import ctypes
import ctypes.wintypes
import logging
import os
import re
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app
from quiet_desktop import quiet_desktop


class ApiFunction:
    def __init__(self, callback):
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


class MonitorWorkareaTests(unittest.TestCase):
    def query(self, point, workarea, monitor=1, success=True):
        calls = []

        def monitor_from_point(value, flags):
            calls.append((value.x, value.y, flags))
            return monitor

        def get_monitor_info(handle, pointer):
            self.assertEqual(monitor, handle)
            info = pointer._obj
            self.assertEqual(ctypes.sizeof(info), info.cbSize)
            info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom = workarea
            return success

        user32 = SimpleNamespace(
            MonitorFromPoint=ApiFunction(monitor_from_point),
            GetMonitorInfoW=ApiFunction(get_monitor_info),
        )
        with patch('app.ctypes.windll', SimpleNamespace(user32=user32), create=True):
            result = app.OverlayApp.__new__(app.OverlayApp)._monitor_workarea(*point)
        return result, calls, user32

    def test_primary_and_negative_monitor_coordinates_are_preserved(self):
        for point, area in (
            ((80, 80), (0, 0, 1920, 1040)),
            ((-1800, 100), (-1920, 0, 0, 1040)),
            ((100, -900), (0, -1080, 1920, -40)),
        ):
            with self.subTest(point=point):
                result, calls, _ = self.query(point, area)
                self.assertEqual(area, result)
                self.assertEqual([(*point, 2)], calls)

    def test_monitor_abi_uses_pointer_sized_handles_and_typed_arguments(self):
        handle = (1 << 40) + 7 if ctypes.sizeof(ctypes.c_void_p) == 8 else 7
        result, _, api = self.query((0, 0), (0, 0, 1920, 1040), monitor=handle)
        self.assertIsNotNone(result)
        self.assertEqual([ctypes.wintypes.POINT, ctypes.wintypes.DWORD], api.MonitorFromPoint.argtypes)
        self.assertIs(ctypes.wintypes.HANDLE, api.MonitorFromPoint.restype)
        self.assertEqual([ctypes.wintypes.HANDLE, ctypes.POINTER(app.MONITORINFO)], api.GetMonitorInfoW.argtypes)
        self.assertIs(ctypes.wintypes.BOOL, api.GetMonitorInfoW.restype)

    def test_failed_or_invalid_api_results_have_no_workarea(self):
        for options in ({'monitor': 0}, {'success': False}):
            with self.subTest(options=options):
                self.assertIsNone(self.query((80, 80), (0, 0, 1920, 1040), **options)[0])
        self.assertIsNone(self.query((80, 80), (0, 0, 0, 0))[0])
        def unavailable(*_):
            raise OSError('unavailable')

        api = SimpleNamespace(MonitorFromPoint=ApiFunction(unavailable), GetMonitorInfoW=ApiFunction(lambda *_: False))
        with patch('app.ctypes.windll', SimpleNamespace(user32=api), create=True):
            self.assertIsNone(app.OverlayApp.__new__(app.OverlayApp)._monitor_workarea(80, 80))

    @unittest.skipUnless(os.name == 'nt', 'Windows ABI')
    def test_monitorinfo_matches_win32_layout(self):
        self.assertEqual(40, ctypes.sizeof(app.MONITORINFO))
        self.assertEqual([0, 4, 20, 36], [getattr(app.MONITORINFO, field).offset for field in ('cbSize', 'rcMonitor', 'rcWork', 'dwFlags')])

    @unittest.skipUnless(os.name == 'nt', 'Windows monitor API')
    def test_real_primary_workarea_matches_system_workarea(self):
        user32 = ctypes.windll.user32
        spi = user32.SystemParametersInfoW
        spi.argtypes = [ctypes.wintypes.UINT, ctypes.wintypes.UINT, ctypes.c_void_p, ctypes.wintypes.UINT]
        spi.restype = ctypes.wintypes.BOOL
        rect = ctypes.wintypes.RECT()
        self.assertTrue(spi(0x30, 0, ctypes.byref(rect), 0))  # SPI_GETWORKAREA
        expected = (rect.left, rect.top, rect.right, rect.bottom)
        self.assertEqual(expected, app.OverlayApp.__new__(app.OverlayApp)._monitor_workarea(0, 0))


