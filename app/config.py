"""تنظیمات برنامه از متغیرهای محیطی."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


@dataclass(frozen=True)
class Config:
    bot_token: str
    owner_id: int
    database_url: str
    mode: str  # webhook | polling
    base_url: str
    webhook_secret: str
    port: int
    allow_names: bool
    button_styles: bool
    log_level: str


def load_config() -> Config:
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN تنظیم نشده است.")
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("DATABASE_URL تنظیم نشده است.")
    owner = os.environ.get("OWNER_ID", "").strip()
    base = (os.environ.get("BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
    mode = os.environ.get("MODE", "webhook" if base else "polling").strip().lower()
    if mode == "webhook" and not base:
        raise RuntimeError("برای حالت webhook مقدار BASE_URL (یا RENDER_EXTERNAL_URL) لازم است.")
    secret = os.environ.get("WEBHOOK_SECRET") or hashlib.sha256(token.encode()).hexdigest()[:32]
    return Config(
        bot_token=token,
        owner_id=int(owner) if owner.isdigit() else 0,
        database_url=dsn,
        mode=mode,
        base_url=base,
        webhook_secret=secret,
        port=int(os.environ.get("PORT", "8080")),
        allow_names=_bool(os.environ.get("ALLOW_NAMES")),
        button_styles=_bool(os.environ.get("BUTTON_STYLES"), True),
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    )
