import json
import shutil
import subprocess
import unittest
from pathlib import Path

from arena_links import arena_link


class ArenaLinkTests(unittest.TestCase):
    def test_normal_window_link(self):
        self.assertEqual(
            arena_link("@GnidoBot", "menu_-100123"),
            "https://t.me/GnidoBot?startapp=menu_-100123",
        )

    def test_start_parameter_is_escaped(self):
        self.assertEqual(
            arena_link("GnidoBot", "b_test &other=1"),
            "https://t.me/GnidoBot?startapp=b_test%20%26other%3D1",
        )


@unittest.skipUnless(shutil.which("node"), "Node is needed for client tests")
class ArenaViewportTests(unittest.TestCase):
    def viewport_calls(self, **options):
        client = Path(__file__).resolve().parents[1] / "webapp" / "battle-client"
        source = client.read_text(encoding="utf-8")
        function = source.split("function configureViewport(){", 1)[1].split(
            "\nasync function boot(){", 1
        )[0]
        script = """
const vm = require('node:vm');
const options = JSON.parse(process.argv[1]);
const calls = [];
const tg = options.noTelegram ? undefined : {
  platform: options.platform,
  isFullscreen: options.fullscreen || false,
  isVersionAtLeast: () => options.supported !== false,
  ready: () => calls.push('ready'),
  expand: () => calls.push('expand'),
  requestFullscreen: () => {
    calls.push('requestFullscreen');
    if (options.fail) throw new Error('UNSUPPORTED');
  },
  exitFullscreen: () => calls.push('exitFullscreen'),
  setHeaderColor: () => calls.push('header'),
  setBackgroundColor: () => calls.push('background'),
};
vm.runInNewContext(process.argv[2] + '\\nconfigureViewport();', {tg});
process.stdout.write(JSON.stringify(calls));
"""
        result = subprocess.run(
            [
                shutil.which("node"),
                "-e",
                script,
                json.dumps(options),
                "function configureViewport(){" + function,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    def test_mobile_requests_fullscreen(self):
        for platform in ("android", "ios"):
            with self.subTest(platform=platform):
                self.assertIn(
                    "requestFullscreen", self.viewport_calls(platform=platform)
                )

    def test_desktop_and_web_do_not_request_fullscreen(self):
        for platform in ("tdesktop", "macos", "web", "weba", "webk", "unknown"):
            with self.subTest(platform=platform):
                calls = self.viewport_calls(platform=platform)
                self.assertNotIn("requestFullscreen", calls)
                self.assertNotIn("exitFullscreen", calls)
                self.assertIn("expand", calls)

    def test_old_fullscreen_desktop_link_exits_fullscreen(self):
        calls = self.viewport_calls(platform="tdesktop", fullscreen=True)
        self.assertIn("exitFullscreen", calls)
        self.assertNotIn("requestFullscreen", calls)

    def test_mobile_already_fullscreen_is_not_requested_again(self):
        calls = self.viewport_calls(platform="ios", fullscreen=True)
        self.assertNotIn("requestFullscreen", calls)
        self.assertNotIn("exitFullscreen", calls)

    def test_unsupported_client_keeps_theme(self):
        calls = self.viewport_calls(platform="android", supported=False)
        self.assertNotIn("requestFullscreen", calls)
        self.assertIn("background", calls)

    def test_fullscreen_failure_keeps_theme(self):
        calls = self.viewport_calls(platform="android", fail=True)
        self.assertIn("background", calls)

    def test_browser_without_telegram(self):
        self.assertEqual(self.viewport_calls(noTelegram=True), [])
