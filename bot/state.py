from __future__ import annotations

import base64
import struct
from dataclasses import dataclass, replace
from enum import IntEnum


class Preset(IntEnum):
    PHOTO_BWR = 0
    PHOTO_BW = 1
    TEXT_LOGO = 2


class Action(IntEnum):
    PUBLISH = 1
    MENU_STYLE = 2
    MENU_CROP = 3
    MENU_TONE = 4
    CANCEL = 5
    BACK_MAIN = 6

    STYLE_BWR = 10
    STYLE_BW = 11
    STYLE_TEXT = 12

    PAN_UP = 20
    PAN_DOWN = 21
    PAN_LEFT = 22
    PAN_RIGHT = 23
    ZOOM_IN = 24
    ZOOM_OUT = 25
    RESET_CROP = 26

    BRIGHTNESS_UP = 30
    BRIGHTNESS_DOWN = 31
    CONTRAST_UP = 32
    CONTRAST_DOWN = 33
    DITHER_UP = 34
    DITHER_DOWN = 35
    RED_UP = 36
    RED_DOWN = 37
    RESET_TONE = 38


_CODEC = struct.Struct(">BBBBbbbbBB")
_PREFIX = "e1"


@dataclass(frozen=True)
class EditState:
    preset: Preset = Preset.PHOTO_BWR
    zoom: int = 0
    pan_x: int = 0
    pan_y: int = 0
    brightness: int = 0
    contrast: int = 1
    dither: int = 8
    red_sensitivity: int = 5

    @classmethod
    def defaults(cls, preset: Preset) -> "EditState":
        if preset == Preset.PHOTO_BW:
            return cls(preset=preset, contrast=1, dither=8, red_sensitivity=0)
        if preset == Preset.TEXT_LOGO:
            return cls(preset=preset, contrast=4, dither=0, red_sensitivity=6)
        return cls(preset=preset, contrast=1, dither=8, red_sensitivity=5)

    def with_preset(self, preset: Preset) -> "EditState":
        defaults = self.defaults(preset)
        return replace(
            defaults,
            zoom=self.zoom,
            pan_x=self.pan_x,
            pan_y=self.pan_y,
        )

    def reset_tone(self) -> "EditState":
        return self.with_preset(self.preset)

    def validated(self) -> "EditState":
        return replace(
            self,
            preset=Preset(int(self.preset)),
            zoom=max(0, min(10, int(self.zoom))),
            pan_x=max(-10, min(10, int(self.pan_x))),
            pan_y=max(-10, min(10, int(self.pan_y))),
            brightness=max(-5, min(5, int(self.brightness))),
            contrast=max(-5, min(8, int(self.contrast))),
            dither=max(0, min(10, int(self.dither))),
            red_sensitivity=max(0, min(10, int(self.red_sensitivity))),
        )


def encode_callback(action: Action, state: EditState) -> str:
    state = state.validated()
    raw = _CODEC.pack(
        1,
        int(action),
        int(state.preset),
        state.zoom,
        state.pan_x,
        state.pan_y,
        state.brightness,
        state.contrast,
        state.dither,
        state.red_sensitivity,
    )
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    value = _PREFIX + encoded
    if len(value.encode("utf-8")) > 64:
        raise ValueError("Telegram callback_data exceeds 64 bytes")
    return value


def decode_callback(value: str) -> tuple[Action, EditState]:
    if not value.startswith(_PREFIX):
        raise ValueError("Unknown callback prefix")
    encoded = value[len(_PREFIX) :]
    encoded += "=" * (-len(encoded) % 4)
    raw = base64.urlsafe_b64decode(encoded)
    if len(raw) != _CODEC.size:
        raise ValueError("Invalid callback state length")
    (
        version,
        action,
        preset,
        zoom,
        pan_x,
        pan_y,
        brightness,
        contrast,
        dither,
        red_sensitivity,
    ) = _CODEC.unpack(raw)
    if version != 1:
        raise ValueError("Unsupported callback state version")
    state = EditState(
        preset=Preset(preset),
        zoom=zoom,
        pan_x=pan_x,
        pan_y=pan_y,
        brightness=brightness,
        contrast=contrast,
        dither=dither,
        red_sensitivity=red_sensitivity,
    ).validated()
    return Action(action), state


def apply_action(action: Action, state: EditState) -> EditState:
    if action == Action.STYLE_BWR:
        return state.with_preset(Preset.PHOTO_BWR)
    if action == Action.STYLE_BW:
        return state.with_preset(Preset.PHOTO_BW)
    if action == Action.STYLE_TEXT:
        return state.with_preset(Preset.TEXT_LOGO)
    if action == Action.PAN_UP:
        return replace(state, pan_y=state.pan_y - 1).validated()
    if action == Action.PAN_DOWN:
        return replace(state, pan_y=state.pan_y + 1).validated()
    if action == Action.PAN_LEFT:
        return replace(state, pan_x=state.pan_x - 1).validated()
    if action == Action.PAN_RIGHT:
        return replace(state, pan_x=state.pan_x + 1).validated()
    if action == Action.ZOOM_IN:
        return replace(state, zoom=state.zoom + 1).validated()
    if action == Action.ZOOM_OUT:
        return replace(state, zoom=state.zoom - 1).validated()
    if action == Action.RESET_CROP:
        return replace(state, zoom=0, pan_x=0, pan_y=0)
    if action == Action.BRIGHTNESS_UP:
        return replace(state, brightness=state.brightness + 1).validated()
    if action == Action.BRIGHTNESS_DOWN:
        return replace(state, brightness=state.brightness - 1).validated()
    if action == Action.CONTRAST_UP:
        return replace(state, contrast=state.contrast + 1).validated()
    if action == Action.CONTRAST_DOWN:
        return replace(state, contrast=state.contrast - 1).validated()
    if action == Action.DITHER_UP:
        return replace(state, dither=state.dither + 1).validated()
    if action == Action.DITHER_DOWN:
        return replace(state, dither=state.dither - 1).validated()
    if action == Action.RED_UP:
        return replace(state, red_sensitivity=state.red_sensitivity + 1).validated()
    if action == Action.RED_DOWN:
        return replace(state, red_sensitivity=state.red_sensitivity - 1).validated()
    if action == Action.RESET_TONE:
        return state.reset_tone()
    return state

