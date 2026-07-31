from dataclasses import asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import StringIO
import json
from pathlib import Path
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from android.termux.node_checks import CheckResult
from android.termux.node_config import NodeConfig
from android.termux.node_state import NotificationEvent
from android.termux import monitor_node


NOW = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)


def result(target, success=True, category="ok"):
    return CheckResult(target, success, category, NOW, 7)


class FakeLock:
    def __init__(self, acquired=True):
        self.acquired = acquired
        self.released = False

    def acquire(self):
        return self.acquired

    def release(self):
        self.released = True


class FakeStopEvent:
    def __init__(self, on_wait=None):
        self.set_called = False
        self.waits = []
        self._on_wait = on_wait

    def set(self):
        self.set_called = True

    def is_set(self):
        return self.set_called

    def wait(self, seconds):
        self.waits.append(seconds)
        if self._on_wait:
            self._on_wait()
        return self.set_called


class MonitorNodeTests(unittest.TestCase):
    def test_direct_script_once_executes_without_a_relative_import_error(self):
        class DashboardHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = (
                    b'{"status":"ok"}'
                    if self.path == "/healthz"
                    else json.dumps(
                        {
                            "status": "ok",
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                            "metrics": {},
                        }
                    ).encode("utf-8")
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), DashboardHandler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        script = Path(__file__).parents[1] / "monitor_node.py"

        try:
            with TemporaryDirectory() as directory:
                config_path = Path(directory) / "config.json"
                config = NodeConfig(
                    dashboard_base_url=f"http://127.0.0.1:{server.server_port}",
                    check_gateway=False,
                    check_internet=False,
                    internet_probe_urls=(),
                )
                config_path.write_text(json.dumps(asdict(config)), encoding="utf-8")
                completed = subprocess.run(
                    [sys.executable, str(script), "--once", "--config", str(config_path)],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        self.assertRegex(completed.stdout, r"^dashboard healthy ok \d+ms\n$")

    def test_default_runtime_files_use_the_private_node_home(self):
        home = Path.home() / ".local" / "share" / "hardware-monitor-node"

        self.assertEqual(monitor_node.NODE_HOME, home)
        self.assertEqual(monitor_node.DEFAULT_CONFIG_PATH, home / "config.json")
        self.assertEqual(
            monitor_node._node_paths(),
            (home / "state.json", home / "logs" / "monitor.log", home / "monitor.lock"),
        )

    def test_run_once_skips_disabled_gateway_and_internet(self):
        config = NodeConfig(check_gateway=False, check_internet=False, internet_probe_urls=())

        with (
            patch("android.termux.monitor_node.check_dashboard", return_value=result("dashboard")) as dashboard,
            patch("android.termux.monitor_node.check_gateway") as gateway,
            patch("android.termux.monitor_node.check_internet") as internet,
        ):
            results = monitor_node.run_once(config, NOW)

        self.assertEqual(results, [result("dashboard")])
        dashboard.assert_called_once_with(config, NOW)
        gateway.assert_not_called()
        internet.assert_not_called()

    def test_run_once_converts_one_target_exception_and_continues_round(self):
        config = NodeConfig()

        with (
            patch("android.termux.monitor_node.check_dashboard", side_effect=OSError("offline")),
            patch("android.termux.monitor_node.check_gateway", return_value=result("gateway")),
            patch("android.termux.monitor_node.check_internet", return_value=result("internet")),
        ):
            results = monitor_node.run_once(config, NOW)

        self.assertEqual([item.target for item in results], ["dashboard", "gateway", "internet"])
        self.assertIsNone(results[0].success)
        self.assertEqual(results[0].category, "check_exception")
        self.assertEqual(results[0].detail, "OSError")

    def test_main_once_loads_config_and_prints_diagnostics(self):
        config = NodeConfig(check_gateway=False, check_internet=False, internet_probe_urls=())
        output = StringIO()

        with (
            patch("android.termux.monitor_node.load_config", return_value=config) as load,
            patch("android.termux.monitor_node.run_once", return_value=[result("dashboard", False, "timeout")]) as run,
            patch("sys.stdout", output),
        ):
            code = monitor_node.main(["--once", "--config", "node.json"])

        self.assertEqual(code, 0)
        load.assert_called_once_with(Path("node.json"))
        run.assert_called_once()
        self.assertEqual(output.getvalue(), "dashboard failed timeout 7ms\n")

    def test_main_once_returns_configuration_error_exit(self):
        output = StringIO()

        with patch("android.termux.monitor_node.load_config", side_effect=ValueError("bad config")), patch(
            "sys.stderr", output
        ):
            code = monitor_node.main(["--once"])

        self.assertEqual(code, 2)
        self.assertEqual(output.getvalue(), "configuration error\n")

    def test_run_forever_returns_when_instance_lock_is_contended(self):
        lock = FakeLock(acquired=False)

        with (
            TemporaryDirectory() as directory,
            patch("android.termux.monitor_node.load_config", return_value=NodeConfig()),
            patch("android.termux.monitor_node.configure_logging"),
            patch("android.termux.monitor_node.InstanceLock", return_value=lock),
        ):
            code = monitor_node.run_forever(Path(directory) / "config.json")

        self.assertEqual(code, 1)
        self.assertFalse(lock.released)

    def test_run_forever_advances_saves_dispatches_and_waits_for_interval(self):
        config = NodeConfig(
            check_interval_seconds=9,
            failure_threshold=1,
            check_gateway=False,
            check_internet=False,
            internet_probe_urls=(),
        )
        lock = FakeLock()
        waits = 0

        def stop_after_second_wait():
            nonlocal waits
            waits += 1
            if waits == 2:
                stop_event.set()

        stop_event = FakeStopEvent(stop_after_second_wait)
        event = NotificationEvent(
            "dashboard", "failure", "hardware-monitor-node-dashboard", "title", "content"
        )

        with (
            TemporaryDirectory() as directory,
            patch("android.termux.monitor_node.load_config", return_value=config),
            patch("android.termux.monitor_node.configure_logging", return_value=object()),
            patch("android.termux.monitor_node.InstanceLock", return_value=lock),
            patch("android.termux.monitor_node.load_state", return_value={}),
            patch(
                "android.termux.monitor_node.run_once",
                side_effect=[[result("dashboard", False, "timeout")], [result("dashboard")]],
            ) as run,
            patch(
                "android.termux.monitor_node.advance_state",
                side_effect=[(object(), [event]), (object(), [])],
            ) as advance,
            patch("android.termux.monitor_node.save_state_atomic") as save,
            patch("android.termux.monitor_node.NotificationClient") as notifications,
            patch("android.termux.monitor_node.log_check_result"),
            patch("android.termux.monitor_node.threading.Event", return_value=stop_event),
        ):
            code = monitor_node.run_forever(Path(directory) / "config.json")

        self.assertEqual(code, 0)
        self.assertEqual(stop_event.waits, [9, 9])
        self.assertEqual(run.call_count, 2)
        self.assertEqual(advance.call_count, 2)
        self.assertGreaterEqual(save.call_count, 2)
        notifications.return_value.send.assert_called_once_with(event)
        self.assertTrue(lock.released)

    def test_sigterm_saves_state_and_releases_lock(self):
        config = NodeConfig(check_gateway=False, check_internet=False, internet_probe_urls=())
        lock = FakeLock()
        handlers = {}
        stop_event = FakeStopEvent()

        def trigger_sigterm():
            handlers[signal.SIGTERM](signal.SIGTERM, None)

        stop_event._on_wait = trigger_sigterm

        with (
            TemporaryDirectory() as directory,
            patch("android.termux.monitor_node.load_config", return_value=config),
            patch("android.termux.monitor_node.configure_logging", return_value=object()),
            patch("android.termux.monitor_node.InstanceLock", return_value=lock),
            patch("android.termux.monitor_node.load_state", return_value={}),
            patch("android.termux.monitor_node.run_once", return_value=[result("dashboard")]),
            patch("android.termux.monitor_node.save_state_atomic") as save,
            patch("android.termux.monitor_node.NotificationClient"),
            patch("android.termux.monitor_node.log_check_result"),
            patch("android.termux.monitor_node.threading.Event", return_value=stop_event),
            patch(
                "android.termux.monitor_node.signal.signal",
                side_effect=lambda signum, handler: handlers.__setitem__(signum, handler),
            ),
        ):
            code = monitor_node.run_forever(Path(directory) / "config.json")

        self.assertEqual(code, 0)
        self.assertTrue(stop_event.set_called)
        self.assertGreaterEqual(save.call_count, 1)
        self.assertTrue(lock.released)


if __name__ == "__main__":
    unittest.main()
