import zlib

import pytest

from bot.epd_format import HEADER_SIZE, PLANE_SIZE, Mode, build_epd, parse_epd


def test_bw_round_trip() -> None:
    black = bytes([0xAA]) * PLANE_SIZE
    encoded = build_epd(black, published_at=123)
    parsed = parse_epd(encoded)

    assert len(encoded) == HEADER_SIZE + PLANE_SIZE
    assert parsed.mode == Mode.BW
    assert parsed.published_at == 123
    assert parsed.black_plane == black
    assert parsed.red_plane is None
    assert parsed.payload_crc == zlib.crc32(black) & 0xFFFFFFFF


def test_bwr_round_trip() -> None:
    black = bytes([0xF0]) * PLANE_SIZE
    red = bytes([0x0F]) * PLANE_SIZE
    parsed = parse_epd(build_epd(black, red, published_at=456))

    assert parsed.mode == Mode.BWR
    assert parsed.red_plane == red


def test_rejects_overlap() -> None:
    black = bytes([0xFE]) + bytes([0xFF]) * (PLANE_SIZE - 1)
    red = bytes([0xFE]) + bytes([0xFF]) * (PLANE_SIZE - 1)
    with pytest.raises(ValueError, match="simultaneously"):
        build_epd(black, red)


def test_rejects_corruption_and_truncation() -> None:
    encoded = bytearray(build_epd(bytes([0xFF]) * PLANE_SIZE))
    encoded[-1] ^= 1
    with pytest.raises(ValueError, match="CRC32"):
        parse_epd(bytes(encoded))
    with pytest.raises(ValueError, match="Truncated"):
        parse_epd(bytes(encoded[:10]))

