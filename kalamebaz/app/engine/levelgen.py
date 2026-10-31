"""تولید مرحله: انتخاب کلمه‌ی پایه، پیدا کردن کلمات قابل‌ساخت و گزینش جواب‌ها.

بخش خالص (بدون دیتابیس) در build_level است؛ generate_level با دو تابع async
که از دیتابیس می‌خوانند کار می‌کند تا به‌راحتی تست شود.
"""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable

from app.text.normalize import sub_signatures

DIFF_RANGE = {"easy": (1, 2), "medium": (2, 4), "hard": (3, 5), "mixed": (1, 5)}
MIN_MAIN = 3
MIN_LETTERS = 4


@dataclass(frozen=True, slots=True)
class WordRow:
    id: int
    norm: str
    display: str
    length: int
    difficulty: int
    puzzle_ok: bool
    category: str = "common"


@dataclass
class Level:
    seed: WordRow
    letters: list[str]
    main: list[WordRow]
    bonus: list[WordRow]


def can_build(word: str, letters: Iterable[str]) -> bool:
    need, have = Counter(word), Counter(letters)
    return all(have[c] >= n for c, n in need.items())


def _pick_varied(pool: list[WordRow], count: int, rng: random.Random, picked: list[WordRow]) -> None:
    """از هر طول به‌نوبت انتخاب می‌کند تا جواب‌ها متنوع باشند."""
    groups: dict[int, list[WordRow]] = {}
    for w in pool:
        groups.setdefault(w.length, []).append(w)
    for g in groups.values():
        rng.shuffle(g)
    while len(picked) < count and groups:
        lengths = sorted(groups, key=lambda L: (sum(1 for p in picked if p.length == L), rng.random()))
        L = lengths[0]
        picked.append(groups[L].pop())
        if not groups[L]:
            del groups[L]


def build_level(
    seed: WordRow,
    candidates: Iterable[WordRow],
    *,
    main_count: int,
    diff_range: tuple[int, int],
    use_bonus: bool,
    recent_word_ids: set[int],
    reserved: frozenset[str] | set[str],
    rng: random.Random,
    bonus_cap: int = 30,
    min_main: int = MIN_MAIN,
) -> Level | None:
    letters = list(seed.norm)
    lo, hi = diff_range
    pool = [c for c in candidates if c.id != seed.id and c.norm not in reserved and c.length >= 3]
    mains_pool = [
        c for c in pool
        if c.puzzle_ok and lo <= c.difficulty <= hi and c.id not in recent_word_ids
    ]
    main: list[WordRow] = []
    if lo <= seed.difficulty <= hi and seed.norm not in reserved:
        main.append(seed)
    _pick_varied(mains_pool, main_count, rng, main)
    if len(main) < min_main:
        return None
    main_ids = {m.id for m in main}
    bonus: list[WordRow] = []
    if use_bonus:
        bonus = [c for c in pool if c.id not in main_ids]
        rng.shuffle(bonus)
        bonus = bonus[:bonus_cap]
    shuffled = letters[:]
    for _ in range(10):
        rng.shuffle(shuffled)
        if shuffled != letters:
            break
    return Level(seed=seed, letters=shuffled, main=main, bonus=bonus)


FetchSeeds = Callable[[int, int, int, list[int], int], Awaitable[list[WordRow]]]
FetchCands = Callable[[list[str]], Awaitable[list[WordRow]]]


async def generate_level(
    fetch_seeds: FetchSeeds,
    fetch_candidates: FetchCands,
    *,
    letters: int,
    difficulty: str,
    main_count: int,
    use_bonus: bool,
    recent_seed_ids: set[int],
    recent_word_ids: set[int],
    reserved: frozenset[str] | set[str],
    rng: random.Random,
) -> Level | None:
    """ابتدا با محدودیت تکرار، سپس بدون آن؛ در صورت کمبود کلمه، تعداد حروف کم می‌شود."""
    lo, hi = DIFF_RANGE.get(difficulty, DIFF_RANGE["mixed"])
    best: Level | None = None
    for strict in (True, False):
        r_seeds = recent_seed_ids if strict else set()
        r_words = recent_word_ids if strict else set()
        for n in range(letters, MIN_LETTERS - 1, -1):
            for _attempt in range(4):
                seeds = await fetch_seeds(n, lo, hi, list(r_seeds), 5)
                if not seeds:
                    break
                for seed in seeds:
                    cands = await fetch_candidates(sub_signatures(list(seed.norm)))
                    lvl = build_level(
                        seed, cands, main_count=main_count, diff_range=(lo, hi),
                        use_bonus=use_bonus, recent_word_ids=r_words,
                        reserved=reserved, rng=rng,
                    )
                    if lvl is None:
                        continue
                    if len(lvl.main) >= main_count:
                        return lvl
                    if best is None or len(lvl.main) > len(best.main):
                        best = lvl
            if best is not None and len(best.main) >= max(MIN_MAIN, main_count - 2):
                return best
    return best
