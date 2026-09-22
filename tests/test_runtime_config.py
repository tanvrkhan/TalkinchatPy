import unittest

from runtime_config import RuntimeConfig, RuntimeConfigError


class RuntimeConfigTests(unittest.TestCase):
    def test_loads_trimmed_values_and_defaults_owner_to_username(self):
        config = RuntimeConfig.from_env(
            {
                "TALKINCHAT_USERNAME": "  bot-user  ",
                "TALKINCHAT_PASSWORD": "  secret value  ",
                "TALKINCHAT_ROOM": "  American  ",
            }
        )

        self.assertEqual("bot-user", config.username)
        self.assertEqual("secret value", config.password)
        self.assertEqual("American", config.room)
        self.assertEqual("bot-user", config.owner)

    def test_uses_explicit_owner(self):
        config = RuntimeConfig.from_env(
            {
                "TALKINCHAT_USERNAME": "bot-user",
                "TALKINCHAT_PASSWORD": "secret",
                "TALKINCHAT_ROOM": "American",
                "TALKINCHAT_OWNER": " room-owner ",
            }
        )

        self.assertEqual("room-owner", config.owner)

    def test_missing_required_values_are_reported_together(self):
        config = RuntimeConfig.from_env({"TALKINCHAT_USERNAME": "bot-user"})

        with self.assertRaisesRegex(
            RuntimeConfigError,
            "TALKINCHAT_PASSWORD, TALKINCHAT_ROOM",
        ):
            config.require_valid()

    def test_validation_error_never_contains_password(self):
        password = "do-not-leak-this"
        config = RuntimeConfig.from_env(
            {
                "TALKINCHAT_PASSWORD": password,
                "TALKINCHAT_ROOM": "American",
            }
        )

        with self.assertRaises(RuntimeConfigError) as raised:
            config.require_valid()

        self.assertNotIn(password, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
