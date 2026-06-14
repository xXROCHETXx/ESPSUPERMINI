from bot.webhook import normalize_webhook_secret


def test_normalized_secret_is_telegram_compatible_and_deterministic() -> None:
    source = "render/value+with=unsupported@characters"

    normalized = normalize_webhook_secret(source)

    assert normalized == normalize_webhook_secret(source)
    assert len(normalized) == 64
    assert normalized.isascii()
    assert normalized.isalnum()
    assert normalized != source
