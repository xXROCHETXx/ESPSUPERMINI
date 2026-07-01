from __future__ import annotations

import struct
import time
import zlib
from dataclasses import dataclass
from enum import IntEnum


WIDTH = 400
HEIGHT = 300
BYTES_PER_ROW = 50
PLANE_SIZE = BYTES_PER_ROW * HEIGHT
HEADER_SIZE = 24
_HEADER = struct.Struct("<4sBBBBHHHHII")


class Mode(IntEnum):
    BW = 1
    BWR = 2


@dataclass(frozen=True)
class EpdFile:
    mode: Mode
    published_at: int
    payload_crc: int
    black_plane: bytes
    red_plane: bytes | None


def build_epd(
    black_plane: bytes,
    red_plane: bytes | None = None,
    *,
    published_at: int | None = None,
) -> bytes:
    if len(black_plane) != PLANE_SIZE:
        raise ValueError(f"Black plane must contain {PLANE_SIZE} bytes")
    if red_plane is not None and len(red_plane) != PLANE_SIZE:
        raise ValueError(f"Red plane must contain {PLANE_SIZE} bytes")
    if red_plane is not None:
        _validate_no_overlap(black_plane, red_plane)

    mode = Mode.BWR if red_plane is not None else Mode.BW
    payload = black_plane + (red_plane or b"")
    payload_crc = zlib.crc32(payload) & 0xFFFFFFFF
    timestamp = int(time.time()) if published_at is None else int(published_at)
    header = _HEADER.pack(
        b"EPD1",
        1,
        int(mode),
        HEADER_SIZE,
        0,
        WIDTH,
        HEIGHT,
        BYTES_PER_ROW,
        len(payload),
        timestamp,
        payload_crc,
    )
    return header + payload


def parse_epd(data: bytes) -> EpdFile:
    if len(data) < HEADER_SIZE:
        raise ValueError("Truncated EPD file")
    (
        magic,
        version,
        mode_value,
        header_size,
        _flags,
        width,
        height,
        bytes_per_row,
        payload_length,
        published_at,
        expected_crc,
    ) = _HEADER.unpack_from(data)
    if magic != b"EPD1":
        raise ValueError("Invalid EPD magic")
    if version != 1:
        raise ValueError("Unsupported EPD version")
    if header_size != HEADER_SIZE:
        raise ValueError("Invalid EPD header size")
    try:
        mode = Mode(mode_value)
    except ValueError as error:
        raise ValueError("Invalid EPD colour mode") from error
    if (width, height, bytes_per_row) != (WIDTH, HEIGHT, BYTES_PER_ROW):
        raise ValueError("Invalid EPD dimensions")

    expected_length = PLANE_SIZE if mode == Mode.BW else PLANE_SIZE * 2
    if payload_length != expected_length:
        raise ValueError("Invalid EPD payload length")
    if len(data) != HEADER_SIZE + payload_length:
        raise ValueError("Truncated EPD file or trailing data")

    payload = data[HEADER_SIZE:]
    payload_crc = zlib.crc32(payload) & 0xFFFFFFFF
    if payload_crc != expected_crc:
        raise ValueError("Invalid EPD CRC32")

    black_plane = payload[:PLANE_SIZE]
    red_plane = payload[PLANE_SIZE:] if mode == Mode.BWR else None
    if red_plane is not None:
        _validate_no_overlap(black_plane, red_plane)
    return EpdFile(mode, published_at, payload_crc, black_plane, red_plane)


def _validate_no_overlap(black_plane: bytes, red_plane: bytes) -> None:
    for black, red in zip(black_plane, red_plane, strict=True):
        if ((~black) & 0xFF) & ((~red) & 0xFF):
            raise ValueError("A pixel cannot be black and red simultaneously")
