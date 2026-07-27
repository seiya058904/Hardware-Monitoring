import logging
import threading
import time
import unittest
from pathlib import Path

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
