from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
import logging
import os
from os import close as os_close
from os import fsync as os_fsync
from os import open as os_open
from os import replace as os_replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from android.termux.node_runtime import (
    InstanceLock,
    NotificationClient,
    configure_logging,
    log_check_result,
    load_state,
    save_state_atomic,
)
from android.termux.node_checks import CheckResult
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
            self.assertTrue(path.exists())

    def test_invalid_target_does_not_discard_valid_sibling_state(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(
                json.dumps({"dashboard": asdict(STATE), "internet": {"status": "broken"}}),
                encoding="utf-8",
            )

            with self.assertLogs("android.termux.node_runtime", level="WARNING"):
                self.assertEqual(load_state(path), {"dashboard": STATE})

            self.assertTrue(path.exists())
            self.assertEqual(len(list(Path(directory).glob("state.corrupt-*.json"))), 1)

    def test_corrupt_sidecopy_does_not_overwrite_a_racing_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text("not json", encoding="utf-8")
            real_open = os.open
            conflicts = []

            def competing_open(name, flags, mode=0o777):
                candidate = Path(name)
                if candidate.name.startswith("state.corrupt-") and flags & os.O_EXCL:
                    conflicts.append(candidate)
                    if len(conflicts) == 1:
                        candidate.write_bytes(b"already preserved")
                        raise FileExistsError()
                return real_open(name, flags, mode)

            with patch("android.termux.node_runtime.os.open", competing_open):
                with self.assertLogs("android.termux.node_runtime", level="WARNING"):
                    self.assertEqual(load_state(path), {})

            copies = list(Path(directory).glob("state.corrupt-*.json"))
            self.assertEqual(len(copies), 2)
            self.assertIn(b"already preserved", [copy.read_bytes() for copy in copies])
            self.assertIn(b"not json", [copy.read_bytes() for copy in copies])

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

    def test_save_syncs_its_parent_directory_when_supported(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            synced = []

            def directory_open(name, flags, mode=0o777):
                return 71 if Path(name) == path.parent else os_open(name, flags, mode)

            def directory_sync(descriptor):
                if descriptor == 71:
                    synced.append(descriptor)
                else:
                    os_fsync(descriptor)

            def directory_close(descriptor):
                if descriptor != 71:
                    os_close(descriptor)

            with (
                patch("android.termux.node_runtime.os.open", directory_open),
                patch("android.termux.node_runtime.os.fsync", directory_sync),
                patch("android.termux.node_runtime.os.close", directory_close),
            ):
                save_state_atomic(path, {"dashboard": STATE})

            self.assertEqual(synced, [71])


class InstanceLockTests(unittest.TestCase):
    def write_lock(self, path, script_path, *, pid=202, ticks=999):
        path.write_text(
            json.dumps(
                {
                    "pid": pid,
                    "started_at": "2026-07-31T10:00:00+00:00",
                    "process_start_ticks": ticks,
                    "script_path": str(script_path),
                }
            ),
            encoding="utf-8",
        )

    def test_exclusive_creation_writes_the_required_lock_record(self):
        with TemporaryDirectory() as directory:
            lock_path = Path(directory) / "node.lock"
            script_path = (Path(directory) / "monitor_node.py").resolve()
            with (
                patch("android.termux.node_runtime.os.getpid", return_value=101),
                patch("android.termux.node_runtime._read_process_start_ticks", return_value=1001),
            ):
                lock = InstanceLock(lock_path, script_path)

                self.assertTrue(lock.acquire())

            record = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(
                record,
                {
                    "pid": 101,
                    "started_at": record["started_at"],
                    "process_start_ticks": 1001,
                    "script_path": str(script_path),
                },
            )
            self.assertIsInstance(record["started_at"], str)

    def test_acquire_publishes_only_a_complete_lock_file(self):
        with TemporaryDirectory() as directory:
            lock_path = Path(directory) / "node.lock"
            script_path = (Path(directory) / "monitor_node.py").resolve()
            real_link = os.link
            published = []

            def recording_link(source, destination):
                self.assertEqual(Path(destination), lock_path)
                self.assertFalse(lock_path.exists())
                published.append(json.loads(Path(source).read_text(encoding="utf-8")))
                real_link(source, destination)

            with (
                patch("android.termux.node_runtime.os.getpid", return_value=101),
                patch("android.termux.node_runtime._read_process_start_ticks", return_value=1001),
                patch("android.termux.node_runtime.os.link", recording_link),
            ):
                self.assertTrue(InstanceLock(lock_path, script_path).acquire())

            self.assertEqual(len(published), 1)
            self.assertEqual(published[0]["pid"], 101)

    def test_stale_lock_is_atomically_moved_before_replacement(self):
        with TemporaryDirectory() as directory:
            lock_path = Path(directory) / "node.lock"
            script_path = (Path(directory) / "monitor_node.py").resolve()
            self.write_lock(lock_path, script_path)
            real_replace = os.replace
            claims = []

            def recording_replace(source, destination):
                if Path(source) == lock_path:
                    claims.append(Path(destination))
                real_replace(source, destination)

            with (
                patch("android.termux.node_runtime.os.getpid", return_value=101),
                patch("android.termux.node_runtime.os.kill", side_effect=ProcessLookupError),
                patch("android.termux.node_runtime._read_process_start_ticks", return_value=1001),
                patch("android.termux.node_runtime.os.replace", recording_replace),
            ):
                self.assertTrue(InstanceLock(lock_path, script_path).acquire())

            self.assertEqual(len(claims), 1)
            self.assertNotEqual(claims[0], lock_path)

    def test_active_matching_node_keeps_its_exclusive_lock(self):
        with TemporaryDirectory() as directory:
            lock_path = Path(directory) / "node.lock"
            script_path = (Path(directory) / "monitor_node.py").resolve()
            with (
                patch("android.termux.node_runtime.os.getpid", return_value=101),
                patch("android.termux.node_runtime.os.kill"),
                patch("android.termux.node_runtime._read_process_cmdline", return_value=[str(script_path)]),
                patch("android.termux.node_runtime._read_process_start_ticks", return_value=1001),
            ):
                self.assertTrue(InstanceLock(lock_path, script_path).acquire())
                self.assertFalse(InstanceLock(lock_path, script_path).acquire())

    def test_dead_pid_lock_is_replaced_without_signaling_a_process(self):
        with TemporaryDirectory() as directory:
            lock_path = Path(directory) / "node.lock"
            script_path = (Path(directory) / "monitor_node.py").resolve()
            self.write_lock(lock_path, script_path)
            with (
                patch("android.termux.node_runtime.os.getpid", return_value=101),
                patch("android.termux.node_runtime.os.kill", side_effect=ProcessLookupError) as kill,
                patch("android.termux.node_runtime._read_process_start_ticks", return_value=1001),
            ):
                self.assertTrue(InstanceLock(lock_path, script_path).acquire())

            kill.assert_called_once_with(202, 0)
            self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8"))["pid"], 101)

    def test_corrupt_lock_is_replaced(self):
        with TemporaryDirectory() as directory:
            lock_path = Path(directory) / "node.lock"
            script_path = (Path(directory) / "monitor_node.py").resolve()
            lock_path.write_text("not json", encoding="utf-8")
            with (
                patch("android.termux.node_runtime.os.getpid", return_value=101),
                patch("android.termux.node_runtime._read_process_start_ticks", return_value=1001),
            ):
                self.assertTrue(InstanceLock(lock_path, script_path).acquire())

            self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8"))["pid"], 101)

    def test_active_pid_with_a_mismatched_cmdline_lock_is_replaced(self):
        with TemporaryDirectory() as directory:
            lock_path = Path(directory) / "node.lock"
            script_path = (Path(directory) / "monitor_node.py").resolve()
            self.write_lock(lock_path, script_path)
            with (
                patch("android.termux.node_runtime.os.getpid", return_value=101),
                patch("android.termux.node_runtime.os.kill"),
                patch("android.termux.node_runtime._read_process_cmdline", return_value=["/other/script.py"]),
                patch("android.termux.node_runtime._read_process_start_ticks", return_value=999),
            ):
                self.assertTrue(InstanceLock(lock_path, script_path).acquire())

            self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8"))["pid"], 101)

    def test_reused_pid_with_different_start_ticks_lock_is_replaced(self):
        with TemporaryDirectory() as directory:
            lock_path = Path(directory) / "node.lock"
            script_path = (Path(directory) / "monitor_node.py").resolve()
            self.write_lock(lock_path, script_path)
            with (
                patch("android.termux.node_runtime.os.getpid", return_value=101),
                patch("android.termux.node_runtime.os.kill"),
                patch("android.termux.node_runtime._read_process_cmdline", return_value=[str(script_path)]),
                patch("android.termux.node_runtime._read_process_start_ticks", return_value=1000),
            ):
                self.assertTrue(InstanceLock(lock_path, script_path).acquire())

            self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8"))["pid"], 101)

    def test_release_does_not_remove_a_lock_replaced_by_another_instance(self):
        with TemporaryDirectory() as directory:
            lock_path = Path(directory) / "node.lock"
            script_path = (Path(directory) / "monitor_node.py").resolve()
            with (
                patch("android.termux.node_runtime.os.getpid", return_value=101),
                patch("android.termux.node_runtime._read_process_start_ticks", return_value=1001),
            ):
                lock = InstanceLock(lock_path, script_path)
                self.assertTrue(lock.acquire())
            self.write_lock(lock_path, script_path, pid=202, ticks=999)

            lock.release()

            self.assertTrue(lock_path.exists())

    def test_release_keeps_an_equivalent_record_replaced_after_acquire(self):
        with TemporaryDirectory() as directory:
            lock_path = Path(directory) / "node.lock"
            script_path = (Path(directory) / "monitor_node.py").resolve()
            with (
                patch("android.termux.node_runtime.os.getpid", return_value=101),
                patch("android.termux.node_runtime._read_process_start_ticks", return_value=1001),
            ):
                lock = InstanceLock(lock_path, script_path)
                self.assertTrue(lock.acquire())
            equivalent_path = Path(directory) / "equivalent.lock"
            equivalent_path.write_bytes(lock_path.read_bytes())
            os.replace(equivalent_path, lock_path)

            lock.release()

            self.assertTrue(lock_path.exists())


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

    def test_outcome_logging_is_bounded_and_summarized_without_healthy_info_spam(self):
        logger = logging.getLogger("runtime-outcome-log")
        logger.handlers.clear()
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        records = []

        class CollectingHandler(logging.Handler):
            def emit(self, record):
                records.append((record.levelname, record.getMessage()))

        logger.addHandler(CollectingHandler())
        failed = CheckResult(
            "dashboard", False, "timeout", datetime.now(timezone.utc), 12, "x" * 1000
        )
        healthy = CheckResult("dashboard", True, "ok", datetime.now(timezone.utc), 4)

        log_check_result(logger, failed, monotonic=lambda: 0.0)
        log_check_result(logger, healthy, monotonic=lambda: 1.0)
        log_check_result(logger, healthy, monotonic=lambda: 3600.0)

        self.assertIn("outcome=failed category=timeout duration_ms=12", records[0][1])
        self.assertNotIn("x" * 1000, records[0][1])
        self.assertEqual([level for level, _ in records].count("INFO"), 1)
        self.assertIn("summary checks=3 healthy=2 failed=1 unknown=0", records[-1][1])


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

    def test_notification_rejects_an_arbitrary_event_id(self):
        commands = []
        client = self.make_client(lambda command: commands.append(command) or 0)

        self.assertFalse(client.send(replace(EVENT, notification_id="unrelated-notification")))

        self.assertEqual(commands, [])

    def test_notification_rejects_a_non_string_target_without_running_a_command(self):
        commands = []
        client = self.make_client(lambda command: commands.append(command) or 0)

        self.assertFalse(client.send(replace(EVENT, target=[])))

        self.assertEqual(commands, [])

    def test_notification_cancel_rejects_an_arbitrary_id(self):
        commands = []
        client = self.make_client(lambda command: commands.append(command) or 0)

        self.assertFalse(client.cancel("unrelated-notification"))

        self.assertEqual(commands, [])

    def test_notification_content_is_bounded_at_the_client_boundary(self):
        commands = []
        client = self.make_client(lambda command: commands.append(command) or 0)

        self.assertTrue(client.send(replace(EVENT, content="x" * 1000)))

        self.assertEqual(len(commands[0][-1]), 512)

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
