import json
import unittest
from pathlib import Path

import commands  # noqa: F401
from registry import all_specs


class CommandParityTests(unittest.TestCase):
    def test_every_baseline_command_and_alias_is_registered(self):
        manifest = json.loads((Path(__file__).parents[1] / "parity" / "howdies-f2567a1.json").read_text())
        expected = {name.casefold() for item in manifest["commands"]
                    for name in [item["name"], *item["aliases"]]}
        actual = {name for spec in all_specs() for name in [spec.name, *spec.aliases]}
        self.assertEqual(set(), expected - actual)

    def test_every_baseline_command_has_a_native_non_placeholder_handler(self):
        manifest = json.loads((Path(__file__).parents[1] / "parity" / "howdies-f2567a1.json").read_text())
        from registry import get
        placeholders = []
        for item in manifest["commands"]:
            spec = get(item["name"])
            if spec.handler.__module__ == "command_modules.compat":
                placeholders.append(item["name"])
            self.assertEqual("enabled", item["status"], item["name"])
        self.assertEqual([], placeholders)


if __name__ == "__main__":
    unittest.main()
