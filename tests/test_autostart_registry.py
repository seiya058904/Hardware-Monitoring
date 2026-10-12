import sys
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import app


class AutostartRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = MagicMock()
        self.registry.REG_SZ = 1
        self.application = app.OverlayApp.__new__(app.OverlayApp)

    def query(self, values=None, error=None):
        def read(key, name):
            if name not in values:
                raise FileNotFoundError(name)
            return values[name]
        self.registry.OpenKey.side_effect = error
        self.registry.QueryValueEx.side_effect = read
        with patch.object(app, "winreg", self.registry):
            return self.application._query_autostart_state()

    def test_missing_run_key_is_disabled_but_access_failure_is_unknown(self):
        self.assertIs(self.query({}, FileNotFoundError()), False)
        self.assertIsNone(self.query({}, PermissionError()))
        self.assertIsNone(self.query({}, OSError("I/O")))

    def test_invalid_values_do_not_claim_enabled(self):
        for value in [("", 1), ('"C:\\missing\\Hardware Monitoring.exe"', 1), ("ignored", 4)]:
            with self.subTest(value=value):
                self.assertIs(self.query({app.AUTOSTART_VALUE_NAME: value}), False)

    def test_current_source_command_is_valid_and_extra_arguments_are_rejected(self):
        command = f'"{sys.executable}" "{Path(app.__file__).resolve()}"'
        self.assertIs(self.query({app.AUTOSTART_VALUE_NAME: (command, 1)}), True)
        self.assertIs(self.query({app.AUTOSTART_VALUE_NAME: (command + " --wrong", 1)}), False)
        relative = f'"{sys.executable}" "app.py"'
        self.assertIs(self.query({app.AUTOSTART_VALUE_NAME: (relative, 1)}), False)

    def test_current_and_legacy_packaged_commands_require_real_files(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, value_name in [("Hardware Monitoring.exe", app.AUTOSTART_VALUE_NAME),
                                     ("HardwareMonitorMini.exe", app.LEGACY_AUTOSTART_VALUE_NAME)]:
                executable = Path(directory) / name
                shutil.copyfile(sys.executable, executable)
                self.assertIs(self.query({value_name: (f'"{executable}"', 1)}), True)
                self.assertIs(self.query({value_name: (f'"{executable}" --wrong', 1)}), False)
                executable.write_bytes(b"not a Windows executable")
                self.assertIs(self.query({value_name: (f'"{executable}"', 1)}), False)

    def test_read_denied_does_not_claim_disabled(self):
        self.registry.QueryValueEx.side_effect = PermissionError()
        with patch.object(app, "winreg", self.registry):
            self.assertIsNone(self.application._query_autostart_state())

    def test_file_inspection_failure_is_unknown(self):
        command = f'"{sys.executable}" "{Path(app.__file__).resolve()}"'
        for error in (PermissionError("denied"), OSError("sharing violation")):
            with self.subTest(error=error), patch.object(Path, "stat", side_effect=error):
                self.assertIsNone(self.query({app.AUTOSTART_VALUE_NAME: (command, 1)}))

    def test_binary_inspection_failure_is_unknown_unless_invalid(self):
        command = f'"{sys.executable}" "{Path(app.__file__).resolve()}"'
        kernel = MagicMock()
        kernel.GetBinaryTypeW.return_value = 0
        for code, expected in ((5, None), (32, None), (193, False), (2, False)):
            with self.subTest(code=code), patch.object(app.ctypes, "WinDLL", return_value=kernel), patch.object(app.ctypes, "get_last_error", return_value=code):
                self.assertIs(self.query({app.AUTOSTART_VALUE_NAME: (command, 1)}), expected)

    def test_valid_legacy_command_overrides_unknown_current_command(self):
        with patch.object(self.application, "_valid_autostart_command", side_effect=[None, True]):
            self.assertIs(self.query({app.AUTOSTART_VALUE_NAME: ("current", 1), app.LEGACY_AUTOSTART_VALUE_NAME: ("legacy", 1)}), True)
        with patch.object(self.application, "_valid_autostart_command", side_effect=[None, False]):
            self.assertIsNone(self.query({app.AUTOSTART_VALUE_NAME: ("current", 1), app.LEGACY_AUTOSTART_VALUE_NAME: ("legacy", 1)}))

    def test_write_denied_is_reported_without_real_registry_changes(self):
        self.registry.OpenKey.side_effect = PermissionError()
        with patch.object(app, "winreg", self.registry):
            self.assertFalse(self.application._set_autostart(True))
            self.assertFalse(self.application._set_autostart(False))
        self.registry.SetValueEx.assert_not_called()


if __name__ == "__main__":
    unittest.main()
