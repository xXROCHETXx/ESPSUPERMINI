from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .epd_format import HEIGHT, PLANE_SIZE, WIDTH, build_epd
from .state import EditState, Preset


WHITE = 0
BLACK = 1
RED = 2


@dataclass(frozen=True)
class ProcessedImage:
    preview_png: bytes
    epd_data: bytes
    black_plane: bytes
    red_plane: bytes | None
    black_pixels: int
    red_pixels: int


def load_source(data: bytes) -> Image.Image:
    with Image.open(BytesIO(data)) as opened:
        oriented = ImageOps.exif_transpose(opened)
        if oriented.mode in ("RGBA", "LA") or (
            oriented.mode == "P" and "transparency" in oriented.info
        ):
            rgba = oriented.convert("RGBA")
            background = Image.new("RGBA", rgba.size, "white")
            background.alpha_composite(rgba)
            return background.convert("RGB")
        return oriented.convert("RGB")


def process_image(source: Image.Image, state: EditState) -> ProcessedImage:
    state = state.validated()
    image = _crop_and_resize(source, state)
    image = _apply_filters(image, state)

    classes = _quantize(image, state)
    black_plane, red_plane, black_pixels, red_pixels = _pack_planes(
        classes,
        include_red=state.preset != Preset.PHOTO_BW,
    )
    preview = _make_preview(classes)
    epd_data = build_epd(black_plane, red_plane)
    return ProcessedImage(
        preview_png=preview,
        epd_data=epd_data,
        black_plane=black_plane,
        red_plane=red_plane,
        black_pixels=black_pixels,
        red_pixels=red_pixels,
    )


def crop_box(source_size: tuple[int, int], state: EditState) -> tuple[int, int, int, int]:
    source_width, source_height = source_size
    target_ratio = WIDTH / HEIGHT
    source_ratio = source_width / source_height

    if source_ratio >= target_ratio:
        base_height = float(source_height)
        base_width = base_height * target_ratio
    else:
        base_width = float(source_width)
        base_height = base_width / target_ratio

    zoom_factor = 1.0 + state.validated().zoom * 0.12
    crop_width = max(1.0, base_width / zoom_factor)
    crop_height = max(1.0, base_height / zoom_factor)
    available_x = max(0.0, source_width - crop_width)
    available_y = max(0.0, source_height - crop_height)

    left = available_x * (state.pan_x + 10) / 20.0
    top = available_y * (state.pan_y + 10) / 20.0
    left = max(0.0, min(available_x, left))
    top = max(0.0, min(available_y, top))
    right = left + crop_width
    bottom = top + crop_height
    return (
        int(round(left)),
        int(round(top)),
        int(round(right)),
        int(round(bottom)),
    )


def _crop_and_resize(source: Image.Image, state: EditState) -> Image.Image:
    box = crop_box(source.size, state)
    cropped = source.crop(box)
    return cropped.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)


def _apply_filters(image: Image.Image, state: EditState) -> Image.Image:
    if state.preset in (Preset.PHOTO_BWR, Preset.PHOTO_BW):
        image = image.filter(ImageFilter.MedianFilter(size=3))

    if state.sharpness > 0:
        image = image.filter(
            ImageFilter.UnsharpMask(
                radius=1.2,
                percent=state.sharpness * 30,
                threshold=0,
            )
        )

    brightness_factor = 2.0 ** (state.brightness / 5.0)
    contrast_factor = 2.0 ** (state.contrast / 4.0)
    image = ImageEnhance.Brightness(image).enhance(brightness_factor)
    return ImageEnhance.Contrast(image).enhance(contrast_factor)


def _quantize(image: Image.Image, state: EditState) -> bytearray:
    if state.preset == Preset.PHOTO_BW:
        return _quantize_bw(image, state)
    return _quantize_bwr(image, state)


def _quantize_bw(image: Image.Image, state: EditState) -> bytearray:
    luminance = [float(value) for value in image.convert("L").getdata()]
    classes = bytearray(WIDTH * HEIGHT)
    dither_strength = state.dither / 10.0

    for y in range(HEIGHT):
        for x in range(WIDTH):
            index = y * WIDTH + x
            old_value = max(0.0, min(255.0, luminance[index]))
            new_value = 255.0 if old_value >= 128.0 else 0.0
            classes[index] = WHITE if new_value == 255.0 else BLACK
            error = (old_value - new_value) * dither_strength
            if error == 0.0:
                continue
            _diffuse_scalar(luminance, x + 1, y, error * 7.0 / 16.0)
            _diffuse_scalar(luminance, x - 1, y + 1, error * 3.0 / 16.0)
            _diffuse_scalar(luminance, x, y + 1, error * 5.0 / 16.0)
            _diffuse_scalar(luminance, x + 1, y + 1, error * 1.0 / 16.0)
    return classes


