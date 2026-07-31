"""Validated configuration for the Termux monitoring node."""

from dataclasses import dataclass, fields
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


DEFAULT_PROBE_URLS = (
    "https://connectivitycheck.gstatic.com/generate_204",
    "https://www.cloudflare.com/cdn-cgi/trace",
)


def _validate_url(value: str, allowed_schemes: set[str], field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a URL")

    try:
        parts = urlsplit(value.strip())
        hostname = parts.hostname
        _ = parts.port
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid URL") from error

    if (
        parts.scheme.lower() not in allowed_schemes
        or not parts.netloc
        or not hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise ValueError(f"{field_name} must be a URL without credentials, query, or fragment")

    return urlunsplit((parts.scheme.lower(), parts.netloc, parts.path.rstrip("/"), "", ""))


def validate_base_url(value: str) -> str:
    """Return a normalized HTTP(S) dashboard base URL without credentials."""
    return _validate_url(value, {"http", "https"}, "dashboard_base_url")


def _positive_int(value: object, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


@dataclass(frozen=True)
class NodeConfig:
    dashboard_base_url: str = "http://192.168.2.249:8765"
    check_interval_seconds: int = 60
    request_timeout_seconds: int = 5
    failure_threshold: int = 3
    recovery_threshold: int = 2
    reminder_interval_seconds: int = 3600
    startup_delay_seconds: int = 30
    log_max_bytes: int = 1048576
    log_backup_count: int = 5
    check_gateway: bool = True
    check_internet: bool = True
    internet_probe_urls: tuple[str, str] = DEFAULT_PROBE_URLS

    def __post_init__(self) -> None:
        object.__setattr__(self, "dashboard_base_url", validate_base_url(self.dashboard_base_url))
        for field_name in (
            "check_interval_seconds",
            "request_timeout_seconds",
            "failure_threshold",
            "recovery_threshold",
            "reminder_interval_seconds",
            "startup_delay_seconds",
            "log_max_bytes",
            "log_backup_count",
        ):
            _positive_int(getattr(self, field_name), field_name)
        for field_name in ("check_gateway", "check_internet"):
            if type(getattr(self, field_name)) is not bool:
                raise ValueError(f"{field_name} must be a boolean")

        urls = self.internet_probe_urls
        if not isinstance(urls, tuple):
            raise ValueError("internet_probe_urls must be a list of URLs")
        if self.check_internet and len(urls) != 2:
            raise ValueError("internet_probe_urls must contain exactly two URLs")
        if not self.check_internet and urls:
            raise ValueError("internet_probe_urls must be empty when check_internet is false")
        normalized_urls = tuple(_validate_url(url, {"https"}, "internet_probe_urls") for url in urls)
        if self.check_internet and normalized_urls != DEFAULT_PROBE_URLS:
            raise ValueError("internet_probe_urls must use the approved probe URLs")
        object.__setattr__(
            self,
            "internet_probe_urls",
            normalized_urls,
        )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("configuration contains duplicate keys")
        result[key] = value
    return result


def load_config(path: Path) -> NodeConfig:
    """Load one complete JSON configuration file without accepting unknown keys."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("configuration must be valid JSON") from error

    if not isinstance(data, dict):
        raise ValueError("configuration must be a JSON object")

    expected_keys = {field.name for field in fields(NodeConfig)}
    if set(data) != expected_keys:
        raise ValueError("configuration keys do not match the required schema")
    if not isinstance(data["internet_probe_urls"], list):
        raise ValueError("internet_probe_urls must be a list of URLs")

    return NodeConfig(**(data | {"internet_probe_urls": tuple(data["internet_probe_urls"])}))
