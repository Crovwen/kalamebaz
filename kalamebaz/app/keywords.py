"""کلمات کلیدی فارسی (بدون اسلش). مقایسه بعد از نرمال‌سازی و حذف فاصله/نیم‌فاصله است."""
from __future__ import annotations

from app.text.normalize import compact_key, normalize, strip_punct

_PHRASES: dict[str, list[str]] = {
    "start": ["شروع بازی", "بازی شروع"],
    "stop": ["توقف بازی", "بازی توقف"],
    "next": ["مرحله بعد", "مرحله بعدی", "بازی بعدی", "بازی مرحله بعد"],
    "help": ["راهنمای بازی", "بازی راهنما"],
    "me": ["امتیاز من", "بازی امتیاز"],
    "top": ["برترین‌ها", "بازی برترین‌ها", "بازی برترین ها"],
    "global": ["رتبه جهانی", "بازی رتبه جهانی"],
    "stats": ["آمار بازی", "بازی آمار"],
    "settings": ["تنظیمات بازی", "بازی تنظیمات"],
    "status": ["وضعیت بازی", "بازی وضعیت"],
}

LOOKUP: dict[str, str] = {compact_key(p): cmd for cmd, ps in _PHRASES.items() for p in ps}
# کلمات رزروشده هرگز به‌عنوان جواب معما انتخاب نمی‌شوند.
RESERVED: frozenset[str] = frozenset(LOOKUP)

ADMIN_ONLY = {"stop", "next", "settings"}
SUGGEST_PREFIX = "پیشنهاد کلمه"


def match_command(text: str | None) -> str | None:
    if not text or len(text) > 40:
        return None
    return LOOKUP.get(compact_key(text))


def parse_suggestion(text: str | None) -> str | None:
    if not text or len(text) > 60:
        return None
    n = strip_punct(normalize(text))
    prefix = normalize(SUGGEST_PREFIX)
    if n.startswith(prefix + " "):
        rest = n[len(prefix):].strip()
        if rest and " " not in rest:
            return rest
    return None
