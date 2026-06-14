from __future__ import annotations

from telegram import InputMediaPhoto


def preview_photo(data: bytes, caption: str) -> InputMediaPhoto:
    return InputMediaPhoto(media=data, filename="preview.png", caption=caption)
