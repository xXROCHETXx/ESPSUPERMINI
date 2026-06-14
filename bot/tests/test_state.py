import base64
import struct
from dataclasses import replace

from bot.state import (
    Action,
    EditState,
    Preset,
    apply_action,
    decode_callback,
    encode_callback,
)


def test_callback_round_trip_stays_below_telegram_limit() -> None:
    state = EditState(
        preset=Preset.TEXT_LOGO,
        zoom=7,
        pan_x=-4,
        pan_y=8,
        brightness=-2,
        contrast=6,
        dither=3,
        red_sensitivity=9,
        sharpness=4,
    )
    encoded = encode_callback(Action.PUBLISH, state)
    action, decoded = decode_callback(encoded)

    assert len(encoded.encode()) <= 64
    assert action == Action.PUBLISH
    assert decoded == state


def test_preset_change_preserves_crop_and_resets_tone() -> None:
    state = replace(EditState.defaults(Preset.PHOTO_BWR), zoom=3, pan_x=2, contrast=7)
    updated = apply_action(Action.STYLE_BW, state)

    assert updated.preset == Preset.PHOTO_BW
    assert updated.zoom == 3
    assert updated.pan_x == 2
    assert updated.contrast == 1
    assert updated.red_sensitivity == 0


def test_bwr_defaults_match_reference_three_colour_dithering() -> None:
    state = EditState.defaults(Preset.PHOTO_BWR)

    assert state.contrast == 0
    assert state.dither == 10
    assert state.red_sensitivity == 5
    assert state.sharpness == 0


def test_legacy_callback_defaults_to_zero_sharpness() -> None:
    raw = struct.pack(
        ">BBBBbbbbBB",
        1,
        int(Action.BRIGHTNESS_UP),
        int(Preset.PHOTO_BWR),
        0,
        0,
        0,
        0,
        0,
        10,
        5,
    )
    encoded = "e1" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    action, state = decode_callback(encoded)

    assert action == Action.BRIGHTNESS_UP
    assert state.sharpness == 0


def test_adjustments_are_clamped() -> None:
    state = EditState.defaults(Preset.PHOTO_BWR)
    for _ in range(20):
        state = apply_action(Action.ZOOM_IN, state)
        state = apply_action(Action.RED_UP, state)
        state = apply_action(Action.SHARPNESS_UP, state)
    assert state.zoom == 10
    assert state.red_sensitivity == 10
    assert state.sharpness == 10
