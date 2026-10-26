"""Browser controller regression tests run against the actual RP client script."""
from pathlib import Path
import shutil
import subprocess
import unittest


class RPClientTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_editor_field_types_and_preview_recovery(self):
        result = subprocess.run(
            [shutil.which('node'), str(Path(__file__).with_name('rp_client.cjs'))],
            capture_output=True, text=True, encoding='utf-8', timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
