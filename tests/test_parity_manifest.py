import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "parity" / "howdies-f2567a1.json"


class ParityManifestTests(unittest.TestCase):
    def load_manifest(self):
        with MANIFEST.open(encoding="utf-8") as handle:
            return json.load(handle)

    def test_manifest_identifies_the_approved_baseline_and_primary_prefix(self):
        manifest = self.load_manifest()
        self.assertEqual("f2567a1", manifest["source_commit"])
        self.assertEqual(",", manifest["primary_prefix"])
        self.assertIn("!", manifest["accepted_prefixes"])

    def test_every_command_has_unique_names_and_explicit_translation(self):
        manifest = self.load_manifest()
        claimed = set()
        self.assertGreaterEqual(len(manifest["commands"]), 100)
        for item in manifest["commands"]:
            self.assertTrue(item["name"])
            self.assertIn(item["status"], {"planned", "enabled", "disabled"})
            self.assertTrue(item["fallback"])
            self.assertIn("capabilities", item)
            for name in [item["name"], *item["aliases"]]:
                normalized = name.casefold()
                self.assertNotIn(normalized, claimed, name)
                claimed.add(normalized)

    def test_checker_accepts_committed_manifest(self):
        result = subprocess.run(
            [sys.executable, "scripts/check_parity.py"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
