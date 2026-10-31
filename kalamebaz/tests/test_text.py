import unittest

from app.keywords import RESERVED, match_command, parse_suggestion
from app.text.normalize import (
    compact_key, fa, is_persian_word, letters_signature, normalize, normalize_display, sub_signatures,
)


class NormalizeTests(unittest.TestCase):
    def test_yeh_kaf(self):
        self.assertEqual(normalize("كتاب ي"), "کتاب ی")
        self.assertEqual(normalize("علي"), "علی")

    def test_zwnj_and_spaces(self):
        self.assertEqual(normalize("  برترین\u200cها  "), "برترینها")
        self.assertEqual(normalize("بازی    شروع"), "بازی شروع")
        self.assertEqual(normalize_display("می\u200c\u200cرود"), "می\u200cرود")

    def test_diacritics_tatweel(self):
        self.assertEqual(normalize("مَادَر"), "مادر")
        self.assertEqual(normalize("مـــادر"), "مادر")

    def test_presentation_forms(self):
        self.assertEqual(normalize("ﻣﺎﺩﺭ"), "مادر")

    def test_alef_madda_kept(self):
        self.assertEqual(normalize("آب"), "آب")
        self.assertNotEqual(normalize("آب"), normalize("اب"))

    def test_no_false_acceptance(self):
        self.assertFalse(is_persian_word(normalize("abc")))
        self.assertFalse(is_persian_word(normalize("کتاب1")))
        self.assertTrue(is_persian_word(normalize("كتاب")))

    def test_signature_and_subsets(self):
        self.assertEqual(letters_signature("درس"), letters_signature("سرد"))
        self.assertEqual(len(sub_signatures(list("مدرسه"))), 16)
        # حروف تکراری → امضای تکراری حذف می‌شود
        self.assertLess(len(sub_signatures(list("ماما"))), 5 + 1)
        self.assertIn(letters_signature("درس"), sub_signatures(list("مدرسه")))

    def test_fa_digits(self):
        self.assertEqual(fa(12), "۱۲")


class KeywordTests(unittest.TestCase):
    def test_all_commands(self):
        expect = {
            "شروع بازی": "start", "بازی شروع": "start", "توقف بازی": "stop", "بازی توقف": "stop",
            "مرحله بعد": "next", "بازی بعدی": "next", "راهنمای بازی": "help", "بازی راهنما": "help",
            "امتیاز من": "me", "بازی امتیاز": "me", "برترین\u200cها": "top", "بازی برترین\u200cها": "top",
            "رتبه جهانی": "global", "بازی رتبه جهانی": "global", "آمار بازی": "stats", "بازی آمار": "stats",
            "تنظیمات بازی": "settings", "بازی تنظیمات": "settings", "وضعیت بازی": "status", "بازی وضعیت": "status",
        }
        for phrase, cmd in expect.items():
            self.assertEqual(match_command(phrase), cmd, phrase)

    def test_variants(self):
        self.assertEqual(match_command("  بازي   شروع "), "start")      # ي عربی + فاصله اضافی
        self.assertEqual(match_command("برترين ها"), "top")             # فاصله به‌جای نیم‌فاصله
        self.assertEqual(match_command("برترینها!"), "top")
        self.assertEqual(match_command("شروع\u200cبازی"), "start")

    def test_non_commands(self):
        for t in ("مادر", "شروع", "بازی", "سلام بچه ها", "x" * 100):
            self.assertIsNone(match_command(t))

    def test_reserved_never_guessable(self):
        self.assertIn(compact_key("بازی شروع"), RESERVED)
        self.assertNotIn(normalize("مادر"), RESERVED)

    def test_suggestion(self):
        self.assertEqual(parse_suggestion("پیشنهاد کلمه  آبگینه"), "آبگینه")
        self.assertIsNone(parse_suggestion("پیشنهاد کلمه دو کلمه"))
        self.assertIsNone(parse_suggestion("مادر"))


if __name__ == "__main__":
    unittest.main()
