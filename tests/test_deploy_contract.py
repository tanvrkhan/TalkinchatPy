from pathlib import Path
import unittest


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "deploy.yml"


class DeploymentWorkflowContractTests(unittest.TestCase):
    def test_workflow_is_isolated_from_howdies(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("branches: [master]", workflow)
        self.assertIn("group: talkinchat-deploy-vm", workflow)
        self.assertIn("/opt/talkinchat/incoming/", workflow)
        self.assertIn("GITHUB_RUN_ID", workflow)
        self.assertIn("talkinchat-bot.env", workflow)
        self.assertIn("/var/lib/talkinchat-bot", workflow)
        self.assertIn("python3 -m unittest discover -v", workflow)
        self.assertIn("bash tests/test_deploy_install.sh", workflow)
        self.assertIn("bash deploy/release.sh", workflow)
        self.assertIn('python-version: "3.12"', workflow)
        self.assertIn("python3 bot.py --check-readiness", workflow)
        service = (WORKFLOW.parents[2] / "deploy" / "talkinchat-bot.service").read_text()
        self.assertIn("/opt/talkinchat/current/bot.py", service)
        self.assertNotIn("/root/TalkinchatPy/main.py", service)
        self.assertIn("User=talkinchat", service)
        self.assertIn("Group=talkinchat", service)
        self.assertIn("UMask=0077", service)
        self.assertIn("ProtectSystem=strict", service)
        release = (WORKFLOW.parents[2] / "deploy" / "release.sh").read_text()
        self.assertIn("previous", release)
        self.assertIn("current", release)
        self.assertIn("backup", release)
        self.assertIn("rollback", release)
        self.assertIn("--check-readiness", release)
        self.assertIn('TALKINCHAT_APP_DIR="$incoming"', release)
        self.assertNotIn("systemctl restart howdies-bot", workflow)
        self.assertNotIn("/root/HowdiesPy", workflow)


if __name__ == "__main__":
    unittest.main()
