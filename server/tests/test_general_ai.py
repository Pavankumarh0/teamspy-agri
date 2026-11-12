"""General-knowledge fallback: a Gemini model answers farming questions the
documents don't cover (mocked, no network)."""
import os
import unittest
from unittest import mock

import test_krishi_app as base  # sets up the environment and the app  # noqa: F401
from test_krishi_app import gemma, krishi


def general(reply):
    return mock.patch.object(krishi.llm, "generate_general", mock.AsyncMock(return_value=reply))


class GeneralAiTests(base.KrishiApiTests.__base__):
    @classmethod
    def setUpClass(cls):
        base.KrishiApiTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        base.KrishiApiTests.tearDownClass.__func__(cls)

    def setUp(self):
        base.sensors.reset()
        krishi.LAST_Q.clear()
        self.env = mock.patch.dict(os.environ, {"GENERAL_AI": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    ask = base.KrishiApiTests.ask

    def test_question_not_in_documents_is_answered_by_the_general_model(self):
        reply = ("Mango hoppers suck sap from flowers, so the flowers drop. Prune crowded branches so light gets in, "
                 "and ask the agriculture officer which spray to use at flowering.")
        with gemma("NOT_IN_KB"), general(reply) as g:
            r = self.ask("How do I control hoppers on my mango flowers?")
        g.assert_awaited_once()
        self.assertTrue(r["in_scope"])
        self.assertEqual(r["via"], "general")
        self.assertEqual(r["sources"], ["general_knowledge"])
        self.assertIn("Mango hoppers", r["answer"])

    def test_non_farming_question_is_politely_refused(self):
        with gemma("NOT_IN_KB"), general("NOT_AGRI"):
            r = self.ask("Who won the cricket match yesterday?")
        self.assertFalse(r["in_scope"])
        self.assertEqual(r["answer"], krishi.NOT_FARMING)

    def test_general_answer_with_a_dose_is_rejected(self):
        with gemma("NOT_IN_KB"), general("Spray 2 ml per litre of water on the mango flowers."):
            r = self.ask("How do I control hoppers on my mango flowers?")
        self.assertEqual(r["answer"], krishi.DONT_KNOW)

    def test_general_fertilizer_answer_gets_the_safety_warning(self):
        with gemma("NOT_IN_KB"), general("Coconut palms need potash for nut filling, so give fertilizer as per the "
                                         "soil test in a ring around the palm."):
            r = self.ask("How should I give fertilizer to coconut palms?")
        self.assertTrue(r["answer"].endswith(krishi.fertilizer.SAFETY_WARNING))

    def test_general_model_failure_falls_back_to_the_usual_reply(self):
        with gemma("NOT_IN_KB"), mock.patch.object(krishi.llm, "generate_general",
                                                   mock.AsyncMock(side_effect=RuntimeError("down"))):
            r = self.ask("How do I control hoppers on my mango flowers?")
        self.assertEqual(r["answer"], krishi.DONT_KNOW)

    def test_off_without_a_key(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}), gemma("NOT_IN_KB"), general("x") as g:
            r = self.ask("How do I control hoppers on my mango flowers?")
        g.assert_not_awaited()
        self.assertEqual(r["answer"], krishi.DONT_KNOW)


if __name__ == "__main__":
    unittest.main()
