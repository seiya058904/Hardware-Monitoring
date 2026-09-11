import threading
import time
import unittest
from app import Metrics
from sensor_runtime import SensorRuntime


class SamplingTests(unittest.TestCase):
    def test_blocked_shutdown_does_not_close_or_publish_from_other_thread(self):
        entered, release, closed = threading.Event(), threading.Event(), threading.Event()
        owners = []
        class Reader:
            def __init__(self): owners.append(threading.get_ident())
            def read_metrics(self, config):
                entered.set()
                release.wait(2)
                return Metrics(cpu_usage='99%')
            def close(self):
                owners.append(threading.get_ident())
                closed.set()
        runtime = SensorRuntime(Reader, lambda: {'refresh_interval_ms': 300}, Metrics)
        runtime.start()
        self.assertTrue(entered.wait(1))
        runtime.stop()
        self.assertFalse(closed.is_set())
        self.assertEqual('stopping', runtime.snapshot()['sample_state'])
        release.set()
        runtime.thread.join(2)
        self.assertTrue(closed.is_set())
        self.assertEqual(owners[0], owners[1])
        self.assertEqual(0, runtime.snapshot()['sample_generation'])

    def test_stale_is_derived_at_single_snapshot_boundary(self):
        runtime = SensorRuntime(None, lambda: {'refresh_interval_ms': 1000}, Metrics, monotonic=lambda: 10)
        runtime.last_success_monotonic = 1
        runtime.state = 'ok'
        self.assertEqual('stale', runtime.snapshot()['sample_state'])
        self.assertEqual(9000, runtime.snapshot()['sample_age_ms'])

    def test_rebuild_backoff_survives_reinitialization(self):
        now = [0]
        class Reader:
            device_outcomes = {'gpu': False}
            def close(self): pass
            def _init_lhm(self): pass
        runtime = SensorRuntime(None, lambda: {}, Metrics, monotonic=lambda: now[0])
        reader = Reader()
        for _ in range(3): runtime._recover_devices(reader)
        now[0] = 30
        runtime._recover_devices(reader)
        self.assertEqual(60, runtime.devices['gpu']['delay'])
        now[0] = 90
        runtime._recover_devices(reader)
        self.assertEqual(120, runtime.devices['gpu']['delay'])
