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

    red_mask = (
        _detect_red(image, state.red_sensitivity)
        if state.preset != Preset.PHOTO_BW
        else [False] * (WIDTH * HEIGHT)
    )
    classes = _quantize(image, red_mask, state)
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
    else:
        image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=180, threshold=2))

    brightness_factor = 2.0 ** (state.brightness / 5.0)
    contrast_factor = 2.0 ** (state.contrast / 4.0)
    image = ImageEnhance.Brightness(image).enhance(brightness_factor)
    return ImageEnhance.Contrast(image).enhance(contrast_factor)


def _detect_red(image: Image.Image, sensitivity: int) -> list[bool]:
    sensitivity = max(0, min(10, sensitivity))
    hsv_pixels = list(image.convert("HSV").getdata())
    rgb_pixels = list(image.getdata())
    hue_span = 10 + sensitivity * 2
    minimum_saturation = 190 - sensitivity * 13
    minimum_value = 45
    dominance = 1.45 - sensitivity * 0.035

    raw_mask: list[bool] = []
    for (hue, saturation, value), (red, green, blue) in zip(
        hsv_pixels, rgb_pixels, strict=True
    ):
        hue_is_red = hue <= hue_span or hue >= 255 - hue_span
        dominant = red > green * dominance and red > blue * dominance
        raw_mask.append(
            hue_is_red
            and saturation >= minimum_saturation
            and value >= minimum_value
            and dominant
        )

    cleaned = raw_mask.copy()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            index = y * WIDTH + x
            if not raw_mask[index]:
                continue
            neighbours = 0
            for near_y in range(max(0, y - 1), min(HEIGHT, y + 2)):
                for near_x in range(max(0, x - 1), min(WIDTH, x + 2)):
                    if near_x == x and near_y == y:
                        continue
                    if raw_mask[near_y * WIDTH + near_x]:
                        neighbours += 1
            if neighbours == 0:
                cleaned[index] = False
    return cleaned


def _quantize(image: Image.Image, red_mask: list[bool], state: EditState) -> bytearray:
    luminance = [float(value) for value in image.convert("L").getdata()]
    classes = bytearray(WIDTH * HEIGHT)
    dither_strength = 0.0 if state.preset == Preset.TEXT_LOGO else state.dither / 10.0
    threshold = 145.0 if state.preset == Preset.TEXT_LOGO else 128.0

    for y in range(HEIGHT):
        for x in range(WIDTH):
            index = y * WIDTH + x
            if red_mask[index]:
                classes[index] = RED
                continue

            old_value = max(0.0, min(255.0, luminance[index]))
            new_value = 255.0 if old_value >= threshold else 0.0
            classes[index] = WHITE if new_value == 255.0 else BLACK
            error = (old_value - new_value) * dither_strength
            if error == 0.0:
                continue
            _diffuse(luminance, red_mask, x + 1, y, error * 7.0 / 16.0)
            _diffuse(luminance, red_mask, x - 1, y + 1, error * 3.0 / 16.0)
            _diffuse(luminance, red_mask, x, y + 1, error * 5.0 / 16.0)
            _diffuse(luminance, red_mask, x + 1, y + 1, error * 1.0 / 16.0)
    return classes


def _diffuse(
    luminance: list[float],
    red_mask: list[bool],
    x: int,
    y: int,
    error: float,
) -> None:
    if x < 0 or x >= WIDTH or y < 0 or y >= HEIGHT:
        return
    index = y * WIDTH + x
    if not red_mask[index]:
        luminance[index] += error


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

