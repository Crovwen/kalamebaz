import asyncio
import random
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.db.repo import period_starts
from app.engine.levelgen import DIFF_RANGE, WordRow, build_level, can_build, generate_level
from app.engine.render import mmss, render_final, render_round
from app.engine.scoring import points_after_hints, word_points
from app.engine.state import RoundState, RWord
from app.keywords import RESERVED
from app.settings_schema import CHOICES, DEFAULTS, cycle, merge
from app.text.normalize import letters_signature, normalize
from app.words.importer import iter_rows, prepare


def row(i, w, d=2, puzzle=True):
    return WordRow(i, normalize(w), w, len(normalize(w)), d, puzzle)


WORDS = ["مدرسه", "درس", "سرد", "رسم", "دسر", "مرد", "رده", "سرم", "مدر"]
CANDS = [row(i + 1, w) for i, w in enumerate(WORDS)]


class LevelTests(unittest.TestCase):
    def test_build_level_valid(self):
        seed = CANDS[0]
        lvl = build_level(seed, CANDS, main_count=4, diff_range=(1, 5), use_bonus=True,
                          recent_word_ids=set(), reserved=RESERVED, rng=random.Random(1))
        self.assertIsNotNone(lvl)
        self.assertEqual(len(lvl.main), 4)
        self.assertEqual(sorted(lvl.letters), sorted(seed.norm))
        for w in lvl.main + lvl.bonus:
            self.assertTrue(can_build(w.norm, lvl.letters))
        self.assertFalse({w.id for w in lvl.main} & {w.id for w in lvl.bonus})

    def test_recent_words_excluded(self):
        recent = {c.id for c in CANDS[1:6]}
        lvl = build_level(CANDS[0], CANDS, main_count=4, diff_range=(1, 5), use_bonus=False,
                          recent_word_ids=recent, reserved=RESERVED, rng=random.Random(2), min_main=2)
        self.assertTrue(all(w.id not in recent for w in lvl.main[1:]))
        self.assertEqual(lvl.bonus, [])

    def test_too_few_returns_none(self):
        self.assertIsNone(build_level(CANDS[0], CANDS[:2], main_count=4, diff_range=(1, 5), use_bonus=True,
                                      recent_word_ids=set(), reserved=RESERVED, rng=random.Random(3)))

    def test_difficulty_filter(self):
        cands = [row(1, "مدرسه", 5)] + [row(i + 2, w, 1) for i, w in enumerate(WORDS[1:])]
        lvl = build_level(cands[0], cands, main_count=4, diff_range=DIFF_RANGE["easy"], use_bonus=False,
                          recent_word_ids=set(), reserved=RESERVED, rng=random.Random(4))
        self.assertNotIn(cands[0].id, [w.id for w in lvl.main])  # بذر سخت جواب اصلی نیست

    def test_generation_over_real_seed_file_is_varied(self):
        p = Path(__file__).resolve().parents[1] / "data" / "seed_words.txt"
        tuples, _ = prepare(iter_rows(p.read_bytes(), p.name), source="seed", trust_puzzle=True)
        rows = [WordRow(i + 1, t[0], t[1], t[2], t[5], t[8], t[6]) for i, t in enumerate(tuples)]
        by_sig = {}
        for r in rows:
            by_sig.setdefault(letters_signature(r.norm), []).append(r)
        rng = random.Random(7)

        async def fetch_seeds(n, lo, hi, ex, lim):
            pool = [r for r in rows if r.puzzle_ok and r.length == n and lo <= r.difficulty <= hi and r.id not in ex]
            rng.shuffle(pool)
            return pool[:lim]

        async def fetch_cands(sigs):
            return [r for s in sigs for r in by_sig.get(s, [])]

        seeds_seen, mains_seen = set(), []
        recent_seeds, recent_words = set(), set()
        ordered = []
        for _ in range(25):
            lvl = asyncio.run(generate_level(
                fetch_seeds, fetch_cands, letters=5, difficulty="mixed", main_count=4, use_bonus=True,
                recent_seed_ids=recent_seeds, recent_word_ids=recent_words, reserved=RESERVED, rng=rng))
            self.assertIsNotNone(lvl)
            for w in lvl.main:
                self.assertTrue(can_build(w.norm, lvl.letters))
            seeds_seen.add(lvl.seed.id)
            ordered.append(lvl.seed.id)
            mains_seen.append({w.id for w in lvl.main})
            recent_seeds.add(lvl.seed.id)
            recent_words |= {w.id for w in lvl.main}
        # با بانک کوچک اولیه، ۱۰ مرحله‌ی اول هیچ کلمه‌ی پایه‌ی تکراری ندارند
        self.assertEqual(len(set(ordered[:10])), 10)


