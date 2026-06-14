from telegram import InputFile

from bot.telegram_media import preview_photo


def test_preview_photo_uses_multipart_attachment() -> None:
    media = preview_photo(b"png-data", "Vista previa")

    assert isinstance(media.media, InputFile)
    assert media.media.attach_uri is not None
    assert media.media.filename == "preview.png"
    assert media.caption == "Vista previa"
