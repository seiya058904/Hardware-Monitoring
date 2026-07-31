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

from .node_state import NotificationEvent, TargetState


_STATE_FIELDS = {field.name for field in fields(TargetState)}
_NOTIFICATION_ERROR_INTERVAL_SECONDS = 3600


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


def _corrupt_path(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    candidate = path.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}")
    suffix = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}.corrupt-{stamp}-{suffix}{path.suffix}")
        suffix += 1
    return candidate


def load_state(path: Path) -> dict[str, TargetState]:
    """Load valid JSON state, isolating invalid input without executing it."""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("state must be a JSON object")
        if any(not isinstance(target, str) or not target for target in payload):
            raise ValueError("state target is invalid")
        return {target: _state_from_json(value) for target, value in payload.items()}
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        try:
            path.replace(_corrupt_path(path))
        except OSError:
            logging.getLogger(__name__).warning("state_corrupt_unpreserved")
        else:
            logging.getLogger(__name__).warning("state_corrupt_isolated")
        return {}


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
        return self._run(
            [
                "termux-notification",
                "--id",
                event.notification_id,
                "--title",
                event.title,
                "--content",
                event.content,
            ]
        )

    def cancel(self, notification_id: str) -> bool:
        return self._run(["termux-notification-remove", "--id", notification_id])
