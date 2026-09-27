import unittest

from services import ai


class FakeLock:
    def __init__(self, acquired):
        self.acquired = acquired
        self.released = False

    def acquire(self, timeout=None):
        return self.acquired

    def release(self):
        self.released = True


class AiReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.original_enabled = ai.enabled
        self.original_ollama = ai._ollama
        self.original_lock = ai._generation_lock
        ai.enabled = lambda: True

    def tearDown(self):
        ai.enabled = self.original_enabled
        ai._ollama = self.original_ollama
        ai._generation_lock = self.original_lock

    def test_generation_keeps_model_loaded_and_uses_configured_timeout(self):
        calls = []

        def fake_ollama(path, payload, timeout=None):
            calls.append((path, payload, timeout))
            return {"message": {"content": "Hello"}}

        ai._ollama = fake_ollama
        ai._generation_lock = FakeLock(True)

        self.assertEqual("Hello", ai.ask_once("Hi"))
        self.assertEqual("30m", calls[0][1]["keep_alive"])
        self.assertEqual(ai.config.AI_TIMEOUT, calls[0][2])
        self.assertTrue(ai._generation_lock.released)

    def test_busy_model_returns_immediately_instead_of_queueing(self):
        ai._generation_lock = FakeLock(False)

        answer = ai.ask_once("Hi")

        self.assertIn("busy", answer.lower())

    def test_timeout_has_friendly_message(self):
        ai._generation_lock = FakeLock(True)
        ai._ollama = lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError())

        answer = ai.ask_once("Hi")

        self.assertIn("timed out", answer.lower())

    def test_translation_uses_language_names_and_returns_only_model_text(self):
        calls = []

        def fake_ollama(path, payload, timeout=None):
            calls.append(payload)
            return {"message": {"content": "beautiful"}}

        ai._ollama = fake_ollama
        ai._generation_lock = FakeLock(True)

        answer = ai.translate("tagalog", "english", "maganda")

        self.assertEqual("beautiful", answer)
        messages = calls[0]["messages"]
        self.assertIn("Tagalog", messages[0]["content"])
        self.assertIn("English", messages[0]["content"])
        self.assertEqual("maganda", messages[1]["content"])
        self.assertEqual(0.1, calls[0]["options"]["temperature"])

    def test_image_prompt_refinement_is_stateless_and_visual(self):
        calls = []

        def fake_ollama(path, payload, timeout=None):
            calls.append(payload)
            return {"message": {"content": "cinematic red castle, moonlight"}}

        ai._ollama = fake_ollama
        ai._generation_lock = FakeLock(True)

        prompt, succeeded = ai.refine_image_prompt("red castle")

        self.assertTrue(succeeded)
        self.assertEqual("cinematic red castle, moonlight", prompt)
        messages = calls[0]["messages"]
        self.assertEqual(2, len(messages))
        self.assertIn("composition", messages[0]["content"].lower())
        self.assertIn("instructions", messages[0]["content"].lower())
        self.assertEqual("red castle", messages[1]["content"])

    def test_image_prompt_refinement_falls_back_to_original_prompt(self):
        ai._generation_lock = FakeLock(False)

        prompt, succeeded = ai.refine_image_prompt("red castle")

        self.assertFalse(succeeded)
        self.assertEqual("red castle", prompt)

    def test_failed_health_check_is_retried_after_cache_ttl(self):
        ai.enabled = self.original_enabled
        original_urlopen = ai.urllib.request.urlopen
        original_monotonic = ai.time.monotonic
        original_available = ai._available
        original_checked = ai._available_checked_at
        attempts = []
        clock = iter([100.0, 131.0])

        def fake_urlopen(*args, **kwargs):
            attempts.append(args[0])
            if len(attempts) == 1:
                raise OSError("starting")
            return object()

        ai.urllib.request.urlopen = fake_urlopen
        ai.time.monotonic = lambda: next(clock)
        ai._available = None
        ai._available_checked_at = 0.0
        try:
            self.assertFalse(ai.enabled())
            self.assertTrue(ai.enabled())
        finally:
            ai.urllib.request.urlopen = original_urlopen
            ai.time.monotonic = original_monotonic
            ai._available = original_available
            ai._available_checked_at = original_checked

        self.assertEqual(2, len(attempts))


if __name__ == "__main__":
    unittest.main()
