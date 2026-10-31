"""ورود واژگان از TXT / CSV / JSON با حذف تکراری‌ها.

TXT: یک یا چند کلمه در هر خط؛ «کلمه ۱۲۳» یعنی کلمه + بسامد. خطوط «#difficulty=2»
و «#category=literary» و «#puzzle=1» مقدار پیش‌فرض بلوک بعدی را تعیین می‌کنند.
CSV: ستون‌های word,freq,category,difficulty,puzzle_ok,bonus_ok (سرایند اختیاری).
JSON: لیست رشته‌ها، لیست دیکشنری، یا دیکشنری {کلمه: بسامد}.

CLI:
  python -m app.words.importer add FILE... --source NAME [--category common] [--trust-puzzle]
  python -m app.words.importer freq FILE --source NAME      # فقط بسامد کلمات موجود
  python -m app.words.importer recompute [--min-freq 50]    # سختی از روی بسامد + puzzle_ok
  python -m app.words.importer stats
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from app.text.normalize import (
    PERSIAN_LETTERS, is_persian_word, letters_signature, normalize, normalize_display,
)

log = logging.getLogger(__name__)
MIN_LEN, MAX_LEN = 2, 14
PUZZLE_MIN, PUZZLE_MAX = 3, 8


@dataclass
class Report:
    total: int = 0
    accepted: int = 0
    inserted: int = 0
    rejected: dict[str, int] = field(default_factory=dict)

    def reject(self, why: str) -> None:
        self.rejected[why] = self.rejected.get(why, 0) + 1

    def text(self) -> str:
        rej = "، ".join(f"{k}: {v}" for k, v in self.rejected.items()) or "—"
        return f"کل: {self.total} | معتبر: {self.accepted} | جدید: {self.inserted} | ردشده: {rej}"


def _to_bool(v) -> bool | None:
    if v is None or v == "":
        return None
    return str(v).strip().lower() in {"1", "true", "yes", "y", "بله"}


def _to_int(v, default=None):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return default


def parse_txt(text: str) -> Iterator[dict]:
    defaults: dict = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if "=" in line:
                k, v = line[1:].split("=", 1)
                defaults[k.strip()] = v.strip()
            continue
        toks = line.replace("\t", " ").replace(",", " ").replace("،", " ").split()
        if len(toks) == 2 and toks[1].isdigit():
            yield {"word": toks[0], "freq": int(toks[1]), **defaults}
        else:
            for t in toks:
                if not t.isdigit():
                    yield {"word": t, **defaults}


def parse_csv(text: str) -> Iterator[dict]:
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return
    header = [c.strip().lower() for c in rows[0]]
    if "word" in header:
        for r in rows[1:]:
            yield {h: v for h, v in zip(header, r)}
    else:
        for r in rows:
            if r:
                d = {"word": r[0]}
                if len(r) > 1:
                    d["freq"] = r[1]
                yield d


def parse_json(text: str) -> Iterator[dict]:
    data = json.loads(text)
    if isinstance(data, dict):
        for k, v in data.items():
            yield {"word": k, "freq": v}
    else:
        for item in data:
            yield {"word": item} if isinstance(item, str) else dict(item)


def iter_rows(data: bytes, filename: str) -> Iterator[dict]:
    text = data.decode("utf-8-sig", errors="replace")
    ext = Path(filename).suffix.lower()
    if ext == ".json":
        return parse_json(text)
    if ext == ".csv":
        return parse_csv(text)
    return parse_txt(text)


def prepare(
    rows: Iterator[dict], *, source: str, category: str = "common",
    trust_puzzle: bool = False, difficulty: int = 3,
) -> tuple[list[tuple], Report]:
    rep = Report()
    merged: dict[str, tuple] = {}
    for r in rows:
        rep.total += 1
        word = str(r.get("word", "")).strip()
        norm = normalize(word)
        if not norm or " " in norm:
            rep.reject("چندکلمه‌ای/خالی")
            continue
        if not is_persian_word(norm):
            rep.reject("نویسه غیرفارسی")
            continue
        if not (MIN_LEN <= len(norm) <= MAX_LEN):
            rep.reject("طول نامجاز")
            continue
        freq = _to_int(r.get("freq"), 0) or 0
        cat = (r.get("category") or category or "common").strip()
        diff = min(5, max(1, _to_int(r.get("difficulty"), difficulty)))
        puzzle = _to_bool(r.get("puzzle_ok"))
        if puzzle is None:
            puzzle = _to_bool(r.get("puzzle"))
        if puzzle is None:
            puzzle = trust_puzzle
        puzzle = bool(puzzle) and PUZZLE_MIN <= len(norm) <= PUZZLE_MAX and cat != "name"
        bonus = _to_bool(r.get("bonus_ok"))
        bonus = True if bonus is None else bonus
        prev = merged.get(norm)
        if prev:
            freq = max(freq, prev[4])
            puzzle = puzzle or prev[8]
        merged[norm] = (
            norm, normalize_display(word), len(norm), letters_signature(norm),
            freq, diff, cat, [source], puzzle, bonus,
        )
    rep.accepted = len(merged)
    return list(merged.values()), rep


UPSERT = """
INSERT INTO words(norm,display,length,letters_sig,freq,difficulty,category,sources,puzzle_ok,bonus_ok)
VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
ON CONFLICT (norm) DO UPDATE SET
  freq = GREATEST(words.freq, EXCLUDED.freq),
  sources = (SELECT ARRAY(SELECT DISTINCT unnest(words.sources || EXCLUDED.sources))),
  puzzle_ok = words.puzzle_ok OR EXCLUDED.puzzle_ok,
  bonus_ok = words.bonus_ok OR EXCLUDED.bonus_ok
