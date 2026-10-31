"""تنظیمات هر گروه: مقدار پیش‌فرض، گزینه‌های مجاز و چرخش مقدار با دکمه."""
from __future__ import annotations

from typing import Any

from app.text.normalize import fa

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "duration": 180,
    "letters": 6,
    "difficulty": "mixed",
    "main_count": 5,
    "bonus": True,
    "hints": 2,
    "auto_next": False,
    "interval": 20,
    "start_policy": "all",
    "show_board": True,
}

CHOICES: dict[str, list[Any]] = {
    "enabled": [True, False],
    "duration": [120, 180, 240, 300],
    "letters": [5, 6, 7, 8],
    "difficulty": ["easy", "medium", "hard", "mixed"],
    "main_count": [4, 5, 6, 7, 8],
    "bonus": [True, False],
    "hints": [0, 1, 2, 3, 5],
    "auto_next": [False, True],
    "interval": [10, 20, 30, 60],
    "start_policy": ["all", "admins"],
    "show_board": [True, False],
}

LABELS: dict[str, str] = {
    "enabled": "🎮 بازی",
    "duration": "⏱ زمان مرحله",
    "letters": "🔤 تعداد حروف",
    "difficulty": "🎯 سختی",
    "main_count": "📝 تعداد جواب‌ها",
    "bonus": "➕ کلمات اضافی",
    "hints": "💡 راهنمایی",
    "auto_next": "🔁 شروع خودکار",
    "interval": "⏳ فاصله مراحل",
    "start_policy": "🚪 شروع بازی",
    "show_board": "🏆 جدول بعد از مرحله",
}

_DIFF = {"easy": "آسان", "medium": "متوسط", "hard": "سخت", "mixed": "ترکیبی"}


def merge(raw: dict | None) -> dict[str, Any]:
    out = dict(DEFAULTS)
    for k, v in (raw or {}).items():
        if k in CHOICES and v in CHOICES[k]:
            out[k] = v
    return out


def cycle(settings: dict[str, Any], key: str) -> dict[str, Any]:
    if key not in CHOICES:
        raise KeyError(key)
    opts = CHOICES[key]
    cur = settings.get(key, DEFAULTS[key])
    nxt = opts[(opts.index(cur) + 1) % len(opts)] if cur in opts else opts[0]
    out = dict(settings)
    out[key] = nxt
    return out


def fmt_value(key: str, value: Any) -> str:
    if key in ("enabled", "bonus", "auto_next", "show_board"):
        return "روشن" if value else "خاموش"
    if key == "duration":
        return f"{fa(value // 60)} دقیقه"
    if key == "interval":
        return f"{fa(value)} ثانیه"
    if key == "difficulty":
        return _DIFF[value]
    if key == "start_policy":
        return "همه اعضا" if value == "all" else "فقط مدیران"
    return fa(value)
