"""CLI composition for the read-only Termux monitoring node."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import signal
import subprocess
import sys
import threading
from typing import Sequence

from .node_checks import CheckResult, CompletedCommand, check_dashboard, check_gateway, check_internet
from .node_config import NodeConfig, load_config
from .node_runtime import (
    InstanceLock,
    NotificationClient,
    configure_logging,
    load_state,
    log_check_result,
    save_state_atomic,
)
from .node_state import advance_state, default_target_state


DEFAULT_CONFIG_PATH = Path.home() / ".hardware-monitor-node" / "config.json"


def _run_command(command: list[str]) -> CompletedCommand:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    return CompletedCommand(completed.returncode, completed.stdout, completed.stderr)


def _check_exception(target: str, now: datetime, error: Exception) -> CheckResult:
    return CheckResult(target, None, "check_exception", now, 0, type(error).__name__)


def run_once(config: NodeConfig, now: datetime) -> list[CheckResult]:
    """Run every enabled probe once, isolating an unexpected target failure."""
    checks = [("dashboard", lambda: check_dashboard(config, now))]
    if config.check_gateway:
        checks.append(("gateway", lambda: check_gateway(config, _run_command)))
    if config.check_internet:
        checks.append(("internet", lambda: check_internet(config)))

    results = []
    for target, check in checks:
        try:
            results.append(check())
        except Exception as error:
            results.append(_check_exception(target, now, error))
    return results


def _outcome(result: CheckResult) -> str:
    return "healthy" if result.success is True else "failed" if result.success is False else "unknown"


def _node_paths(config_path: Path) -> tuple[Path, Path, Path]:
    directory = config_path.parent
    return directory / "state.json", directory / "monitor.log", directory / "monitor.lock"


def run_forever(config_path: Path) -> int:
    """Run scheduled checks until SIGINT or SIGTERM requests a graceful stop."""
    try:
        config = load_config(config_path)
    except ValueError:
        print("configuration error", file=sys.stderr)
        return 2

    state_path, log_path, lock_path = _node_paths(config_path)
    logger = configure_logging(log_path, config.log_max_bytes, config.log_backup_count)
    lock = InstanceLock(lock_path, Path(__file__))
    if not lock.acquire():
        logger.error("instance_lock_contended")
        return 1

    stop_event = threading.Event()
    previous_handlers = {}

    def stop(signum, frame) -> None:
        stop_event.set()

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, stop)

        states = load_state(state_path)
        notifications = NotificationClient(logger)
        while not stop_event.is_set():
            now = datetime.now(timezone.utc)
            events = []
            for result in run_once(config, now):
                log_check_result(logger, result)
                state, target_events = advance_state(
                    states.get(result.target, default_target_state()), result, config, now
                )
                states[result.target] = state
                events.extend(target_events)
            save_state_atomic(state_path, states)
            for event in events:
                notifications.send(event)
            if stop_event.wait(config.check_interval_seconds):
                break
        return 0
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        lock.release()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Termux hardware monitoring node")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--once", action="store_true", help="run one diagnostic round")
    arguments = parser.parse_args(argv)

    if not arguments.once:
        return run_forever(arguments.config)
    try:
        config = load_config(arguments.config)
    except ValueError:
        print("configuration error", file=sys.stderr)
        return 2
    for result in run_once(config, datetime.now(timezone.utc)):
        print(f"{result.target} {_outcome(result)} {result.category} {result.duration_ms}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
