"""Local persistence, logging, and Termux notification adaptation."""

from dataclasses import asdict, fields
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Callable

from .node_checks import CheckResult
from .node_state import NotificationEvent, TargetState


_STATE_FIELDS = {field.name for field in fields(TargetState)}
_NOTIFICATION_ERROR_INTERVAL_SECONDS = 3600
_NOTIFICATION_TARGETS = frozenset(("dashboard", "gateway", "internet"))
_NOTIFICATION_TITLE_LIMIT = 128
_NOTIFICATION_CONTENT_LIMIT = 512
_LOG_DETAIL_LIMIT = 160
_LOG_SUMMARY_INTERVAL_SECONDS = 3600


def _state_from_json(value: object) -> TargetState:
    if not isinstance(value, dict) or set(value) != _STATE_FIELDS:
        raise ValueError("state entry has an invalid schema")
    if not isinstance(value["status"], str) or not value["status"]:
        raise ValueError("state status is invalid")
    for field_name in ("consecutive_failures", "consecutive_successes"):
        if type(value[field_name]) is not int or value[field_name] < 0:
            raise ValueError(f"state {field_name} is invalid")
    for field_name in (
        "failure_started_at",
        "last_notification_at",
        "last_success_at",
        "last_category",
    ):
        if value[field_name] is not None and not isinstance(value[field_name], str):
            raise ValueError(f"state {field_name} is invalid")
    return TargetState(**value)


def _preserve_corrupt(path: Path, contents: bytes) -> bool:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    for suffix in range(100):
        suffix_text = "" if suffix == 0 else f"-{suffix}"
        candidate = path.with_name(f"{path.stem}.corrupt-{stamp}{suffix_text}{path.suffix}")
        try:
            descriptor = os.open(
                candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
        except FileExistsError:
            continue
        except OSError:
            return False
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(contents)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            return False
        return True
    return False


def _state_corrupt(path: Path, contents: bytes) -> None:
    category = "state_corrupt_isolated" if _preserve_corrupt(path, contents) else "state_corrupt_unpreserved"
    logging.getLogger(__name__).warning(category)


def load_state(path: Path) -> dict[str, TargetState]:
    """Load valid JSON state, isolating invalid input without executing it."""
    try:
        contents = path.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError:
        logging.getLogger(__name__).warning("state_unreadable")
        return {}
    try:
        payload = json.loads(contents)
        if not isinstance(payload, dict):
            raise ValueError("state must be a JSON object")
    except (TypeError, ValueError, json.JSONDecodeError):
        _state_corrupt(path, contents)
        return {}

    states = {}
    invalid = False
    for target, value in payload.items():
        if not isinstance(target, str) or not target:
            invalid = True
            continue
        try:
            states[target] = _state_from_json(value)
        except (TypeError, ValueError):
            invalid = True
    if invalid:
        _state_corrupt(path, contents)
    return states


def _sync_parent_directory(path: Path) -> None:
    try:
        descriptor = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def save_state_atomic(path: Path, states: dict[str, TargetState]) -> None:
    """Persist state using a synced temporary file in the destination directory."""
    if any(
        not isinstance(target, str) or not target or not isinstance(state, TargetState)
        for target, state in states.items()
    ):
        raise ValueError("states must map target names to TargetState values")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({target: asdict(state) for target, state in states.items()}, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        _sync_parent_directory(path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def configure_logging(log_path: Path, max_bytes: int, backup_count: int) -> logging.Logger:
    """Configure one local rotating log file with bounded retention."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"hardware_monitor_node.{log_path.resolve()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(
        isinstance(handler, RotatingFileHandler)
        and Path(handler.baseFilename) == log_path.resolve()
        for handler in logger.handlers
    ):
        handler = RotatingFileHandler(
            log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def _limited_text(value: object, limit: int) -> str:
    return " ".join(str(value).split())[:limit]


def log_check_result(
    logger: logging.Logger,
    result: CheckResult,
    *,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Log failures immediately and aggregate all check outcomes hourly."""
    outcome = "healthy" if result.success is True else "failed" if result.success is False else "unknown"
    now = monotonic()
    counters = getattr(logger, "_hardware_monitor_summary", None)
    if counters is None:
        counters = {"started": now, "checks": 0, "healthy": 0, "failed": 0, "unknown": 0}
    counters["checks"] += 1
    counters[outcome] += 1
    if outcome != "healthy":
        logger.warning(
            "check target=%s outcome=%s category=%s duration_ms=%s detail=%s",
            _limited_text(result.target, 64),
            outcome,
            _limited_text(result.category, 64),
            max(0, int(result.duration_ms)),
            _limited_text(result.detail, _LOG_DETAIL_LIMIT),
        )
    if now - counters["started"] >= _LOG_SUMMARY_INTERVAL_SECONDS:
        logger.info(
            "summary checks=%s healthy=%s failed=%s unknown=%s",
            counters["checks"],
            counters["healthy"],
            counters["failed"],
            counters["unknown"],
        )
        counters = {"started": now, "checks": 0, "healthy": 0, "failed": 0, "unknown": 0}
    logger._hardware_monitor_summary = counters


def _run_notification(command: list[str]) -> int:
    return subprocess.run(
        command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ).returncode


class NotificationClient:
    """Best-effort Termux:API notifications that never change monitoring state."""

    def __init__(
        self,
        logger: logging.Logger,
        *,
        runner: Callable[[list[str]], int] = _run_notification,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._logger = logger
        self._runner = runner
        self._monotonic = monotonic
        self._last_error_at: float | None = None

    def _run(self, command: list[str]) -> bool:
        try:
            result = self._runner(command)
            returncode = result if isinstance(result, int) else result.returncode
        except (OSError, AttributeError):
            self._error("command_unavailable")
            return False
        if returncode != 0:
            self._error("command_failed")
            return False
        return True

    def _error(self, category: str) -> None:
        now = self._monotonic()
        if (
            self._last_error_at is None
            or now - self._last_error_at >= _NOTIFICATION_ERROR_INTERVAL_SECONDS
        ):
            self._logger.error("notification_unavailable: %s", category)
            self._last_error_at = now

    def send(self, event: NotificationEvent) -> bool:
        if (
            not isinstance(event.target, str)
            or event.target not in _NOTIFICATION_TARGETS
            or event.notification_id != f"hardware-monitor-node-{event.target}"
            or not isinstance(event.title, str)
            or not isinstance(event.content, str)
        ):
            self._error("invalid_event")
            return False
        return self._run(
            [
                "termux-notification",
                "--id",
                event.notification_id,
                "--title",
                event.title[:_NOTIFICATION_TITLE_LIMIT],
                "--content",
                event.content[:_NOTIFICATION_CONTENT_LIMIT],
            ]
        )

    def cancel(self, notification_id: str) -> bool:
        if not isinstance(notification_id, str) or notification_id not in {
            f"hardware-monitor-node-{target}" for target in _NOTIFICATION_TARGETS
        }:
            self._error("invalid_event")
            return False
        return self._run(["termux-notification-remove", "--id", notification_id])
