import unittest

from config import Config
from services.activity_store import ActivityStore


class CollectorPrivacyTests(unittest.TestCase):
    def test_collector_mode_is_explicit_and_separately_configured(self):
        config = Config.from_env({
            "TALKINCHAT_USERNAME": "collector", "TALKINCHAT_PASSWORD": "pw",
            "TALKINCHAT_ROOM": "Room", "TALKINCHAT_MODE": "collector",
        })
        self.assertTrue(config.collector_mode)

    def test_activity_api_has_no_direct_message_recording_operation(self):
        self.assertNotIn("record_dm", dir(ActivityStore))


if __name__ == "__main__":
    unittest.main()
