import logging
import os
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch
from app import DEFAULT_CONFIG, Metrics, OverlayApp, TrayIconService, configure_tray_abi


@unittest.skipUnless(os.name == 'nt', 'Windows desktop')
class DesktopTests(unittest.TestCase):
    def test_settings_offline_target_language_and_reset_cancel(self):
        class Reader:
            gpu_devices = [('/gpu/a', 'GPU A')]
            device_outcomes = {'/cpu': True}
            def read_metrics(self, config): return Metrics(cpu_usage='12%', temp_hint='temperatures_unavailable')
            def close(self): pass
        with tempfile.TemporaryDirectory() as directory, patch('app.SensorReader', Reader), patch('app.setup_logger', return_value=logging.getLogger('ui-test')), patch('app.runtime_data_dir', return_value=Path(directory)), patch.object(OverlayApp, '_setup_tray'), patch.object(OverlayApp, '_is_autostart_enabled', return_value=False), patch.object(OverlayApp, '_set_autostart', return_value=True), patch.object(OverlayApp, '_list_process_names', return_value=[]):
            root = tk.Tk()
            errors = []
            root.report_callback_exception = lambda *args: errors.append(args)
            config = DEFAULT_CONFIG.copy()
            config['fps_target_process'] = 'offline-game.exe'
            config['gpu_device_id'] = '/gpu/a'
            application = OverlayApp(root, config)
            try:
                root.update()
                application._toggle_diagnostics()
                for language in ('en', 'zh', 'en'):
                    application.config['ui_language'] = language
                    application._update_metrics_loop()
                    root.update()
                    self.assertEqual('Sensor diagnostics' if language == 'en' else '传感器诊断', application.diag_window.title())
                application._toggle_settings()
                root.update()
                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)
                reset = next(widget for widget in descendants(application.settings_window) if isinstance(widget, tk.Button) and widget.cget('text') == 'Reset All')
                original = dict(application.config)
                with patch('app.messagebox.askyesno', return_value=False) as confirm:
                    reset.invoke()
                    confirm.assert_called_once()
                self.assertEqual(original, application.config)
                self.assertEqual('offline-game.exe', application.config['fps_target_process'])
                save = next(widget for widget in descendants(application.settings_window) if isinstance(widget, tk.Button) and widget.cget('text') == 'Save')
                save.invoke()
                root.update()
                self.assertEqual('offline-game.exe', application.config['fps_target_process'])
                self.assertEqual('/gpu/a', application.config['gpu_device_id'])
                self.assertEqual(1, len(root.tk.call('after', 'info')))
                self.assertFalse(errors, errors)
            finally:
                application._close_now()
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    try: root.update()
                    except tk.TclError: break
                    try:
                        if not root.winfo_exists(): break
                    except tk.TclError: break
                    time.sleep(.02)

    def test_tray_failure_does_not_report_success(self):
        configure_tray_abi()
        tray = TrayIconService('test', None, lambda: None, lambda: None)
        tray._enabled = True
        tray._nid = TrayIconService.NOTIFYICONDATAW()
        with patch('app.ctypes.windll.shell32.Shell_NotifyIconW', return_value=0):
            self.assertFalse(tray.show())
            self.assertFalse(tray._visible)
        with patch('app.ctypes.windll.shell32.Shell_NotifyIconW', return_value=1) as add:
            self.assertTrue(tray.show())
            self.assertTrue(tray.show())
            self.assertEqual(1, add.call_count)
