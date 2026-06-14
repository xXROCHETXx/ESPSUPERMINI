from __future__ import annotations

import hashlib


def normalize_webhook_secret(secret: str) -> str:
    """Return a deterministic Telegram-compatible webhook secret."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()
