"""دکمه‌های شیشه‌ای. رنگ‌ها با فیلد رسمی style در Bot API: primary(آبی) success(سبز) danger(قرمز)."""
from __future__ import annotations

import logging

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.settings_schema import CHOICES, LABELS, fmt_value

log = logging.getLogger(__name__)
STYLES_ENABLED = True


def _b(text: str, data: str, style: str | None = None) -> InlineKeyboardButton:
    if style and STYLES_ENABLED:
        try:
            return InlineKeyboardButton(text=text, callback_data=data, style=style)
        except Exception:  # نسخه‌ی قدیمی aiogram بدون پشتیبانی style
            log.warning("این نسخه aiogram از style پشتیبانی نمی‌کند؛ دکمه بدون رنگ ساخته شد.")
    return InlineKeyboardButton(text=text, callback_data=data)


def _kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def idle_kb() -> InlineKeyboardMarkup:
    return _kb([
        [_b("🟢 شروع بازی", "g:start", "success")],
        [_b("🏆 امتیازات", "g:top", "primary"), _b("❓ راهنما", "g:help", "primary")],
    ])


def running_kb(hints_max: int) -> InlineKeyboardMarkup:
    first = [_b("🏆 امتیازات", "g:top", "primary")]
    if hints_max > 0:
        first.insert(0, _b("💡 راهنمایی", "g:hint", "primary"))
    return _kb([
        first,
        [_b("📊 وضعیت", "g:status", "primary"), _b("❓ راهنما", "g:help", "primary")],
        [_b("🔴 توقف بازی", "g:stop", "danger")],
    ])


def finished_kb() -> InlineKeyboardMarkup:
    return _kb([
        [_b("🟢 مرحله بعد", "g:next", "success")],
        [_b("🏆 امتیازات", "g:top", "primary"), _b("📊 آمار", "g:stats", "primary")],
    ])


def settings_kb(settings: dict) -> InlineKeyboardMarkup:
    rows = [[_b(f"{LABELS[k]}: {fmt_value(k, settings[k])}", f"s:{k}", "primary")] for k in CHOICES]
    rows.append([_b("🔴 بازنشانی تنظیمات", "s:reset", "danger"), _b("✅ بستن", "s:close", "success")])
    return _kb(rows)


def help_kb() -> InlineKeyboardMarkup:
    return _kb([[_b("🟢 شروع بازی", "g:start", "success")]])


def owner_kb() -> InlineKeyboardMarkup:
    return _kb([
        [_b("📊 آمار کلی", "o:stats", "primary"), _b("📚 بانک واژگان", "o:words", "primary")],
        [_b("🧾 پیشنهادها", "o:sugg", "primary"), _b("📣 اطلاعیه", "o:bc", "primary")],
        [_b("➕ افزودن کلمه", "o:add", "success"), _b("🚫 غیرفعال‌کردن کلمه", "o:dis", "danger")],
        [_b("🏷 نام‌های خاص", "o:names", "primary"), _b("🐞 خطاها", "o:err", "primary")],
        [_b("💾 پشتیبان", "o:backup", "primary")],
    ])


def suggestion_kb(sid: int) -> InlineKeyboardMarkup:
    return _kb([[_b("✅ تأیید", f"o:ap:{sid}", "success"), _b("❌ رد", f"o:rj:{sid}", "danger")]])