@unittest.skipUnless(os.name == 'nt', 'Windows desktop')
class WorkareaLayoutTests(unittest.TestCase):
    def build_app(self, directory, point, area, dpi):
        class Reader:
            gpu_devices = []
            device_outcomes = {}

            def read_metrics(self, config):
                return app.Metrics(cpu_usage='12%')

            def close(self):
                pass

        patches = [
            patch('app.SensorReader', Reader),
            patch('app.setup_logger', return_value=logging.getLogger('workarea-test')),
            patch('app.runtime_data_dir', return_value=Path(directory)),
            patch.object(app.OverlayApp, '_setup_tray'),
            patch.object(app.OverlayApp, '_is_autostart_enabled', return_value=False),
            patch.object(app.OverlayApp, '_set_autostart', return_value=True),
            patch.object(app.OverlayApp, '_list_process_names', return_value=[]),
            patch('app.virtual_screen_bounds', return_value=area or (0, 0, 1920, 1040)),
        ]
        for patcher in patches:
            patcher.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(patches)])
        config = app.DEFAULT_CONFIG.copy()
        config.update({key: True for key in config if key.startswith('show_')})
        config.update(font_scale=1.5, window_x=point[0], window_y=point[1])
        self.root = tk.Tk()
        quiet = quiet_desktop(self.root)
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.root.winfo_fpixels = lambda _: 96 * dpi
        self.root.tk.call('tk', 'scaling', dpi * 96 / 72)
        self.geometry_calls = []
        geometry = self.root.geometry

        def remember(value=None):
            if value is not None:
                self.geometry_calls.append(value)
            return geometry(value)

        self.root.geometry = remember
        rows = app.OverlayApp._build_rows
        self.tight_passes = []

        def measure(application, theme, scale, density, compact, groups, english, text, tight):
            self.tight_passes.append(tight)
            return rows(application, theme, scale, density, compact, groups, english, text, tight)

        with patch.object(app.OverlayApp, '_monitor_workarea', return_value=area) as query, patch.object(app.OverlayApp, '_build_rows', measure):
            self.application = app.OverlayApp(self.root, config)
            self.monitor_query = query.call_args
        self.addCleanup(self.shutdown)
        self.assertFalse(self.root.winfo_ismapped())

    def shutdown(self):
        self.application._close_now()
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            try:
                self.root.update()
                if not self.root.winfo_exists():
                    break
            except tk.TclError:
                break
            time.sleep(.01)
        self.assertFalse(self.errors, self.errors)

    def final_geometry(self):
        return tuple(map(int, re.fullmatch(r'(\d+)x(\d+)\+(-?\d+)\+(-?\d+)', self.geometry_calls[-1]).groups()))

    def test_large_metrics_compact_and_clamp_inside_primary_workarea(self):
        with tempfile.TemporaryDirectory() as directory:
            self.build_app(directory, (1700, 700), (0, 0, 1920, 1040), 2.0)
            width, height, x, y = self.final_geometry()
            self.assertEqual([False, True], self.tight_passes)
            self.assertGreater(len(self.application.labels), 20)
            self.assertLessEqual(x + width, 1920)
            self.assertLessEqual(y + height, 1040)
            self.assertLessEqual(height, 1016)

    def test_saved_left_and_upper_positions_select_negative_monitor_before_layout(self):
        for point, area in (
            ((-1400, 400), (-1920, 0, 0, 800)),
            ((300, -700), (0, -1080, 1920, -40)),
        ):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as directory:
                try:
                    self.build_app(directory, point, area, 1.5)
                    # _setup_window clamps its initial 340x330 before querying.
                    expected = app.clamp_window_position(*point, 340, 330, area)
                    self.assertEqual(expected, self.monitor_query.args)
                    width, height, x, y = self.final_geometry()
                    self.assertGreaterEqual(x, area[0])
                    self.assertGreaterEqual(y, area[1])
                    self.assertLessEqual(x + width, area[2])
                    self.assertLessEqual(y + height, area[3])
                finally:
                    self.doCleanups()

    def test_api_failure_preserves_unconstrained_fallback_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            self.build_app(directory, (80, 80), None, 2.0)
            self.assertEqual([False], self.tight_passes)
            width, height, _, _ = self.final_geometry()
            self.assertGreaterEqual(width, 320)
            self.assertGreaterEqual(height, 220)


if __name__ == '__main__':
    unittest.main()
