import json
import math
import time
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from app import DEFAULT_CONFIG, LanDashboardService


class LanDashboardServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = LanDashboardService(
            lambda: {"cpu_usage": 42.0, "bad": math.nan, "nested": [math.inf]},
            lambda: 123.0,
        )
        self.assertTrue(self.service.start(port=0))
        self.base_url = f"http://127.0.0.1:{self.service.port}"

    def tearDown(self) -> None:
        self.service.stop()

    def test_healthz_and_metrics_are_read_only_valid_json(self) -> None:
        with urlopen(f"{self.base_url}/healthz", timeout=2) as response:
            self.assertEqual(200, response.status)
            self.assertEqual({"status": "ok"}, json.loads(response.read()))
        with urlopen(f"{self.base_url}/api/metrics", timeout=2) as response:
            payload = json.loads(response.read())
        self.assertEqual(42.0, payload["metrics"]["cpu_usage"])
        self.assertIsNone(payload["metrics"]["bad"])
        self.assertIsNone(payload["metrics"]["nested"][0])
        with self.assertRaises(HTTPError) as context:
            urlopen(f"{self.base_url}/api/metrics", data=b"x", timeout=2)
        self.assertEqual(405, context.exception.code)

    def test_repeated_start_stop_and_port_conflict_do_not_leave_server_running(self) -> None:
        port = self.service.port
        conflicting_service = LanDashboardService(lambda: {}, lambda: "")
        self.assertFalse(conflicting_service.start(port=port))
        self.assertFalse(conflicting_service.is_running)
        self.service.stop()
        self.assertFalse(self.service.is_running)
        self.assertTrue(self.service.start(port=port))
        self.service.stop()
        deadline = time.monotonic() + 1
        while self.service.is_alive and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(self.service.is_alive)

    def test_default_config_keeps_dashboard_disabled(self) -> None:
        self.assertFalse(DEFAULT_CONFIG["lan_dashboard_enabled"])


if __name__ == "__main__":
    unittest.main()
