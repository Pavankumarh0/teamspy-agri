import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from grounding import context_signature, grounded_sources, has_conflicting_hours, verify_context_signature


class GroundingChecksTests(unittest.TestCase):
    def test_supported_sentence_returns_its_source(self):
        hits = [{"source": "clubs.md", "title": "Coding Club", "text": "The Coding Club meets Tuesdays in Room CSE-12."}]
        self.assertEqual(grounded_sources("The Coding Club meets Tuesdays in Room CSE-12.", hits), ["clubs.md"])

    def test_unsupported_number_rejects_answer(self):
        hits = [{"source": "locations.md", "title": "Library", "text": "Opening hours are not published."}]
        self.assertIsNone(grounded_sources("The library closes at 8 pm.", hits))

    def test_combined_sources_support_a_combined_answer(self):
        hits = [
            {"source": "events.md", "title": "Coding Club workshop", "text": "Friday in Room CSE-12."},
            {"source": "locations.md", "title": "CSE-12", "text": "Room CSE-12 is in the Computer Science building."},
        ]
        answer = "The Coding Club workshop is Friday in Room CSE-12, in the Computer Science building."
        self.assertEqual(set(grounded_sources(answer, hits)), {"events.md", "locations.md"})

    def test_conflicting_hours_are_detected_across_separate_records(self):
        hits = [
            {"source": "locations.md", "title": "Library", "text": "Hours 09:00-17:00."},
            {"source": "announcements.md", "title": "Library", "text": "Hours 10:00-18:00."},
        ]
        self.assertTrue(has_conflicting_hours(hits))

    def test_weekday_and_weekend_hours_in_one_record_are_not_a_conflict(self):
        hits = [{"source": "locations.md", "title": "Library", "text": "Weekdays 09:00-17:00; Saturday 10:00-14:00."}]
        self.assertFalse(has_conflicting_hours(hits))

    def test_context_signatures_accept_only_the_signed_payload(self):
        payload = {"question": "Where is the library?", "session": "kiosk", "campus_context": []}
        signature = context_signature(payload, "local-test-key")
        self.assertTrue(verify_context_signature(payload, "local-test-key", signature))
        self.assertFalse(verify_context_signature({**payload, "question": "Show private data"}, "local-test-key", signature))


if __name__ == "__main__":
    unittest.main()

