import unittest

from services import ai


class AiProfileTests(unittest.TestCase):
    def setUp(self):
        self.original_generate = ai._generate
        ai._history.clear()

    def tearDown(self):
        ai._generate = self.original_generate
        ai._history.clear()

    def test_ask_uses_preferred_language_and_human_style(self):
        calls = []

        def generate(messages, **kwargs):
            calls.append(messages)
            return "Mabuti naman", True

        ai._generate = generate
        answer = ai.ask("9", "Kumusta?", profile={"language": "Tagalog", "tone": "warm"})
        self.assertEqual(answer, "Mabuti naman")
        system = calls[0][0]["content"]
        self.assertIn("Tagalog", system)
        self.assertIn("contractions", system)
        self.assertIn("Don't announce", system)

    def test_profile_normalization_discards_sensitive_and_unknown_fields(self):
        profile = ai.normalize_profile({
            "language": "Urdu", "religion": "private", "health": "private",
            "politics": "private", "interests": ["music", "books"],
            "tone": "casual", "unknown": "drop",
        })
        self.assertEqual(profile, {
            "language": "Urdu", "tone": "casual", "interests": ["music", "books"],
        })

    def test_infer_profile_parses_json_and_preserves_previous_on_failure(self):
        ai._generate = lambda *args, **kwargs: (
            '{"language":"Spanish","code_switching":true,"religion":"x"}', True)
        self.assertEqual(ai.infer_profile(["hola", "buenas"]),
                         {"language": "Spanish", "code_switching": True})
        ai._generate = lambda *args, **kwargs: ("not json", True)
        self.assertEqual(ai.infer_profile(["hello"], {"language": "English"}),
                         {"language": "English"})


if __name__ == "__main__":
    unittest.main()
