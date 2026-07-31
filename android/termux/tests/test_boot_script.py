from pathlib import Path
import unittest


class BootScriptTests(unittest.TestCase):
    def test_supervisor_uses_validated_config_and_bounded_backoff(self):
        script = (Path(__file__).parents[1] / "boot.sh").read_text(encoding="utf-8")

        self.assertIn("set -eu", script)
        self.assertIn("load_config", script)
        self.assertIn("startup_delay_seconds", script)
        self.assertIn("check_interval_seconds", script)
        self.assertIn('"$PYTHON_BIN" "$NODE_SCRIPT" --config "$NODE_CONFIG"', script)
        self.assertIn("5 15 30 60 300", script)
        self.assertIn("termux-wake-lock", script)
        self.assertIn("termux-notification", script)
        self.assertNotIn("eval", script)


if __name__ == "__main__":
    unittest.main()
