from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import unittest

from android.termux.node_config import NodeConfig
from android.termux.node_state import (
    NotificationEvent,
    advance_state,
    default_target_state,
)


@dataclass(frozen=True)
class CheckResult:
    target: str
    success: bool | None
    category: str
    checked_at: datetime
    duration_ms: int = 5
    detail: str = ""


NOW = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)


class TargetStateTests(unittest.TestCase):
    def setUp(self):
        self.config = NodeConfig(
            failure_threshold=2,
            recovery_threshold=3,
            reminder_interval_seconds=120,
        )

    def result(self, success, category, at=NOW):
        return CheckResult("dashboard", success, category, at)

    def test_unknown_success_becomes_healthy_without_notification(self):
        state, events = advance_state(
            default_target_state(), self.result(True, "ok"), self.config, NOW
        )

        self.assertEqual(state.status, "healthy")
        self.assertEqual(state.consecutive_failures, 0)
        self.assertEqual(state.consecutive_successes, 0)
        self.assertEqual(state.last_success_at, "2026-07-31T10:00:00+00:00")
        self.assertEqual(state.last_category, "ok")
        self.assertEqual(events, [])

    def test_first_failure_is_suspected_using_configured_threshold(self):
        state, events = advance_state(
            default_target_state(), self.result(False, "timeout"), self.config, NOW
        )

        self.assertEqual(state.status, "suspected_failure")
        self.assertEqual(state.consecutive_failures, 1)
        self.assertEqual(state.failure_started_at, "2026-07-31T10:00:00+00:00")
        self.assertEqual(events, [])

    def test_second_failure_confirms_failure_with_fixed_target_event_id(self):
        suspected, _ = advance_state(
            default_target_state(), self.result(False, "timeout"), self.config, NOW
        )
        state, events = advance_state(
            suspected,
            self.result(False, "unreachable", NOW + timedelta(minutes=1)),
            self.config,
            NOW + timedelta(minutes=1),
        )

        self.assertEqual(state.status, "failed")
        self.assertEqual(state.consecutive_failures, 2)
        self.assertEqual(state.last_notification_at, "2026-07-31T10:01:00+00:00")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].target, "dashboard")
        self.assertEqual(events[0].kind, "failure")
        self.assertEqual(events[0].notification_id, "hardware-monitor-node-dashboard")
        self.assertEqual(
            events[0].content,
            "unreachable; failing for 60s; checked 2026-07-31T10:01:00+00:00",
        )

    def test_confirmed_failure_enters_recovering_after_one_success(self):
        suspected, _ = advance_state(
            default_target_state(), self.result(False, "timeout"), self.config, NOW
        )
        failed, _ = advance_state(
            suspected,
            self.result(False, "unreachable", NOW + timedelta(minutes=1)),
            self.config,
            NOW + timedelta(minutes=1),
        )
        state, events = advance_state(
            failed,
            self.result(True, "ok", NOW + timedelta(minutes=2)),
            self.config,
            NOW + timedelta(minutes=2),
        )

        self.assertEqual(state.status, "recovering")
        self.assertEqual(state.consecutive_failures, 0)
        self.assertEqual(state.consecutive_successes, 1)
        self.assertEqual(events, [])

    def test_third_success_confirms_recovery_using_configured_threshold(self):
        state = default_target_state()
        for offset, success, category in (
            (0, False, "timeout"),
            (1, False, "unreachable"),
            (2, True, "ok"),
            (3, True, "ok"),
        ):
            now = NOW + timedelta(minutes=offset)
            state, _ = advance_state(state, self.result(success, category, now), self.config, now)

        recovered_at = NOW + timedelta(minutes=4)
        state, events = advance_state(
            state, self.result(True, "ok", recovered_at), self.config, recovered_at
        )

        self.assertEqual(state.status, "healthy")
        self.assertEqual(state.failure_started_at, None)
        self.assertEqual(state.consecutive_successes, 0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "recovery")
        self.assertEqual(events[0].notification_id, "hardware-monitor-node-dashboard")

    def test_failure_reminder_waits_for_configured_interval(self):
        suspected, _ = advance_state(
            default_target_state(), self.result(False, "timeout"), self.config, NOW
        )
        failed_at = NOW + timedelta(minutes=1)
        failed, _ = advance_state(
            suspected, self.result(False, "unreachable", failed_at), self.config, failed_at
        )
        early_at = failed_at + timedelta(seconds=119)
        throttled, events = advance_state(
            failed, self.result(False, "unreachable", early_at), self.config, early_at
        )
        due_at = failed_at + timedelta(seconds=120)
        reminded, events_due = advance_state(
            throttled, self.result(False, "unreachable", due_at), self.config, due_at
        )

        self.assertEqual(events, [])
        self.assertEqual(len(events_due), 1)
        self.assertEqual(events_due[0].kind, "failure")
        self.assertEqual(reminded.last_notification_at, "2026-07-31T10:03:00+00:00")

    def test_unknown_result_does_not_count_as_failure(self):
        suspected, _ = advance_state(
            default_target_state(), self.result(False, "timeout"), self.config, NOW
        )
        state, events = advance_state(
            suspected,
            self.result(None, "gateway_unverified", NOW + timedelta(minutes=1)),
            self.config,
            NOW + timedelta(minutes=1),
        )

        self.assertEqual(state.status, "suspected_failure")
        self.assertEqual(state.consecutive_failures, 1)
        self.assertEqual(state.consecutive_successes, 0)
        self.assertEqual(state.last_category, "gateway_unverified")
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
