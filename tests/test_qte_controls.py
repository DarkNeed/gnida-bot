import json
from pathlib import Path
import shutil
import subprocess
import unittest

from arena_qte_rules import replay


@unittest.skipUnless(shutil.which("node"), "Node required")
class TouchInputTests(unittest.TestCase):
    def test_relative_drag_joystick_and_existing_server_replay(self):
        result = subprocess.run(
            [shutil.which("node"), str(Path(__file__).with_name("qte_controls.cjs"))],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        for case in json.loads(result.stdout):
            self.assertEqual(replay(case["challenge"], case["proof"], 10), case["mask"])
