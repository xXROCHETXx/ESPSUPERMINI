from io import BytesIO

from PIL import Image

from bot.epd_format import HEIGHT, PLANE_SIZE, WIDTH, Mode, parse_epd
from bot.image_pipeline import crop_box, load_source, process_image
from bot.state import EditState, Preset


def test_crop_preserves_display_aspect_ratio() -> None:
    box = crop_box((1000, 1000), EditState())
    width = box[2] - box[0]
    height = box[3] - box[1]
    assert abs(width / height - WIDTH / HEIGHT) < 0.01


def test_crop_controls_move_and_zoom_without_leaving_source() -> None:
    centered = crop_box((1200, 800), EditState())
    adjusted = crop_box(
        (1200, 800),
        EditState(zoom=5, pan_x=10, pan_y=-10),
    )

    assert adjusted[2] - adjusted[0] < centered[2] - centered[0]
    assert adjusted[3] - adjusted[1] < centered[3] - centered[1]
    assert 0 <= adjusted[0] < adjusted[2] <= 1200
    assert 0 <= adjusted[1] < adjusted[3] <= 800


def test_bw_output_omits_red_plane() -> None:
    source = Image.new("RGB", (600, 400), (220, 0, 0))
    result = process_image(source, EditState.defaults(Preset.PHOTO_BW))
    parsed = parse_epd(result.epd_data)

    assert parsed.mode == Mode.BW
    assert parsed.red_plane is None
    assert len(parsed.black_plane) == PLANE_SIZE
    assert result.red_pixels == 0


def test_bwr_detects_red_and_never_overlaps_planes() -> None:
    source = Image.new("RGB", (WIDTH, HEIGHT), (230, 20, 20))
    result = process_image(source, EditState.defaults(Preset.PHOTO_BWR))
    parsed = parse_epd(result.epd_data)

    assert parsed.mode == Mode.BWR
    assert result.red_pixels > WIDTH * HEIGHT * 0.95
    assert parsed.red_plane is not None
    for black, red in zip(parsed.black_plane, parsed.red_plane, strict=True):
        assert not (((~black) & 0xFF) & ((~red) & 0xFF))


def test_isolated_red_noise_is_removed() -> None:
    source = Image.new("RGB", (WIDTH, HEIGHT), "white")
    source.putpixel((WIDTH // 2, HEIGHT // 2), (255, 0, 0))
    result = process_image(source, EditState.defaults(Preset.PHOTO_BWR))

    assert result.red_pixels == 0


def test_red_sensitivity_changes_muted_red_result() -> None:
    source = Image.new("RGB", (WIDTH, HEIGHT), (160, 120, 120))
    low_state = EditState(
        preset=Preset.PHOTO_BWR,
        contrast=1,
        dither=8,
        red_sensitivity=0,
    )
    low = process_image(
        source,
        low_state,
    )
    high_state = EditState(
        preset=Preset.PHOTO_BWR,
        contrast=1,
        dither=8,
        red_sensitivity=10,
    )
    high = process_image(source, high_state)

    assert high.red_pixels > low.red_pixels


def test_warm_wood_and_skin_tones_do_not_flood_red() -> None:
    source = Image.new("RGB", (WIDTH, HEIGHT), (175, 95, 45))
    result = process_image(source, EditState.defaults(Preset.PHOTO_BWR))

    assert result.red_pixels < WIDTH * HEIGHT * 0.01


def test_dark_red_uses_red_and_black_as_a_visual_shade() -> None:
    source = Image.new("RGB", (WIDTH, HEIGHT), (105, 8, 8))
    result = process_image(source, EditState.defaults(Preset.PHOTO_BWR))

    assert WIDTH * HEIGHT * 0.25 < result.red_pixels < WIDTH * HEIGHT * 0.75
    assert result.black_pixels > WIDTH * HEIGHT * 0.20


def test_exif_orientation_is_applied() -> None:
    source = Image.new("RGB", (40, 20), "white")
    exif = Image.Exif()
    exif[274] = 6
    encoded = BytesIO()
    source.save(encoded, format="JPEG", exif=exif)

    loaded = load_source(encoded.getvalue())
    assert loaded.size == (20, 40)
