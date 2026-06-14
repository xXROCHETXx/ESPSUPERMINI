from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from dataclasses import dataclass, replace

from telegram import Message, MessageEntity

from .state import EditState


SESSION_URL_PREFIX = "https://telegram.org/#epd-manual="


@dataclass(frozen=True)
class ManualSession:
    callback_data: str
    chat_id: int
    preview_message_id: int
    file_id: str


def encode_manual_session(session: ManualSession, secret: str) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "s": session.callback_data,
            "c": session.chat_id,
            "m": session.preview_message_id,
            "f": session.file_id,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(
        secret.encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).digest()[:12]
    encoded_signature = (
        base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    )
    return f"{SESSION_URL_PREFIX}{encoded}.{encoded_signature}"


def decode_manual_session(url: str, secret: str) -> ManualSession:
    if not url.startswith(SESSION_URL_PREFIX):
        raise ValueError("Unknown manual session")
    token = url.removeprefix(SESSION_URL_PREFIX)
    try:
        encoded, encoded_signature = token.split(".", 1)
        signature = base64.urlsafe_b64decode(
            encoded_signature + "=" * (-len(encoded_signature) % 4)
        )
        expected = hmac.new(
            secret.encode("utf-8"),
            encoded.encode("ascii"),
            hashlib.sha256,
        ).digest()[:12]
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid manual session signature")
        payload = base64.urlsafe_b64decode(
            encoded + "=" * (-len(encoded) % 4)
        )
        data = json.loads(payload)
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
    ) as error:
        raise ValueError("Invalid manual session") from error
    if data.get("v") != 1:
        raise ValueError("Unsupported manual session")
    return ManualSession(
        callback_data=str(data["s"]),
        chat_id=int(data["c"]),
        preview_message_id=int(data["m"]),
        file_id=str(data["f"]),
    )


def manual_session_url(message: Message | None) -> str | None:
    if message is None:
        return None
    for entity in message.entities or ():
        if (
            entity.type == MessageEntity.TEXT_LINK
            and entity.url
            and entity.url.startswith(SESSION_URL_PREFIX)
        ):
            return entity.url
    return None


def parse_manual_values(text: str, state: EditState) -> EditState:
    values = [int(value) for value in re.findall(r"(?<!\d)-?\d+", text)]
    if len(values) != 5:
        raise ValueError(
            "Escribe exactamente 5 numeros: brillo contraste trama nitidez rojo."
        )

    brightness, contrast, dither, sharpness, red_sensitivity = values
    ranges = (
        ("brillo", brightness, -5, 5),
        ("contraste", contrast, -5, 8),
        ("trama", dither, 0, 10),
        ("nitidez", sharpness, 0, 10),
        ("rojo", red_sensitivity, 0, 10),
    )
    for name, value, minimum, maximum in ranges:
        if not minimum <= value <= maximum:
            raise ValueError(
                f"{name.capitalize()} debe estar entre {minimum} y {maximum}."
            )

    return replace(
        state,
        brightness=brightness,
        contrast=contrast,
        dither=dither,
        sharpness=sharpness,
        red_sensitivity=red_sensitivity,
    )
