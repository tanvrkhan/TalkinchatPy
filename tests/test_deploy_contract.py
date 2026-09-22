from pathlib import Path
import unittest


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "deploy.yml"


class DeploymentWorkflowContractTests(unittest.TestCase):
    def test_workflow_is_isolated_from_howdies(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("branches: [master]", workflow)
        self.assertIn("group: talkinchat-deploy-vm", workflow)
        self.assertIn("/root/TalkinchatPy/", workflow)
        self.assertIn("talkinchat-bot.env", workflow)
        self.assertIn("/var/lib/talkinchat-bot", workflow)
        self.assertIn("python3 -m unittest discover -v", workflow)
        self.assertIn("bash tests/test_deploy_install.sh", workflow)
        self.assertIn("bash deploy/install.sh", workflow)
        self.assertNotIn("systemctl restart howdies-bot", workflow)
        self.assertNotIn("/root/HowdiesPy", workflow)


if __name__ == "__main__":
    unittest.main()