def _quantize_bwr(image: Image.Image, state: EditState) -> bytearray:
    pixels = [
        [float(red), float(green), float(blue)]
        for red, green, blue in image.getdata()
    ]
    _adjust_red_sensitivity(pixels, state.red_sensitivity)
    classes = bytearray(WIDTH * HEIGHT)
    dither_strength = (
        0.0 if state.preset == Preset.TEXT_LOGO else state.dither / 10.0
    )
    palette = (
        (WHITE, (255.0, 255.0, 255.0)),
        (BLACK, (0.0, 0.0, 0.0)),
        (RED, (255.0, 0.0, 0.0)),
    )

    for y in range(HEIGHT):
        for x in range(WIDTH):
            index = y * WIDTH + x
            old_red, old_green, old_blue = pixels[index]
            selected_class = WHITE
            selected_colour = palette[0][1]
            selected_distance = float("inf")

            for colour_class, colour in palette:
                distance = (
                    (old_red - colour[0]) ** 2
                    + (old_green - colour[1]) ** 2
                    + (old_blue - colour[2]) ** 2
                )
                if distance < selected_distance:
                    selected_class = colour_class
                    selected_colour = colour
                    selected_distance = distance

            classes[index] = selected_class
            if dither_strength == 0.0:
                continue

            error = (
                (old_red - selected_colour[0]) * dither_strength,
                (old_green - selected_colour[1]) * dither_strength,
                (old_blue - selected_colour[2]) * dither_strength,
            )
            _diffuse_rgb(pixels, x + 1, y, error, 7.0 / 16.0)
            _diffuse_rgb(pixels, x - 1, y + 1, error, 3.0 / 16.0)
            _diffuse_rgb(pixels, x, y + 1, error, 5.0 / 16.0)
            _diffuse_rgb(pixels, x + 1, y + 1, error, 1.0 / 16.0)
    return classes


def _adjust_red_sensitivity(
    pixels: list[list[float]],
    sensitivity: int,
) -> None:
    delta = max(0, min(10, sensitivity)) - 5
    if delta == 0:
        return

    red_shift = delta * 4.0
    other_shift = delta * 2.0
    for pixel in pixels:
        red, green, blue = pixel
        if red <= green or red <= blue:
            continue
        pixel[0] = max(0.0, min(255.0, red + red_shift))
        pixel[1] = max(0.0, min(255.0, green - other_shift))
        pixel[2] = max(0.0, min(255.0, blue - other_shift))


def _diffuse_scalar(values: list[float], x: int, y: int, error: float) -> None:
    if x < 0 or x >= WIDTH or y < 0 or y >= HEIGHT:
        return
    values[y * WIDTH + x] += error


def _diffuse_rgb(
    pixels: list[list[float]],
    x: int,
    y: int,
    error: tuple[float, float, float],
    weight: float,
) -> None:
    if x < 0 or x >= WIDTH or y < 0 or y >= HEIGHT:
        return
    pixel = pixels[y * WIDTH + x]
    pixel[0] += error[0] * weight
    pixel[1] += error[1] * weight
    pixel[2] += error[2] * weight


def _pack_planes(
    classes: bytearray,
    *,
    include_red: bool,
) -> tuple[bytes, bytes | None, int, int]:
    black_plane = bytearray(b"\xff" * PLANE_SIZE)
    red_plane = bytearray(b"\xff" * PLANE_SIZE) if include_red else None
    black_pixels = 0
    red_pixels = 0

    for y in range(HEIGHT):
        row_offset = y * 37
        for x in range(WIDTH):
            colour = classes[y * WIDTH + x]
            byte_index = row_offset + x // 8
            bit_mask = 1 << (7 - (x % 8))
            if colour == BLACK:
                black_plane[byte_index] &= ~bit_mask
                black_pixels += 1
            elif colour == RED and red_plane is not None:
                red_plane[byte_index] &= ~bit_mask
                red_pixels += 1
    return bytes(black_plane), bytes(red_plane) if red_plane is not None else None, black_pixels, red_pixels


def _make_preview(classes: bytearray) -> bytes:
    preview = Image.new("RGB", (WIDTH, HEIGHT), "white")
    pixels = preview.load()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            colour = classes[y * WIDTH + x]
            if colour == BLACK:
                pixels[x, y] = (0, 0, 0)
            elif colour == RED:
                pixels[x, y] = (220, 0, 0)

    preview = preview.resize((WIDTH * 4, HEIGHT * 4), Image.Resampling.NEAREST)
    output = BytesIO()
    output.name = "preview.png"
    preview.save(output, format="PNG", optimize=True)
    return output.getvalue()
