"""Pure per-target monitoring state transitions."""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING

from .node_config import NodeConfig

if TYPE_CHECKING:
    from .node_checks import CheckResult


@dataclass
class TargetState:
    status: str
    consecutive_failures: int
    consecutive_successes: int
    failure_started_at: str | None
    last_notification_at: str | None
    last_success_at: str | None
    last_category: str | None


@dataclass(frozen=True)
class NotificationEvent:
    target: str
    kind: str
    notification_id: str
    title: str
    content: str


def default_target_state() -> TargetState:
    return TargetState("unknown", 0, 0, None, None, None, None)


def _notification(
    target: str, kind: str, category: str, now: datetime, failure_started_at: str | None
) -> NotificationEvent:
    checked_at = now.isoformat()
    suffix = "recovered" if kind == "recovery" else "failed"
    try:
        duration = max(0, int((now - datetime.fromisoformat(failure_started_at or checked_at)).total_seconds()))
    except (TypeError, ValueError):
        duration = 0
    duration_text = "outage" if kind == "recovery" else "failing"
    return NotificationEvent(
        target=target,
        kind=kind,
        notification_id=f"hardware-monitor-node-{target}",
        title=f"Hardware monitor: {target} {suffix}",
        content=f"{category}; {duration_text} for {duration}s; checked {checked_at}",
    )


def _reminder_due(last_notification_at: str | None, now: datetime, interval: int) -> bool:
    if last_notification_at is None:
        return True
    try:
        previous = datetime.fromisoformat(last_notification_at)
        return (now - previous).total_seconds() >= interval
    except (TypeError, ValueError):
        return True


def advance_state(
    current: TargetState, result: "CheckResult", config: NodeConfig, now: datetime
) -> tuple[TargetState, list[NotificationEvent]]:
    """Advance one target without performing I/O or mutating ``current``."""
    timestamp = now.isoformat()

    if result.success is None:
        return replace(current, last_category=result.category), []

    if result.success is True:
        updated = replace(current, last_success_at=timestamp, last_category=result.category)
        if current.status in ("failed", "recovering"):
            successes = 1 if current.status == "failed" else current.consecutive_successes + 1
            if successes < config.recovery_threshold:
                return (
                    replace(
                        updated,
                        status="recovering",
                        consecutive_failures=0,
                        consecutive_successes=successes,
                    ),
                    [],
                )
            event = _notification(
                result.target, "recovery", result.category, now, current.failure_started_at
            )
            return (
                replace(
                    updated,
                    status="healthy",
                    consecutive_failures=0,
                    consecutive_successes=0,
                    failure_started_at=None,
                    last_notification_at=timestamp,
                ),
                [event],
            )
        return (
            replace(
                updated,
                status="healthy",
                consecutive_failures=0,
                consecutive_successes=0,
                failure_started_at=None,
            ),
            [],
        )

    failures = current.consecutive_failures + 1
    failure_started_at = current.failure_started_at or timestamp
    updated = replace(
        current,
        consecutive_failures=failures,
        consecutive_successes=0,
        failure_started_at=failure_started_at,
        last_category=result.category,
    )
    if current.status not in ("failed", "recovering") and failures < config.failure_threshold:
        return replace(updated, status="suspected_failure"), []

    if current.status not in ("failed", "recovering"):
        event = _notification(result.target, "failure", result.category, now, failure_started_at)
        return replace(updated, status="failed", last_notification_at=timestamp), [event]

    if _reminder_due(current.last_notification_at, now, config.reminder_interval_seconds):
        event = _notification(result.target, "failure", result.category, now, failure_started_at)
        return replace(updated, status="failed", last_notification_at=timestamp), [event]
    return replace(updated, status="failed"), []
