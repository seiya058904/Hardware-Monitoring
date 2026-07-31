from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import socket
import unittest
from urllib.error import HTTPError, URLError

from android.termux.node_checks import check_dashboard
from android.termux.node_config import NodeConfig


NOW = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)
FIXTURES = Path(__file__).with_name("fixtures")


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self.body = body
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return self.body if size < 0 else self.body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False


class DashboardChecksTests(unittest.TestCase):
    def setUp(self):
        self.config = NodeConfig(
            dashboard_base_url="http://dashboard.example:8765",
            check_interval_seconds=60,
            request_timeout_seconds=5,
        )

    def fixture(self, name):
        return (FIXTURES / name).read_bytes()

    def check(self, responses, now=NOW):
        calls = []

        def opener(request, timeout):
            calls.append((request.full_url, timeout))
            response = responses.pop(0)
            if isinstance(response, BaseException):
                raise response
            return response

        result = check_dashboard(self.config, now, _opener=opener, _monotonic=lambda: 1.0)
        return result, calls

    def assert_failure(self, response, category, now=NOW):
        result, _ = self.check(response, now)
        self.assertEqual(result.target, "dashboard")
        self.assertFalse(result.success)
        self.assertEqual(result.category, category)
        self.assertEqual(result.detail, category)
        self.assertEqual(result.checked_at, now)

    def test_unreachable_health_is_classified_without_request_details(self):
        for error in (URLError("private host failed"), ConnectionRefusedError("connection refused")):
            with self.subTest(error=error):
                self.assert_failure([error], "unreachable")

    def test_health_timeout_is_classified(self):
        self.assert_failure([socket.timeout()], "timeout")

    def test_non_success_health_response_stops_before_metrics(self):
        health = HTTPError("http://dashboard.example:8765/healthz", 503, "unavailable", {}, None)

        result, calls = self.check([health])

        self.assertFalse(result.success)
        self.assertEqual(result.category, "health_http_error")
        self.assertEqual(calls, [("http://dashboard.example:8765/healthz", 5)])

    def test_invalid_health_body_stops_before_metrics(self):
        for body in (b"not json", b'{"status":"unavailable"}'):
            with self.subTest(body=body):
                result, calls = self.check([FakeResponse(200, body)])

                self.assertFalse(result.success)
                self.assertEqual(result.category, "health_invalid")
                self.assertEqual(calls, [("http://dashboard.example:8765/healthz", 5)])

    def test_non_success_metrics_response_is_classified(self):
        self.assert_failure(
            [FakeResponse(200, self.fixture("health-ok.json")), FakeResponse(503, b"{}")],
            "metrics_http_error",
        )

    def test_invalid_metrics_json_is_classified(self):
        self.assert_failure(
            [FakeResponse(200, self.fixture("health-ok.json")), FakeResponse(200, b"not json")],
            "metrics_json_invalid",
        )

    def test_wrong_metrics_status_is_classified(self):
        payload = json.dumps({"status": "unavailable", "updated_at": NOW.isoformat(), "metrics": {}}).encode()

        self.assert_failure(
            [FakeResponse(200, self.fixture("health-ok.json")), FakeResponse(200, payload)],
            "metrics_status_invalid",
        )

    def test_missing_or_invalid_metrics_timestamp_is_stale(self):
        for timestamp in (None, "not-a-date"):
            with self.subTest(timestamp=timestamp):
                payload = json.dumps({"status": "ok", "updated_at": timestamp, "metrics": {}}).encode()

                self.assert_failure(
                    [FakeResponse(200, self.fixture("health-ok.json")), FakeResponse(200, payload)],
                    "metrics_stale",
                )

    def test_metrics_older_than_configured_staleness_limit_are_stale(self):
        stale_at = NOW - timedelta(seconds=126)
        payload = json.dumps({"status": "ok", "updated_at": stale_at.isoformat(), "metrics": {}}).encode()

        self.assert_failure(
            [FakeResponse(200, self.fixture("health-ok.json")), FakeResponse(200, payload)],
            "metrics_stale",
        )

    def test_configured_staleness_window_accepts_metrics_at_its_exact_limit(self):
        self.config = NodeConfig(
            dashboard_base_url="http://dashboard.example:8765",
            check_interval_seconds=70,
            request_timeout_seconds=5,
        )
        updated_at = NOW - timedelta(seconds=145)
        payload = json.dumps({"status": "ok", "updated_at": updated_at.isoformat(), "metrics": {}}).encode()

        result, _ = self.check(
            [FakeResponse(200, self.fixture("health-ok.json")), FakeResponse(200, payload)]
        )

        self.assertTrue(result.success)
        self.assertEqual(result.category, "ok")

    def test_non_object_metrics_are_rejected(self):
        payload = json.dumps({"status": "ok", "updated_at": NOW.isoformat(), "metrics": []}).encode()

        self.assert_failure(
            [FakeResponse(200, self.fixture("health-ok.json")), FakeResponse(200, payload)],
            "metrics_shape_invalid",
        )

    def test_fresh_metrics_are_healthy_and_requests_are_bounded(self):
        health = FakeResponse(200, self.fixture("health-ok.json"))
        metrics = FakeResponse(200, self.fixture("metrics-fresh.json"))

        result, calls = self.check([health, metrics])

        self.assertTrue(result.success)
        self.assertEqual(result.category, "ok")
        self.assertEqual(result.detail, "")
        self.assertEqual(
            calls,
            [
                ("http://dashboard.example:8765/healthz", 5),
                ("http://dashboard.example:8765/api/metrics", 5),
            ],
        )
        self.assertTrue(all(size > 0 for size in health.read_sizes + metrics.read_sizes))


if __name__ == "__main__":
    unittest.main()
