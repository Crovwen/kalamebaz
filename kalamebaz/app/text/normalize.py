"""نرمال‌سازی متن فارسی.

- ي/ى → ی ، ك → ک ، ة/ۀ → ه ، أ/إ/ٱ → ا
- حذف اعراب، کشیده، نیم‌فاصله و نویسه‌های جهت‌دهی نامرئی
- فشرده‌سازی فاصله‌ها
- تبدیل شکل‌های نمایشی عربی (ﻣﺎﺩﺭ) با NFKC
آ، ئ و ؤ عمداً حفظ می‌شوند چون حرف مستقل‌اند.
"""
from __future__ import annotations

import re
import unicodedata
from itertools import combinations

PERSIAN_LETTERS = frozenset("آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهیئؤ")

ZWNJ = "\u200c"
_TRANS = str.maketrans(
    {
        "ي": "ی", "ى": "ی", "ې": "ی", "ێ": "ی",
        "ك": "ک", "ڪ": "ک",
        "ة": "ه", "ۀ": "ه", "ە": "ه",
        "أ": "ا", "إ": "ا", "ٱ": "ا",
    }
)
_STRIP = re.compile(
    "[\u064b-\u065f\u0670\u0640\u200b\u200d\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]"
)
_WS = re.compile(r"\s+")
_ZWNJ_RUN = re.compile("\u200c+")
_PUNCT = " \t\n.,!?؟،؛:;\"'«»()[]{}…-_*~"
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _base(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = t.translate(_TRANS)
    return _STRIP.sub("", t)


def normalize(text: str) -> str:
    """شکل نرمال برای مقایسه: بدون نیم‌فاصله، با فاصله‌های فشرده."""
    t = _base(text).replace(ZWNJ, "")
    return _WS.sub(" ", t).strip()


def normalize_display(text: str) -> str:
    """شکل نمایشی: نیم‌فاصله حفظ می‌شود (بدون تکرار)."""
    t = _ZWNJ_RUN.sub(ZWNJ, _base(text))
    return _WS.sub(" ", t).strip().strip(ZWNJ)


def strip_punct(text: str) -> str:
    return text.strip(_PUNCT)


def compact_key(text: str) -> str:
    """کلید مقایسه دستورات: بدون هیچ فاصله و نیم‌فاصله و علامت حاشیه‌ای."""
    return strip_punct(normalize(text)).replace(" ", "")


def is_persian_word(norm: str) -> bool:
    return bool(norm) and all(ch in PERSIAN_LETTERS for ch in norm)


def letters_signature(norm: str) -> str:
    return "".join(sorted(norm))


def sub_signatures(letters: list[str], min_len: int = 3) -> list[str]:
    """همه امضاهای مرتب‌شده‌ی زیرمجموعه‌های حروف (بدون تکرار)."""
    s = sorted(letters)
    out: set[str] = set()
    for r in range(min_len, len(s) + 1):
        for combo in combinations(s, r):
            out.add("".join(combo))
    return sorted(out)


def fa(n: int | str) -> str:
    return str(n).translate(_FA_DIGITS)
