"""Stateless network probes for the Termux monitoring node."""

from dataclasses import dataclass
from datetime import datetime
import json
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .node_config import NodeConfig


_MAX_RESPONSE_BYTES = 65536


@dataclass(frozen=True)
class CheckResult:
    target: str
    success: bool | None
    category: str
    checked_at: datetime
    duration_ms: int
    detail: str = ""


def _load_json(response) -> object:
    body = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(body) > _MAX_RESPONSE_BYTES:
        raise ValueError("response too large")
    return json.loads(body)


def _is_timeout(error: BaseException) -> bool:
    return isinstance(error, (TimeoutError, socket.timeout)) or (
        isinstance(error, URLError) and isinstance(error.reason, (TimeoutError, socket.timeout))
    )


def _parse_updated_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def check_dashboard(
    config: NodeConfig,
    now: datetime,
    *,
    _opener=urlopen,
    _monotonic=time.monotonic,
) -> CheckResult:
    """Check dashboard availability and the freshness of its metrics."""
    started = _monotonic()

    def result(success: bool, category: str, detail: str = "") -> CheckResult:
        return CheckResult(
            target="dashboard",
            success=success,
            category=category,
            checked_at=now,
            duration_ms=max(0, int((_monotonic() - started) * 1000)),
            detail=detail,
        )

    try:
        with _opener(
            Request(f"{config.dashboard_base_url}/healthz", method="GET"),
            timeout=config.request_timeout_seconds,
        ) as response:
            if response.status < 200 or response.status >= 300:
                return result(False, "health_http_error", "health_http_error")
            health = _load_json(response)
    except HTTPError:
        return result(False, "health_http_error", "health_http_error")
    except (TimeoutError, socket.timeout, URLError) as error:
        category = "timeout" if _is_timeout(error) else "unreachable"
        return result(False, category, category)
    except OSError as error:
        category = "timeout" if _is_timeout(error) else "unreachable"
        return result(False, category, category)
    except ValueError:
        return result(False, "health_invalid", "health_invalid")

    if not isinstance(health, dict) or health.get("status") != "ok":
        return result(False, "health_invalid", "health_invalid")

    try:
        with _opener(
            Request(f"{config.dashboard_base_url}/api/metrics", method="GET"),
            timeout=config.request_timeout_seconds,
        ) as response:
            if response.status < 200 or response.status >= 300:
                return result(False, "metrics_http_error", "metrics_http_error")
            payload = _load_json(response)
    except HTTPError:
        return result(False, "metrics_http_error", "metrics_http_error")
    except (TimeoutError, socket.timeout, URLError) as error:
        category = "timeout" if _is_timeout(error) else "unreachable"
        return result(False, category, category)
    except OSError as error:
        category = "timeout" if _is_timeout(error) else "unreachable"
        return result(False, category, category)
    except ValueError:
        return result(False, "metrics_json_invalid", "metrics_json_invalid")

    if not isinstance(payload, dict):
        return result(False, "metrics_json_invalid", "metrics_json_invalid")
    if payload.get("status") != "ok":
        return result(False, "metrics_status_invalid", "metrics_status_invalid")

    updated_at = _parse_updated_at(payload.get("updated_at"))
    stale_after = max(
        2 * config.check_interval_seconds + config.request_timeout_seconds,
        125,
    )
    if updated_at is None or (now - updated_at).total_seconds() > stale_after:
        return result(False, "metrics_stale", "metrics_stale")
    if not isinstance(payload.get("metrics"), dict):
        return result(False, "metrics_shape_invalid", "metrics_shape_invalid")
    return result(True, "ok")
