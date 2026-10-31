"""Run the actual guild entry point, including pre-board and failed API states."""
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'Node required for UI regression tests')
class GuildStartupClientTests(unittest.TestCase):
    def test_startup_and_error_screens_without_hunter_data(self):
        result=subprocess.run([shutil.which('node'),'tests/guild_startup_client.cjs'],
                              cwd=Path(__file__).resolve().parents[1],capture_output=True,
                              text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
