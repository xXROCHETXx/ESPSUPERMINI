import pytest

from bot.manual_values import (
    ManualSession,
    decode_manual_session,
    encode_manual_session,
    parse_manual_values,
)
from bot.state import EditState, Preset


def test_manual_session_round_trip() -> None:
    session = ManualSession("e1example", 123456, 42, "telegram-file-id")

    encoded = encode_manual_session(session, "secret")

    assert decode_manual_session(encoded, "secret") == session


def test_manual_session_rejects_tampering() -> None:
    session = ManualSession("e1example", 123456, 42, "telegram-file-id")
    encoded = encode_manual_session(session, "secret")
    replacement = "A" if encoded[-1] != "A" else "B"
    tampered = encoded[:-1] + replacement

    with pytest.raises(ValueError):
        decode_manual_session(tampered, "secret")


def test_manual_session_url_handles_long_telegram_file_id() -> None:
    session = ManualSession("e1example", 123456, 42, "A" * 160)

    encoded = encode_manual_session(session, "secret")

    assert len(encoded) < 500
    assert decode_manual_session(encoded, "secret") == session


def test_manual_values_accept_numbers_or_named_values() -> None:
    state = EditState.defaults(Preset.PHOTO_BWR)

    plain = parse_manual_values("1 -2 8 4 6", state)
    named = parse_manual_values(
        "brillo=1 contraste=-2 trama=8 nitidez=4 rojo=6",
        state,
    )

    assert plain == named
    assert plain.brightness == 1
    assert plain.contrast == -2
    assert plain.dither == 8
    assert plain.sharpness == 4
    assert plain.red_sensitivity == 6


def test_manual_values_validate_count_and_ranges() -> None:
    state = EditState.defaults(Preset.PHOTO_BWR)

    with pytest.raises(ValueError):
        parse_manual_values("0 0 10", state)
    with pytest.raises(ValueError):
        parse_manual_values("0 0 10 4 11", state)
