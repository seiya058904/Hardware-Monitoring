import json
import logging
import os
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch
from quiet_desktop import quiet_desktop

from app import (
    DEFAULT_CONFIG,
    MIN_WINDOW_OPACITY,
    Metrics,
    OverlayApp,
    LanDashboardService,
    clamp_window_position,
    validate_config,
)


def settings_iter(widget):
    for child in widget.winfo_children():
        yield child
        yield from settings_iter(child)


def find_button(widget, text):
    for child in settings_iter(widget):
        if isinstance(child, tk.Button) and child.cget("text") == text:
            return child
    return None


class PositionClampTests(unittest.TestCase):
    def test_inside_position_is_untouched(self):
        self.assertEqual((120, 90), clamp_window_position(120, 90, 340, 330, (0, 0, 1920, 1040)))

    def test_offscreen_position_is_pulled_back(self):
        x, y = clamp_window_position(5000, 5000, 340, 330, (0, 0, 1920, 1040))
        self.assertLessEqual(x + 340, 1920)
        self.assertLessEqual(y + 330, 1040)
        x, y = clamp_window_position(-4000, -4000, 340, 330, (0, 0, 1920, 1040))
        self.assertGreaterEqual(x + 340, 48)
        self.assertGreaterEqual(y, 0)

    def test_degenerate_bounds_are_ignored(self):
        self.assertEqual((7, 9), clamp_window_position(7, 9, 340, 330, (0, 0, 0, 0)))


class OpacityFloorTests(unittest.TestCase):
    def test_opacity_cannot_become_invisible(self):
        for raw in (0.0, 0.1, -1.0):
            self.assertEqual(MIN_WINDOW_OPACITY, validate_config({"window_opacity": raw})[0]["window_opacity"])
        self.assertEqual(1.0, validate_config({"window_opacity": 1.7})[0]["window_opacity"])
        self.assertEqual(0.5, validate_config({"window_opacity": 0.5})[0]["window_opacity"])

    def test_window_position_fields_accept_int_or_none(self):
        ok, _ = validate_config({"window_x": 12, "window_y": None})
        self.assertEqual(12, ok["window_x"])
        self.assertIsNone(ok["window_y"])
        bad, errors = validate_config({"window_x": "12", "window_y": 1.5})
        self.assertEqual(["window_x", "window_y"], errors)


class LanPageTests(unittest.TestCase):
    def setUp(self):
        self.service = LanDashboardService(lambda: {}, lambda: "")
        self.assertTrue(self.service.start(port=0))

    def tearDown(self):
        self.service.stop()

    def test_page_is_selfcontained_and_state_aware(self):
        from urllib.request import urlopen
        with urlopen(f"http://127.0.0.1:{self.service.port}/", timeout=2) as response:
            page = response.read().decode("utf-8")
        for marker in ("id=hero", "id=langBtn", "id=themeBtn", "sample_state", "sample_age_ms",
                       "sample_generation", "error_code", "data-theme", "AbortSignal.timeout"):
            self.assertIn(marker, page)
        self.assertNotIn("src=\"http", page)
        self.assertNotIn("href=\"http", page)
        self.assertNotIn("https://", page)


@unittest.skipUnless(os.name == "nt", "Windows desktop")
class ProcessSnapshotTests(unittest.TestCase):
    def test_current_process_is_listed_and_snapshot_handles_are_released(self):
        import psutil
        application = OverlayApp.__new__(OverlayApp)
        process = psutil.Process()
        self.assertIn(process.name(), application._list_process_names())
        handles = process.num_handles()
        for _ in range(32):
            self.assertIn(process.name(), application._list_process_names())
        self.assertLessEqual(process.num_handles(), handles + 2)


