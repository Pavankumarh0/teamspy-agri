import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import language  # noqa: E402


class LanguageTests(unittest.TestCase):
    def test_reply_language_follows_the_enabled_languages(self):
        with mock.patch.dict(os.environ, {"KIOSK_LANGUAGES": "en,kn,hi"}):
            self.assertEqual(language.reply_language("kn-IN"), "kn")
            self.assertEqual(language.reply_language("hi-IN"), "hi")
            self.assertEqual(language.reply_language("ta-IN"), "en")     # not enabled: English
            self.assertEqual(language.reply_language(None), "en")
        with mock.patch.dict(os.environ, {"KIOSK_LANGUAGES": "en,kn"}):
            self.assertEqual(language.reply_language("hi-IN"), "en")

    def test_spoken_source_names_stay_english(self):
        self.assertEqual(language.spoken_suffix("en", ["05_hostel.md"]), " This is from the hostel information.")
        self.assertIn("campus map", language.spoken_suffix("kn", ["campus_map.md"]))
        self.assertEqual(language.spoken_suffix("hi", []), "")

    def test_the_reply_style_follows_the_question(self):
        # Kanglish / Hinglish: English words in the question -> code-mixed reply
        self.assertEqual(language.question_style("Boys hostel-ge hoguva map kodu.", "Give me the map to the boys' hostel."), "mixed")
        self.assertEqual(language.question_style("Bhai, canteen kahan hai?", "Brother, where is the canteen?"), "mixed")
        # plain Kannada / Hindi -> plain reply
        self.assertEqual(language.question_style("Granthalaya ellide?", "Where is the library?"), "native")
        self.assertEqual(language.question_style("Pustakalay kahan hai?", "Where is the library?"), "native")

    def test_romanize_spells_kannada_and_hindi_letter_for_letter(self):
        self.assertEqual(language.romanize("ಗ್ರಂಥಾಲಯ ಎಲ್ಲಿದೆ?"), "Granthalaya ellide?")
        self.assertEqual(language.romanize("ಅದರ ಬಗ್ಗೆ ನನಗೆ ಗೊತ್ತಿಲ್ಲ."), "Adara bagge nanage gottilla.")
        self.assertEqual(language.romanize("ಸಂಪರ್ಕ"), "Samparka")                  # anusvara before p -> m
        self.assertEqual(language.romanize("कैंटीन कहाँ है?"), "Kaintin kahan hai?")  # Hindi drops the final a
        self.assertEqual(language.romanize("मुझे नहीं पता।"), "Mujhe nahin pata.")     # danda -> full stop
        self.assertEqual(language.romanize("OB-1 ರಲ್ಲಿ 122 m"), "OB-1 ralli 122 m")   # Latin text and digits kept

    def test_english_needs_no_translation(self):
        import asyncio
        out = asyncio.run(language.understand("Where is the library?", "en-IN"))
        self.assertEqual((out["language"], out["english"]), ("en", "Where is the library?"))


if __name__ == "__main__":
    unittest.main()
