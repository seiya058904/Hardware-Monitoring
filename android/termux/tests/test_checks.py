from datetime import datetime, timedelta, timezone
import errno
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import json
import socket
import ssl
import threading
import unittest
from urllib.error import HTTPError, URLError

from android.termux.node_checks import CompletedCommand, check_dashboard, check_gateway, check_internet
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

    def test_dashboard_does_not_follow_health_or_metrics_redirects(self):
        outside_hits = []

        class OutsideHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                outside_hits.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(
                    self.server.responses.get(self.path, b"{}")
                )

            def log_message(self, format, *args):
                pass

        class DashboardHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == self.server.redirect_path:
                    self.send_response(302)
                    self.send_header(
                        "Location",
                        f"http://127.0.0.1:{outside.server_port}{self.path}",
                    )
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(self.server.responses[self.path])

            def log_message(self, format, *args):
                pass

        responses = {
            "/healthz": self.fixture("health-ok.json"),
            "/api/metrics": json.dumps(
                {"status": "ok", "updated_at": NOW.isoformat(), "metrics": {}}
            ).encode(),
        }
        outside = HTTPServer(("127.0.0.1", 0), OutsideHandler)
        outside.responses = responses
        source = HTTPServer(("127.0.0.1", 0), DashboardHandler)
        source.responses = responses
        threads = [
            threading.Thread(target=server.serve_forever, daemon=True)
            for server in (outside, source)
        ]
        for thread in threads:
            thread.start()
        try:
            self.config = NodeConfig(
                dashboard_base_url=f"http://127.0.0.1:{source.server_port}",
                check_interval_seconds=60,
                request_timeout_seconds=5,
            )
            for redirect_path, category in (
                ("/healthz", "health_http_error"),
                ("/api/metrics", "metrics_http_error"),
            ):
                with self.subTest(path=redirect_path):
                    source.redirect_path = redirect_path
                    outside_hits.clear()
                    result = check_dashboard(self.config, NOW)
                    self.assertFalse(result.success)
                    self.assertEqual(result.category, category)
                    self.assertEqual(outside_hits, [])
        finally:
            source.shutdown()
            outside.shutdown()
            for thread in threads:
                thread.join()
            source.server_close()
            outside.server_close()


class GatewayChecksTests(unittest.TestCase):
    def setUp(self):
        self.config = NodeConfig(request_timeout_seconds=5)

    def check(self, commands, socket_factory=None):
        calls = []

        def runner(command):
            calls.append(command)
            response = commands.pop(0)
            if isinstance(response, BaseException):
                raise response
            return response

        result = check_gateway(
            self.config,
            runner,
            _socket_factory=socket_factory or (lambda *_: (_ for _ in ()).throw(AssertionError("TCP not expected"))),
            _now=lambda: NOW,
            _monotonic=lambda: 1.0,
        )
        return result, calls

    def test_route_parsing_uses_the_default_gateway_neighbor(self):
        result, calls = self.check(
            [
                CompletedCommand(0, "10.0.0.0/8 dev wlan0\ndefault via 192.168.50.1 dev wlan0\n"),
                CompletedCommand(0, "192.168.50.1 dev wlan0 lladdr 00:11:22:33:44:55 REACHABLE\n"),
            ]
        )

        self.assertTrue(result.success)
        self.assertEqual(result.category, "gateway_neighbor")
        self.assertEqual(calls, [["ip", "route"], ["ip", "neigh", "show", "192.168.50.1"]])

    def test_absent_default_gateway_is_unknown(self):
        result, calls = self.check([CompletedCommand(0, "192.168.50.0/24 dev wlan0\n")])

        self.assertIsNone(result.success)
        self.assertEqual(result.category, "gateway_unknown")
        self.assertEqual(calls, [["ip", "route"]])

    def test_accepted_neighbor_states_confirm_the_gateway(self):
        for state in ("REACHABLE", "STALE", "DELAY", "PROBE", "PERMANENT"):
            with self.subTest(state=state):
                result, _ = self.check(
                    [
                        CompletedCommand(0, "default via 192.168.50.1 dev wlan0\n"),
                        CompletedCommand(0, f"192.168.50.1 dev wlan0 {state}\n"),
                    ]
                )
                self.assertTrue(result.success)
                self.assertEqual(result.category, "gateway_neighbor")

    def test_absent_neighbor_makes_one_dns_tcp_attempt(self):
        attempts = []

        class ConnectedSocket:
            def __enter__(self):
                return self

            def __exit__(self, *unused):
                return False

        def socket_factory(address, timeout):
            attempts.append((address, timeout))
            return ConnectedSocket()

        result, _ = self.check(
            [CompletedCommand(0, "default via 192.168.50.1 dev wlan0\n"), CompletedCommand(0, "")],
            socket_factory,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.category, "gateway_tcp")
        self.assertEqual(attempts, [(("192.168.50.1", 53), 5)])

    def test_unaccepted_neighbor_result_still_makes_one_dns_tcp_attempt(self):
        class ConnectedSocket:
            def __enter__(self):
                return self

            def __exit__(self, *unused):
                return False

        result, _ = self.check(
            [
                CompletedCommand(0, "default via 192.168.50.1 dev wlan0\n"),
                CompletedCommand(2, stderr="neighbor entry unavailable"),
            ],
            lambda *_: ConnectedSocket(),
        )

        self.assertTrue(result.success)
        self.assertEqual(result.category, "gateway_tcp")

    def test_tcp_connection_refused_confirms_the_gateway_replied(self):
        def socket_factory(*unused):
            raise ConnectionRefusedError()

        result, _ = self.check(
            [CompletedCommand(0, "default via 192.168.50.1 dev wlan0\n"), CompletedCommand(0, "")],
            socket_factory,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.category, "gateway_tcp")

    def test_tcp_host_or_network_unreachable_is_a_gateway_failure(self):
        for error_number in (errno.EHOSTUNREACH, errno.ENETUNREACH):
            with self.subTest(error_number=error_number):
                def socket_factory(*unused):
                    raise OSError(error_number, "unreachable")

                result, _ = self.check(
                    [CompletedCommand(0, "default via 192.168.50.1 dev wlan0\n"), CompletedCommand(0, "")],
                    socket_factory,
                )
                self.assertFalse(result.success)
                self.assertEqual(result.category, "gateway_unreachable")

    def test_tcp_timeout_is_unverified(self):
        def socket_factory(*unused):
            raise socket.timeout()

        result, _ = self.check(
            [CompletedCommand(0, "default via 192.168.50.1 dev wlan0\n"), CompletedCommand(0, "")],
            socket_factory,
        )

        self.assertIsNone(result.success)
        self.assertEqual(result.category, "gateway_unverified")

    def test_missing_ip_tool_is_probe_unavailable(self):
        result, calls = self.check([FileNotFoundError()])

        self.assertIsNone(result.success)
        self.assertEqual(result.category, "gateway_probe_unavailable")
        self.assertEqual(calls, [["ip", "route"]])

    def test_ip_permission_failure_is_probe_unavailable(self):
        result, _ = self.check([CompletedCommand(1, stderr="Operation not permitted")])

        self.assertIsNone(result.success)
        self.assertEqual(result.category, "gateway_probe_unavailable")


