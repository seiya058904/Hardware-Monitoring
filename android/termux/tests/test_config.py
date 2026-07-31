import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from android.termux.node_config import NodeConfig, load_config, validate_base_url


DEFAULT_VALUES = {
    "dashboard_base_url": "http://192.168.2.249:8765",
    "check_interval_seconds": 60,
    "request_timeout_seconds": 5,
    "failure_threshold": 3,
    "recovery_threshold": 2,
    "reminder_interval_seconds": 3600,
    "startup_delay_seconds": 30,
    "log_max_bytes": 1048576,
    "log_backup_count": 5,
    "check_gateway": True,
    "check_internet": True,
    "internet_probe_urls": [
        "https://connectivitycheck.gstatic.com/generate_204",
        "https://www.cloudflare.com/cdn-cgi/trace",
    ],
}


class ConfigTests(unittest.TestCase):
    def load_values(self, values):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(values), encoding="utf-8")
            return load_config(path)

    def test_example_has_exact_approved_defaults(self):
        path = Path(__file__).parents[1] / "config.example.json"

        config = load_config(path)

        self.assertEqual(
            config,
            NodeConfig(
                dashboard_base_url="http://192.168.2.249:8765",
                check_interval_seconds=60,
                request_timeout_seconds=5,
                failure_threshold=3,
                recovery_threshold=2,
                reminder_interval_seconds=3600,
                startup_delay_seconds=30,
                log_max_bytes=1048576,
                log_backup_count=5,
                check_gateway=True,
                check_internet=True,
                internet_probe_urls=(
                    "https://connectivitycheck.gstatic.com/generate_204",
                    "https://www.cloudflare.com/cdn-cgi/trace",
                ),
            ),
        )

    def test_config_is_immutable(self):
        config = self.load_values(DEFAULT_VALUES)

        with self.assertRaises(FrozenInstanceError):
            config.check_gateway = False

    def test_rejects_non_positive_or_boolean_numeric_values(self):
        for field, value in (
            ("check_interval_seconds", 0),
            ("request_timeout_seconds", -1),
            ("failure_threshold", True),
            ("recovery_threshold", 1.5),
            ("reminder_interval_seconds", 0),
            ("startup_delay_seconds", -1),
            ("log_max_bytes", 0),
            ("log_backup_count", False),
        ):
            with self.subTest(field=field, value=value):
                values = DEFAULT_VALUES | {field: value}

                with self.assertRaises(ValueError):
                    self.load_values(values)

    def test_rejects_non_http_dashboard_urls(self):
        for value in ("ftp://dashboard.example", "dashboard.example", "https:///healthz"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_base_url(value)

    def test_rejects_credentials_without_echoing_them(self):
        secret = "not-for-logs"
        values = DEFAULT_VALUES | {
            "dashboard_base_url": f"http://user:{secret}@dashboard.example"
        }

        with self.assertRaises(ValueError) as raised:
            self.load_values(values)

        self.assertNotIn(secret, str(raised.exception))

    def test_requires_exactly_two_https_probe_urls_when_enabled(self):
        for urls in (
            [],
            ["https://one.example"],
            ["https://one.example", "https://two.example", "https://three.example"],
            ["http://one.example", "https://two.example"],
        ):
            with self.subTest(urls=urls):
                values = DEFAULT_VALUES | {"internet_probe_urls": urls}

                with self.assertRaises(ValueError):
                    self.load_values(values)

    def test_rejects_unapproved_or_reordered_probe_urls(self):
        for urls in (
            ["https://private.example/probe", "https://www.cloudflare.com/cdn-cgi/trace"],
            ["https://www.cloudflare.com/cdn-cgi/trace", "https://connectivitycheck.gstatic.com/generate_204"],
        ):
            with self.subTest(urls=urls):
                with self.assertRaises(ValueError):
                    self.load_values(DEFAULT_VALUES | {"internet_probe_urls": urls})

    def test_allows_empty_probe_urls_only_when_internet_check_is_disabled(self):
        config = self.load_values(
            DEFAULT_VALUES | {"check_internet": False, "internet_probe_urls": []}
        )

        self.assertEqual(config.internet_probe_urls, ())

    def test_rejects_unknown_keys_and_non_boolean_flags(self):
        with self.assertRaises(ValueError):
            self.load_values(DEFAULT_VALUES | {"unexpected": "value"})

        with self.assertRaises(ValueError):
            self.load_values(DEFAULT_VALUES | {"check_gateway": 1})


if __name__ == "__main__":
    unittest.main()
