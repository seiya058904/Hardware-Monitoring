import logging
from os import replace as os_replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from android.termux.node_runtime import (
    NotificationClient,
    configure_logging,
    load_state,
    save_state_atomic,
)
from android.termux.node_state import NotificationEvent, TargetState


STATE = TargetState(
    status="failed",
    consecutive_failures=3,
    consecutive_successes=0,
    failure_started_at="2026-07-31T10:00:00+00:00",
    last_notification_at="2026-07-31T10:02:00+00:00",
    last_success_at=None,
    last_category="timeout",
)
EVENT = NotificationEvent(
    target="dashboard",
    kind="failure",
    notification_id="hardware-monitor-node-dashboard",
    title="Hardware monitor: dashboard failed",
    content="timeout; failing for 120s; checked 2026-07-31T10:02:00+00:00",
)


class RuntimeStateTests(unittest.TestCase):
    def test_state_round_trip_preserves_target_state(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"

            save_state_atomic(path, {"dashboard": STATE})

            self.assertEqual(load_state(path), {"dashboard": STATE})

    def test_corrupt_state_is_isolated_and_loads_safe_empty_state(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text("not json", encoding="utf-8")

            with self.assertLogs("android.termux.node_runtime", level="WARNING"):
                self.assertEqual(load_state(path), {})

            copies = list(Path(directory).glob("state.corrupt-*.json"))
            self.assertEqual(len(copies), 1)
            self.assertEqual(copies[0].read_text(encoding="utf-8"), "not json")
            self.assertFalse(path.exists())

    def test_save_replaces_via_a_same_directory_temporary_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            replaced = []
            def recording_replace(source, destination):
                replaced.append((Path(source), Path(destination)))
                os_replace(source, destination)

            with patch("android.termux.node_runtime.os.replace", recording_replace):
                save_state_atomic(path, {"dashboard": STATE})

            self.assertEqual(len(replaced), 1)
            self.assertEqual(replaced[0][0].parent, path.parent)
            self.assertEqual(replaced[0][1], path)
            self.assertEqual(load_state(path), {"dashboard": STATE})


class RuntimeLoggingTests(unittest.TestCase):
    def test_configure_logging_uses_the_requested_rotation_limits(self):
        with TemporaryDirectory() as directory:
            logger = configure_logging(Path(directory) / "monitor.log", 1048576, 5)

            handlers = [handler for handler in logger.handlers if hasattr(handler, "maxBytes")]
            self.assertEqual(len(handlers), 1)
            self.assertEqual(handlers[0].maxBytes, 1048576)
            self.assertEqual(handlers[0].backupCount, 5)
            logger.removeHandler(handlers[0])
            handlers[0].close()


class NotificationClientTests(unittest.TestCase):
    def make_client(self, runner, monotonic=lambda: 10.0):
        logger = logging.getLogger("runtime-test")
        logger.handlers.clear()
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        return NotificationClient(logger, runner=runner, monotonic=monotonic)

    def test_notification_success_invokes_termux_with_the_event_fixed_id(self):
        commands = []
        client = self.make_client(lambda command: commands.append(command) or 0)

        self.assertTrue(client.send(EVENT))
        self.assertTrue(client.cancel(EVENT.notification_id))

        self.assertEqual(
            commands,
            [
                [
                    "termux-notification",
                    "--id",
                    "hardware-monitor-node-dashboard",
                    "--title",
                    "Hardware monitor: dashboard failed",
                    "--content",
                    "timeout; failing for 120s; checked 2026-07-31T10:02:00+00:00",
                ],
                ["termux-notification-remove", "--id", "hardware-monitor-node-dashboard"],
            ],
        )

    def test_absent_notification_command_returns_false(self):
        client = self.make_client(lambda command: (_ for _ in ()).throw(FileNotFoundError()))

        self.assertFalse(client.send(EVENT))

    def test_nonzero_notification_command_returns_false(self):
        client = self.make_client(lambda command: 1)

        self.assertFalse(client.send(EVENT))

    def test_notification_errors_are_rate_limited(self):
        logger = logging.getLogger("runtime-notification-errors")
        logger.handlers.clear()
        logger.setLevel(logging.ERROR)
        logger.propagate = False
        records = []

        class CollectingHandler(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        logger.addHandler(CollectingHandler())
        moments = iter((0.0, 1.0, 3600.0))
        client = NotificationClient(logger, runner=lambda command: 1, monotonic=lambda: next(moments))

        self.assertFalse(client.send(EVENT))
        self.assertFalse(client.send(EVENT))
        self.assertFalse(client.send(EVENT))

        self.assertEqual(records, ["notification_unavailable: command_failed"] * 2)


if __name__ == "__main__":
    unittest.main()