class InternetChecksTests(unittest.TestCase):
    def setUp(self):
        self.config = NodeConfig(request_timeout_seconds=5)

    def check(self, responses):
        calls = []

        def opener(request, timeout, context):
            calls.append((request.full_url, timeout, context))
            response = responses.pop(0)
            if isinstance(response, BaseException):
                raise response
            return response

        result = check_internet(
            self.config,
            _opener=opener,
            _now=lambda: NOW,
            _monotonic=lambda: 1.0,
        )
        return result, calls

    def test_google_204_confirms_internet_with_tls_verification(self):
        result, calls = self.check([FakeResponse(204, b"")])

        self.assertTrue(result.success)
        self.assertEqual(result.category, "ok")
        self.assertEqual(calls[0][:2], ("https://connectivitycheck.gstatic.com/generate_204", 5))
        self.assertTrue(calls[0][2].check_hostname)
        self.assertEqual(calls[0][2].verify_mode, ssl.CERT_REQUIRED)

    def test_cloudflare_trace_confirms_internet_with_a_bounded_read(self):
        trace = FakeResponse(200, b"fl=1\nvisit_scheme=https\n")

        result, calls = self.check([FakeResponse(503, b""), trace])

        self.assertTrue(result.success)
        self.assertEqual(result.category, "ok")
        self.assertEqual([call[0] for call in calls], [
            "https://connectivitycheck.gstatic.com/generate_204",
            "https://www.cloudflare.com/cdn-cgi/trace",
        ])
        self.assertEqual(trace.read_sizes, [2048])

    def test_both_invalid_targets_report_their_separate_categories(self):
        result, _ = self.check([FakeResponse(200, b""), FakeResponse(200, b"visit_scheme=http\n")])

        self.assertFalse(result.success)
        self.assertEqual(result.category, "internet_failed")
        self.assertEqual(result.detail, "http_error,trace_invalid")

    def test_redirect_tls_dns_and_timeout_failures_are_classified(self):
        cases = (
            (HTTPError("https://example.invalid", 302, "redirect", {}, None), "redirect"),
            (URLError(ssl.SSLCertVerificationError()), "tls_error"),
            (URLError(socket.gaierror()), "dns_error"),
            (URLError(socket.timeout()), "timeout"),
        )
        for error, category in cases:
            with self.subTest(category=category):
                result, _ = self.check([error, FakeResponse(200, b"visit_scheme=http\n")])
                self.assertFalse(result.success)
                self.assertEqual(result.category, "internet_failed")
                self.assertEqual(result.detail, f"{category},trace_invalid")


if __name__ == "__main__":
    unittest.main()
