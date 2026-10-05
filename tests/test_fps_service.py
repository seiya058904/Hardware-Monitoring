import logging
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app import FpsService, OverlayApp
from service_runtime import ServiceRuntime


class BlockingPipe:
    def __init__(self) -> None:
        self.released = threading.Event()

    def readline(self) -> str:
        self.released.wait()
        return ""


class FakeProcess:
    def __init__(self) -> None:
        self.stdout = BlockingPipe()
        self.stderr = None
        self.terminated = False

    def poll(self):
        return None if not self.terminated else 0

    def terminate(self) -> None:
        self.terminated = True
        self.stdout.released.set()

    def wait(self, timeout=None) -> None:
        return 0

    def kill(self) -> None:
        self.terminate()


class FpsServiceTest(unittest.TestCase):
    def test_same_target_retries_failed_capture_once_and_keeps_healthy_worker(self):
        service = FpsService(Path('.'), Path('.'), logging.getLogger('fps-retry'))
        started = threading.Event()
        healthy = FakeProcess()
        calls = []

        def spawn():
            calls.append(service._spawn_context.target)
            if len(calls) == 1:
                return None
            started.set()
            return healthy

        service._spawn = spawn
        runtime = ServiceRuntime(service.close)
        application = OverlayApp.__new__(OverlayApp)
        application.config = dict(fps_enabled=True, fps_target_process='game.exe')
        application.logger = logging.getLogger('fps-retry-app')
        application.fps_service = service
        application.service_runtime = runtime
        application._requested_fps_config = None
        try:
            with patch.object(service, '_resolve_presentmon_path', return_value=Path('PresentMon.exe')):
                application._apply_fps_config()
                deadline = time.monotonic() + 2
                while service.snapshot()['error_code'] != 'fps_capture_failed' and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual('fps_capture_failed', service.snapshot()['error_code'])
                application._apply_fps_config()
                self.assertTrue(started.wait(1), 'same target must spawn a real recovery worker')
                self.assertEqual(['game.exe', 'game.exe'], calls)
                self.assertEqual('', service.snapshot()['error_code'])
                application._apply_fps_config()
                # Drain the service queue behind any accidental restart.
                drained = threading.Event()
                runtime.submit('barrier', drained.set)
                self.assertTrue(drained.wait(1))
                self.assertEqual(2, len(calls))
                self.assertFalse(healthy.terminated)
        finally:
            runtime.stop()
            runtime.thread.join(3)
        self.assertFalse(runtime.thread.is_alive())
        self.assertTrue(healthy.terminated)

    def test_same_target_retries_normally_terminated_worker(self):
        service = FpsService(Path('.'), Path('.'), logging.getLogger('fps-ended'))
        service._spawn = lambda: None
        try:
            with patch.object(service, '_resolve_presentmon_path', return_value=Path('PresentMon.exe')):
                service.configure(True, 'game.exe')
                service._worker_thread.join(1)
                service._error_code = ''  # A normal exit can also leave no worker.
                with patch.object(service, 'restart', wraps=service.restart) as restart:
                    service.configure(True, 'game.exe')
                    restart.assert_called_once()
        finally:
            service.close()

    def test_target_switch_discards_late_failure_from_previous_worker(self):
        service = FpsService(Path('.'), Path('.'), logging.getLogger('fps-target-switch'))
        entered, released = threading.Event(), threading.Event()
        healthy = FakeProcess()
        targets = []

        def spawn():
            target = service._spawn_context.target
            targets.append(target)
            if target == 'old.exe':
                entered.set()
                released.wait(5)
                return None
            return healthy

        service._spawn = spawn
        try:
            with patch.object(service, '_resolve_presentmon_path', return_value=Path('PresentMon.exe')):
                service.configure(True, 'old.exe')
                self.assertTrue(entered.wait(1))
                service.configure(True, 'new.exe')
                released.set()
                deadline = time.monotonic() + 1
                while any(worker.is_alive() for worker in service._workers[:-1]) and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(['old.exe', 'new.exe'], targets)
                self.assertEqual('new.exe', service.snapshot()['target_process'])
                self.assertEqual('', service.snapshot()['error_code'])
                self.assertEqual('--', service.snapshot()['fps'])
                self.assertFalse(healthy.terminated)
        finally:
            released.set()
            service.close()

    def test_failed_capture_clears_pending_percentile_and_stays_unavailable(self):
        service = FpsService(Path('.'), Path('.'), logging.getLogger('fps-exit'))
        class Capture:
            selected = (1, 2, 'a')
            def consume(self, line): return 60, 1000/60, False
        service._enabled = service._presentmon_available = True
        service._target_process = 'game.exe'
        service._spawn = lambda: subprocess.Popen(
            [sys.executable, '-c', "for _ in range(60): print('frame', flush=True)\nraise SystemExit(1)"],
            stdout=subprocess.PIPE, text=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        service._capture = Capture()
        service._run_worker(service._generation)
        snapshot = service.snapshot()
        self.assertEqual('不可用', snapshot['fps'])
        self.assertEqual('不可用', snapshot['fps_low_1'])
        self.assertEqual('fps_capture_failed', snapshot['error_code'])
        with patch('app.time.monotonic', return_value=time.monotonic()+5):
            self.assertEqual('不可用', service.snapshot()['fps'])

    def test_percentile_is_computed_on_view_and_never_leaks_after_disable(self):
        service = FpsService(Path('.'), Path('.'), logging.getLogger('fps-view'))
        class Capture:
            selected = (1, 2, 'a')
            def consume(self, line): return 60, 1000/60, False
        service._capture = Capture()
        service._enabled = service._presentmon_available = True
        service._target_process = 'game.exe'
        with patch.object(service, '_calc_low_1_text', wraps=service._calc_low_1_text) as calculate:
            for _ in range(1000): service._consume_line('frame')
            calculate.assert_not_called()
            self.assertEqual('60', service.snapshot()['fps_low_1'])
            self.assertEqual('60', service.get_low_display_text())
            calculate.assert_called_once()
            service._consume_line('frame')
            service.configure(False, '')
            self.assertEqual('关闭', service.get_low_display_text())
            calculate.assert_called_once()

    def test_restart_does_not_leave_new_process_untracked_when_old_spawn_returns_late(self) -> None:
        service = FpsService(Path("."), Path("."), logging.getLogger("test_fps_service"))
        service._enabled = True
        service._target_process = "game.exe"
        service._presentmon_available = True
        first_spawn_started = threading.Event()
        allow_first_spawn = threading.Event()
        processes = []

        def spawn():
            if not first_spawn_started.is_set():
                first_spawn_started.set()
                allow_first_spawn.wait(2)
            proc = FakeProcess()
            processes.append(proc)
            return proc

        service._spawn = spawn
        service.restart()
        self.assertTrue(first_spawn_started.wait(1))
        service.restart()
        allow_first_spawn.set()
        deadline = time.monotonic() + 1
        while len(processes) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(2, len(processes))
        service.stop()
        self.assertTrue(all(proc.terminated for proc in processes))


if __name__ == "__main__":
    unittest.main()