"""


async def upsert_words(pool, tuples: list[tuple], report: Report, *, filename="", source="") -> Report:
    async with pool.acquire() as conn:
        before = await conn.fetchval("SELECT count(*) FROM words")
        for i in range(0, len(tuples), 5000):
            await conn.executemany(UPSERT, tuples[i : i + 5000])
        after = await conn.fetchval("SELECT count(*) FROM words")
        report.inserted = after - before
        await conn.execute(
            "INSERT INTO import_batches(filename,source,total,inserted,rejected) VALUES($1,$2,$3,$4,$5)",
            filename, source, report.total, report.inserted, sum(report.rejected.values()),
        )
    return report


async def update_freq(pool, tuples: list[tuple], report: Report) -> Report:
    async with pool.acquire() as conn:
        for i in range(0, len(tuples), 5000):
            chunk = [(t[0], t[4]) for t in tuples[i : i + 5000]]
            await conn.executemany("UPDATE words SET freq = GREATEST(freq,$2) WHERE norm=$1", chunk)
    return report


async def recompute(pool, min_freq: int = 50) -> str:
    """سختی (۱ تا ۵) از روی چندک بسامد؛ puzzle_ok از روی حداقل بسامد و طول."""
    async with pool.acquire() as conn:
        await conn.execute(
            "WITH r AS (SELECT id, NTILE(5) OVER (ORDER BY freq DESC) AS q FROM words WHERE freq > 0) "
            "UPDATE words w SET difficulty = r.q FROM r WHERE w.id = r.id"
        )
        res = await conn.execute(
            "UPDATE words SET puzzle_ok = ((freq >= $1 AND length BETWEEN $2 AND $3 "
            "AND status='approved' AND category <> 'name') OR 'seed' = ANY(sources) OR 'manual' = ANY(sources)) "
            "AND status='approved'",
            min_freq, PUZZLE_MIN, PUZZLE_MAX,
        )
        n = await conn.fetchval("SELECT count(*) FROM words WHERE puzzle_ok")
    return f"{res}؛ تعداد کلمات مناسب معما: {n}"


async def stats(pool) -> str:
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT count(*) AS total, count(*) FILTER (WHERE puzzle_ok) AS puzzle, "
            "count(*) FILTER (WHERE freq>0) AS with_freq, count(*) FILTER (WHERE status='disabled') AS disabled FROM words"
        )
    return f"کل مدخل‌ها: {r['total']} | مناسب معما: {r['puzzle']} | دارای بسامد: {r['with_freq']} | غیرفعال: {r['disabled']}"


async def import_seed_if_empty(pool) -> None:
    seed = Path(__file__).resolve().parents[2] / "data" / "seed_words.txt"
    async with pool.acquire() as conn:
        n = await conn.fetchval("SELECT count(*) FROM words")
    if n == 0 and seed.exists():
        tuples, rep = prepare(iter_rows(seed.read_bytes(), seed.name), source="seed", trust_puzzle=True)
        await upsert_words(pool, tuples, rep, filename=seed.name, source="seed")
        log.info("بانک اولیه وارد شد: %s", rep.text())


async def _cli(args) -> None:
    from app.db.pool import create_pool, migrate

    pool = await create_pool(os.environ["DATABASE_URL"])
    await migrate(pool)
    if args.cmd in ("add", "freq"):
        for f in args.files:
            p = Path(f)
            tuples, rep = prepare(
                iter_rows(p.read_bytes(), p.name), source=args.source, category=args.category,
                trust_puzzle=args.trust_puzzle, difficulty=args.difficulty,
            )
            if args.cmd == "add":
                await upsert_words(pool, tuples, rep, filename=p.name, source=args.source)
            else:
                await update_freq(pool, tuples, rep)
            print(p.name, "→", rep.text())
    elif args.cmd == "recompute":
        print(await recompute(pool, args.min_freq))
    print(await stats(pool))
    await pool.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="ورود واژگان به بانک کلمه‌باز")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("add", "freq"):
        p = sub.add_parser(name)
        p.add_argument("files", nargs="+")
        p.add_argument("--source", required=True)
        p.add_argument("--category", default="common")
        p.add_argument("--trust-puzzle", action="store_true", help="همه کلمات ۳ تا ۸ حرفی مناسب معما باشند")
        p.add_argument("--difficulty", type=int, default=3)
    r = sub.add_parser("recompute")
    r.add_argument("--min-freq", type=int, default=50)
    sub.add_parser("stats")
    asyncio.run(_cli(ap.parse_args()))


if __name__ == "__main__":
    main()