class ScoringTests(unittest.TestCase):
    def test_points(self):
        self.assertGreater(word_points(5, 3, True), word_points(3, 1, True))
        self.assertLess(word_points(5, 3, False), word_points(5, 3, True))
        self.assertEqual(points_after_hints(5, 2), 3)
        self.assertEqual(points_after_hints(2, 9), 1)


class SettingsTests(unittest.TestCase):
    def test_cycle_wraps(self):
        s = dict(DEFAULTS)
        for _ in range(len(CHOICES["duration"])):
            s = cycle(s, "duration")
        self.assertEqual(s["duration"], DEFAULTS["duration"])

    def test_merge_ignores_bad(self):
        self.assertEqual(merge({"duration": 7, "nope": 1})["duration"], DEFAULTS["duration"])
        self.assertEqual(merge({"duration": 300})["duration"], 300)


class RenderTests(unittest.TestCase):
    def make(self):
        words = {}
        for i, w in enumerate(["مادر", "ماد", "دام"]):
            words[w] = RWord(i, i, w, w, True, 4)
        now = datetime.now(timezone.utc)
        return RoundState(1, 10, 12, list("مادرب"), now + timedelta(seconds=180), 2, words), now

    def test_round_text(self):
        st, now = self.make()
        st.words["مادر"].found_by = 5
        st.words["مادر"].found_name = "علی"
        st.words["مادر"].points = 4
        st.words["دام"].revealed = 1
        st.last_event = "🏅 علی ..."
        t = render_round(st, now)
        self.assertIn("مرحله ۱۲", t)
        self.assertIn("م ا د ر ✅", t)
        self.assertIn("د □ □", t)
        self.assertIn("پیشرفت: ۱ از ۳", t)
        self.assertIn("۰۳:۰۰", t)

    def test_final_text_escapes(self):
        st, _ = self.make()
        st.words["مادر"].found_by = 5
        st.words["مادر"].found_name = "<b>x</b>"
        st.players = {5: ["<b>x</b>", 4, 1]}
        t = render_final(st, "time")
        self.assertNotIn("<b>x</b>", t)
        self.assertIn("❌", t)

    def test_mmss(self):
        self.assertEqual(mmss(65), "۰۱:۰۵")
        self.assertEqual(mmss(-3), "۰۰:۰۰")


class PeriodTests(unittest.TestCase):
    def test_week_starts_saturday(self):
        from zoneinfo import ZoneInfo
        t = datetime(2026, 10, 28, 12, 0, tzinfo=ZoneInfo("Asia/Tehran"))  # چهارشنبه
        day, week, month = period_starts(t)
        self.assertEqual((week.month, week.day), (10, 24))
        self.assertEqual(week.weekday(), 5)
        self.assertEqual(day.day, 28)
        self.assertEqual(month.day, 1)


class ImporterTests(unittest.TestCase):
    def test_txt_directives_and_freq(self):
        data = "#difficulty=2\n#category=literary\nمادر 120\nكتاب پدر\n# توضیح\nabc سلام\n".encode()
        tuples, rep = prepare(iter_rows(data, "a.txt"), source="t", trust_puzzle=True)
        d = {t[0]: t for t in tuples}
        self.assertEqual(d["مادر"][4], 120)
        self.assertEqual(d["مادر"][5], 2)
        self.assertEqual(d["مادر"][6], "literary")
        self.assertIn("کتاب", d)                      # ك → ک
        self.assertNotIn("abc", d)
        self.assertEqual(rep.rejected["نویسه غیرفارسی"], 1)

    def test_dedupe_and_merge_freq(self):
        data = "مادر 5\nمادر 9\nماد‌ر 1\n".encode()
        tuples, rep = prepare(iter_rows(data, "a.txt"), source="t")
        self.assertEqual(len(tuples), 1)
        self.assertEqual(tuples[0][4], 9)

    def test_csv_and_json(self):
        csv_data = "word,freq,puzzle_ok\nدریا,10,1\nآب,3,0\n".encode()
        t, _ = prepare(iter_rows(csv_data, "x.csv"), source="c")
        d = {x[0]: x for x in t}
        self.assertTrue(d["دریا"][8])
        self.assertFalse(d["آب"][8])
        j, _ = prepare(iter_rows('{"کوه": 7, "رود": 2}'.encode(), "x.json"), source="j")
        self.assertEqual({x[0] for x in j}, {"کوه", "رود"})
        j2, _ = prepare(iter_rows('["گل", {"word":"باغ","freq":4}]'.encode(), "x.json"), source="j")
        self.assertEqual({x[0] for x in j2}, {"گل", "باغ"})

    def test_puzzle_length_bounds(self):
        t, _ = prepare(iter_rows("آب\nدریا\nفرهنگستان\n".encode(), "a.txt"), source="t", trust_puzzle=True)
        d = {x[0]: x for x in t}
        self.assertFalse(d["آب"][8])
        self.assertTrue(d["دریا"][8])
        self.assertFalse(d["فرهنگستان"][8])


if __name__ == "__main__":
    unittest.main()
