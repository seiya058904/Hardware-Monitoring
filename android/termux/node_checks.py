"""Stateless network probes for the Termux monitoring node."""

from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import json
import socket
import ssl
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from .node_config import NodeConfig


_MAX_RESPONSE_BYTES = 65536
_CLOUDFLARE_TRACE_BYTES = 2048
_GATEWAY_NEIGHBOR_STATES = {"REACHABLE", "STALE", "DELAY", "PROBE", "PERMANENT"}


@dataclass(frozen=True)
class CheckResult:
    target: str
    success: bool | None
    category: str
    checked_at: datetime
    duration_ms: int
    detail: str = ""


@dataclass(frozen=True)
class CompletedCommand:
    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[list[str]], CompletedCommand]


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _open_dashboard(request: Request, timeout: int):
    return build_opener(_NoRedirectHandler()).open(request, timeout=timeout)


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
    _opener=_open_dashboard,
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


def _gateway_from_routes(output: str) -> str | None:
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[:2] == ["default", "via"]:
            return fields[2]
    return None


def _gateway_result(
    success: bool | None,
    category: str,
    started: float,
    now: datetime,
    monotonic: Callable[[], float],
) -> CheckResult:
    return CheckResult(
        target="gateway",
        success=success,
        category=category,
        checked_at=now,
        duration_ms=max(0, int((monotonic() - started) * 1000)),
        detail=category,
    )


def _is_probe_unavailable(error: BaseException) -> bool:
    return isinstance(error, (FileNotFoundError, PermissionError)) or (
        isinstance(error, OSError) and error.errno in (errno.EACCES, errno.EPERM)
    )


def _command_probe_unavailable(command: CompletedCommand) -> bool:
    detail = f"{command.stdout}\n{command.stderr}".lower()
    return command.returncode in (126, 127) or "permission denied" in detail or "not permitted" in detail


def check_gateway(
    config: NodeConfig,
    command_runner: CommandRunner,
    *,
    _socket_factory=socket.create_connection,
    _now=lambda: datetime.now(timezone.utc),
    _monotonic=time.monotonic,
) -> CheckResult:
    """Check the current default gateway without assuming its address."""
    started = _monotonic()
    now = _now()
    try:
        route = command_runner(["ip", "route"])
    except OSError as error:
        category = "gateway_probe_unavailable" if _is_probe_unavailable(error) else "gateway_unknown"
        return _gateway_result(None, category, started, now, _monotonic)

    if route.returncode != 0 and _command_probe_unavailable(route):
        return _gateway_result(None, "gateway_probe_unavailable", started, now, _monotonic)

    gateway = _gateway_from_routes(route.stdout)
    if gateway is None:
        return _gateway_result(None, "gateway_unknown", started, now, _monotonic)

    try:
        neighbor = command_runner(["ip", "neigh", "show", gateway])
    except OSError as error:
        if _is_probe_unavailable(error):
            return _gateway_result(None, "gateway_probe_unavailable", started, now, _monotonic)
        neighbor = CompletedCommand(1)

    if neighbor.returncode != 0 and _command_probe_unavailable(neighbor):
        return _gateway_result(None, "gateway_probe_unavailable", started, now, _monotonic)

    if any(state in _GATEWAY_NEIGHBOR_STATES for state in neighbor.stdout.split()):
        return _gateway_result(True, "gateway_neighbor", started, now, _monotonic)

    try:
        with _socket_factory((gateway, 53), config.request_timeout_seconds):
            pass
    except ConnectionRefusedError:
        return _gateway_result(True, "gateway_tcp", started, now, _monotonic)
    except (TimeoutError, socket.timeout):
        return _gateway_result(None, "gateway_unverified", started, now, _monotonic)
    except OSError as error:
        if _is_probe_unavailable(error):
            return _gateway_result(None, "gateway_probe_unavailable", started, now, _monotonic)
        if error.errno in (errno.EHOSTUNREACH, errno.ENETUNREACH):
            return _gateway_result(False, "gateway_unreachable", started, now, _monotonic)
        return _gateway_result(None, "gateway_unverified", started, now, _monotonic)
    return _gateway_result(True, "gateway_tcp", started, now, _monotonic)


def _open_internet(request: Request, timeout: int, context: ssl.SSLContext):
    return build_opener(HTTPSHandler(context=context), _NoRedirectHandler()).open(request, timeout=timeout)


def _internet_error_category(error: BaseException) -> str:
    if isinstance(error, HTTPError):
        return "redirect" if 300 <= error.code < 400 else "http_error"
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(reason, ssl.SSLError):
        return "tls_error"
    if isinstance(reason, socket.gaierror):
        return "dns_error"
    return "unreachable"


def check_internet(
    config: NodeConfig,
    *,
    _opener=_open_internet,
    _now=lambda: datetime.now(timezone.utc),
    _monotonic=time.monotonic,
) -> CheckResult:
    """Confirm public HTTPS reachability with the two approved endpoints."""
    started = _monotonic()
    now = _now()
    failures = []
    context = ssl.create_default_context()

    for index, url in enumerate(config.internet_probe_urls):
        try:
            with _opener(Request(url, method="GET"), config.request_timeout_seconds, context) as response:
                if index == 0:
                    valid = response.status == 204
                    failure = "http_error"
                else:
                    valid = response.status == 200 and b"visit_scheme=https" in response.read(_CLOUDFLARE_TRACE_BYTES)
                    failure = "trace_invalid" if response.status == 200 else "http_error"
        except (HTTPError, URLError, OSError, ssl.SSLError) as error:
            failures.append(_internet_error_category(error))
            continue
        if valid:
            return CheckResult(
                target="internet",
                success=True,
                category="ok",
                checked_at=now,
                duration_ms=max(0, int((_monotonic() - started) * 1000)),
            )
        failures.append(failure)

    return CheckResult(
        target="internet",
        success=False,
        category="internet_failed",
        checked_at=now,
        duration_ms=max(0, int((_monotonic() - started) * 1000)),
        detail=",".join(failures),
    )
