import logging
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app import FpsService


class BlockingPipe:
    def __init__(self) -> None:
        self.released = threading.Event()

    def readline(self) -> str:
        self.released.wait(2)
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