@unittest.skipUnless(os.name == "nt", "Windows desktop")
class SettingsTransactionTests(unittest.TestCase):
    def pump_until(self, predicate, seconds=3):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("Asynchronous settings result did not arrive")

    def build_app(self, directory, **config_overrides):
        class Reader:
            gpu_devices = [("/gpu/a", "GPU A")]
            device_outcomes = {"/cpu": True}

            def read_metrics(self, config):
                return Metrics(cpu_usage="12%")

            def close(self):
                pass

        patchers = [
            patch("app.SensorReader", Reader),
            patch("app.setup_logger", return_value=logging.getLogger("settings-test")),
            patch("app.runtime_data_dir", return_value=Path(directory)),
            patch.object(OverlayApp, "_setup_tray"),
            patch.object(OverlayApp, "_is_autostart_enabled", return_value=False),
            patch.object(OverlayApp, "_set_autostart", return_value=True),
            patch.object(OverlayApp, "_list_process_names", return_value=[]),
        ]
        for patcher in patchers:
            patcher.start()
        self.addCleanup(lambda: [p.stop() for p in patchers])
        config = DEFAULT_CONFIG.copy()
        config.update(config_overrides)
        self.root = tk.Tk()
        quiet = quiet_desktop(self.root)
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        self.root.report_callback_exception = lambda *args: self.fail(f"tk callback error: {args}")
        self.application = OverlayApp(self.root, config)
        self.addCleanup(self.shutdown)

    def shutdown(self):
        try:
            self.application._close_now()
        except Exception:
            pass
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            try:
                self.root.update()
                if not self.root.winfo_exists():
                    break
            except tk.TclError:
                break
            time.sleep(0.02)
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def open_settings(self):
        self.application._toggle_settings()
        self.root.update()
        self.assertFalse(self.root.winfo_ismapped())
        self.assertFalse(self.application.settings_window.winfo_ismapped())
        return self.application.settings_window

    def test_settings_refresh_keeps_window_and_preview_keeps_sampling_config(self):
        with tempfile.TemporaryDirectory() as directory:
            self.build_app(directory)
            window = self.open_settings()
            sampling = self.application._sampling_config
            self.application._settings_working['theme'] = '石墨灰'
            self.application._settings_working['show_cpu_temperature'] = False
            self.application._open_settings_dialog()
            self.root.update()
            self.assertIs(window, self.application.settings_window)
            self.assertIs(sampling, self.application._sampling_config)
            self.assertTrue(sampling['show_cpu_temperature'])
            self.assertFalse(window.winfo_ismapped())

    def test_blocked_process_scan_keeps_tk_responsive_and_cancel_discards_widget_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            self.build_app(directory, fps_target_process="kept.exe")
            entered, release, finished = threading.Event(), threading.Event(), threading.Event()
            self.addCleanup(release.set)
            owners, ticks = [], []

            def blocked_scan():
                owners.append(threading.get_ident())
                entered.set()
                release.wait(3)
                finished.set()
                return ["alive.exe"]

            with patch.object(self.application, "_list_process_names", side_effect=blocked_scan):
                window = self.open_settings()
                self.assertTrue(entered.wait(1))
                self.root.after(0, lambda: ticks.append("responsive"))
                self.root.update()
                self.assertEqual(["responsive"], ticks)
                self.assertFalse(release.is_set())
                # Rebuild and Cancel while the first scan owns a native call.
                self.application._open_settings_dialog()
                self.assertIs(window, self.application.settings_window)
                self.application._cancel_settings()
                release.set()
                self.pump_until(finished.is_set)
                self.root.after(200, lambda: ticks.append("late result"))
                self.pump_until(lambda: len(ticks) == 2)
            self.assertTrue(owners)
            self.assertTrue(all(owner != threading.get_ident() for owner in owners))
            self.assertIsNone(self.application.settings_window)
            self.assertEqual("kept.exe", self.application.config["fps_target_process"])
            self.assertFalse((Path(directory) / "config.json").exists())

    def test_process_scan_error_can_retry_without_losing_selected_target(self):
        with tempfile.TemporaryDirectory() as directory:
            self.build_app(directory, fps_target_process="kept.exe")
            with patch.object(self.application, "_list_process_names", side_effect=[OSError("scan failed"), ["alive.exe"]]):
                window = self.open_settings()
                failed = lambda: any(isinstance(child, tk.Label) and "进程列表读取失败" in child.cget("text") for child in settings_iter(window))
                self.pump_until(failed)
                find_button(window, "刷新列表").invoke()
                self.pump_until(lambda: any(child.winfo_class() == "TCombobox" and "alive.exe" in child.cget("values") for child in settings_iter(window)))
                combos = [child for child in settings_iter(window) if child.winfo_class() == "TCombobox" and "alive.exe" in child.cget("values")]
                self.assertEqual("kept.exe", combos[0].get())
                self.assertIn("kept.exe", combos[0].cget("values"))
                self.assertEqual("kept.exe", self.application._settings_working["fps_target_process"])
            self.application._cancel_settings()
            self.assertEqual("kept.exe", self.application.config["fps_target_process"])

    def test_cancel_restores_config_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            self.build_app(directory)
            self.open_settings()
            working = self.application._settings_working
            working["theme"] = "石墨灰"
            working["window_opacity"] = 0.5
            working["fps_enabled"] = True
            self.application._open_settings_dialog()
            self.root.update()
            self.assertEqual("石墨灰", self.application.config["theme"])
            original = dict(self.application.config)
            original["theme"] = "深色蓝"
            with patch.object(OverlayApp, "_save_config") as save:
                cancel = find_button(self.application.settings_window, "取消")
                cancel.invoke()
                self.root.update()
                save.assert_not_called()
            self.assertEqual("深色蓝", self.application.config["theme"])
            self.assertEqual(0.96, self.application.config["window_opacity"])
            self.assertFalse(self.application.config["fps_enabled"])
            self.assertFalse(list(Path(directory).glob("config.json")))
            self.assertIsNone(self.application._settings_working)
            self.assertIsNone(self.application._settings_original)

    def test_save_persists_once_and_applies_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            self.build_app(directory)
            self.open_settings()
            working = self.application._settings_working
            working["fps_enabled"] = True
            working["fps_target_process"] = "game.exe"
            working["theme"] = "极光绿"
            working["refresh_interval_ms"] = 300
            self.application._open_settings_dialog()
            self.root.update()
            with patch.object(OverlayApp, "_save_config", wraps=self.application._save_config) as save, \
                 patch.object(OverlayApp, "_apply_fps_config", wraps=self.application._apply_fps_config) as apply_fps:
                save_button = find_button(self.application.settings_window, "保存")
                save_button.invoke()
                self.root.update()
                self.assertEqual(1, save.call_count)
                self.assertEqual(1, apply_fps.call_count)
            self.assertEqual("极光绿", self.application.config["theme"])
            self.assertTrue(self.application.config["fps_enabled"])
            self.assertEqual("game.exe", self.application.config["fps_target_process"])
            self.assertEqual(300, self.application._sampling_config['refresh_interval_ms'])
            self.assertEqual('game.exe', self.application._sampling_config['fps_target_process'])
            saved = json.loads((Path(directory) / "config.json").read_text(encoding="utf-8"))
            self.assertEqual("极光绿", saved["theme"])
            self.assertTrue(saved["fps_enabled"])
            # Settings process-list polling can still be pending after Save.
            self.pump_until(lambda: len(self.root.tk.call("after", "info")) == 1)
            self.assertEqual(1, len(self.root.tk.call("after", "info")))

    def test_config_folder_button_opens_runtime_data_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            self.build_app(directory)
            self.open_settings()
            opened = []
            with patch("app.os.startfile", side_effect=lambda path: opened.append(path)):
                button = find_button(self.application.settings_window, "打开数据目录")
                button.invoke()
            self.assertEqual([str(Path(directory).resolve())], [str(Path(p).resolve()) for p in opened])

    def assert_save_failure_is_transactional(self, stage):
        with tempfile.TemporaryDirectory() as directory:
            self.build_app(directory)
            path = Path(directory) / 'config.json'
            original_bytes = b'{"lan_dashboard_enabled":"false"}'
            path.write_bytes(original_bytes)
            original = dict(self.application.config)
            method = {'tmp': 'write_text', 'backup': 'open', 'replace': 'replace'}[stage]
            real_method = getattr(Path, method)

            def fail(target, *args, **kwargs):
                if (stage == 'backup' and target.name.startswith('config.invalid-')) or (stage != 'backup' and target.name == 'config.json.tmp'):
                    raise OSError('synthetic ' + stage + ' failure')
                return real_method(target, *args, **kwargs)

            def prepare():
                self.open_settings()
                self.application._settings_working.update(fps_enabled=True, lan_dashboard_enabled=True, autostart=True)

            with patch.object(self.application, '_apply_fps_config') as fps, \
                 patch.object(self.application, '_apply_lan_dashboard_config') as lan, \
                 patch.object(self.application, '_set_autostart') as startup, \
                 patch('app.messagebox.showerror') as error:
                for finish in ['cancel', 'retry']:
                    prepare()
                    window = self.application.settings_window
                    working = self.application._settings_working
                    with patch.object(Path, method, autospec=True, side_effect=fail):
                        find_button(window, '保存').invoke()
                    self.root.update()
                    self.assertEqual(original_bytes, path.read_bytes())
                    self.assertEqual(original, self.application.config)
                    self.assertEqual(original, self.application._settings_original)
                    self.assertIs(working, self.application._settings_working)
                    self.assertTrue(window.winfo_exists())
                    fps.assert_not_called()
                    lan.assert_not_called()
                    startup.assert_not_called()
                    if finish == 'cancel':
                        find_button(window, '取消').invoke()
                        self.assertEqual(original, self.application.config)
                        self.assertIsNone(self.application._settings_working)
                    else:
                        find_button(window, '保存').invoke()
                self.assertEqual(2, error.call_count)
                fps.assert_called_once_with()
                lan.assert_called_once_with()
                startup.assert_called_once_with(True)
                saved = json.loads(path.read_text(encoding='utf-8'))
                for key in ['fps_enabled', 'lan_dashboard_enabled', 'autostart']:
                    self.assertTrue(saved[key])
                    self.assertTrue(self.application.config[key])
                self.assertIsNone(self.application._settings_working)
                self.assertIsNone(self.application.settings_window)
                backups = list(Path(directory).glob('config.invalid-*.json'))
                self.assertEqual(1, len(backups))
                self.assertEqual(original_bytes, backups[0].read_bytes())

    def test_tmp_write_failure_keeps_settings_retryable_and_cancellable(self):
        self.assert_save_failure_is_transactional('tmp')

    def test_backup_failure_keeps_settings_retryable_and_cancellable(self):
        self.assert_save_failure_is_transactional('backup')

    def test_replace_failure_keeps_settings_retryable_and_cancellable(self):
        self.assert_save_failure_is_transactional('replace')

    def test_minimize_button_respects_minimize_to_tray(self):
        with tempfile.TemporaryDirectory() as directory:
            self.build_app(directory, minimize_to_tray=False)
            with patch.object(OverlayApp, "_hide_to_tray") as hide:
                self.application._minimize_clicked()
                hide.assert_not_called()
            self.assertNotEqual("normal", self.application.root.state())
            self.application.root.deiconify()
            self.application.config["minimize_to_tray"] = True
            with patch.object(OverlayApp, "_hide_to_tray") as hide:
                self.application._minimize_clicked()
                hide.assert_called_once()

    def test_close_protocol_follows_close_action(self):
        with tempfile.TemporaryDirectory() as directory:
            self.build_app(directory, close_action="tray", minimize_to_tray=True)
            with patch.object(OverlayApp, "_close_now") as close_now, \
                 patch.object(OverlayApp, "_hide_to_tray") as hide:
                self.application._on_close_clicked()
                hide.assert_called_once()
                close_now.assert_not_called()
            self.application.config["close_action"] = "exit"
            with patch.object(OverlayApp, "_close_now") as close_now:
                self.application._on_close_clicked()
                close_now.assert_called_once()

    def test_tray_failure_paths_are_never_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            self.build_app(directory, close_action="tray", minimize_to_tray=True)
            application = self.application
            application.tray_service = None
            # Minimize must give visible feedback even when the tray is dead.
            application._minimize_clicked()
            self.root.update()
            application.root.deiconify.assert_called()
            self.assertIn("托盘不可用", application.hint_label.cget("text"))
            # Close with close_action=tray degrades to a graceful exit instead
            # of being a silent no-op.
            with patch.object(OverlayApp, "_close_now") as close_now:
                application._on_close_clicked()
                close_now.assert_called_once()

    def test_tray_hide_hides_window_when_tray_available(self):
        with tempfile.TemporaryDirectory() as directory:
            self.build_app(directory, close_action="tray", minimize_to_tray=True)
            application = self.application

            class FakeTray:
                def show(self):
                    return True

                def close(self):
                    pass

            application.tray_service = FakeTray()
            application._minimize_clicked()
            self.root.update()
            self.assertNotEqual("normal", application.root.state())
            with patch.object(OverlayApp, "_close_now") as close_now:
                application._on_close_clicked()
                close_now.assert_not_called()

    def test_sticky_hint_survives_metric_refresh_until_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            self.build_app(directory)
            application = self.application
            application.tray_service = None
            application._minimize_clicked()
            sticky = application.hint_label.cget("text")
            self.assertIn("托盘不可用", sticky)
            application._update_metrics_loop()
            self.root.update()
            self.assertEqual(sticky, application.hint_label.cget("text"))
            application._rebuild_ui_fast()
            application._update_metrics_loop()
            self.root.update()
            self.assertNotEqual(sticky, application.hint_label.cget("text"))


if __name__ == "__main__":
    unittest.main()
