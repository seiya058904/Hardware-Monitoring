import logging
import threading
import time
import unittest

from service_runtime import ServiceRuntime


class ServiceTests(unittest.TestCase):
    def test_blocked_service_does_not_block_submit_and_latest_request_wins(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        calls, owners = [], []
        runtime = ServiceRuntime(lambda: owners.append(threading.get_ident()))
        def block():
            owners.append(threading.get_ident())
            entered.set()
            release.wait(3)
        try:
            runtime.submit('fps', block)
            self.assertTrue(entered.wait(1))
            started = time.monotonic()
            runtime.submit('lan', lambda: calls.append('obsolete'))
            runtime.submit('lan', lambda: (calls.append('latest'), finished.set()))
            self.assertLess(time.monotonic()-started, .1)
            release.set()
            self.assertTrue(finished.wait(1))
            self.assertEqual(['latest'], calls)
        finally:
            release.set()
            runtime.stop()
            runtime.thread.join(2)
        self.assertFalse(runtime.thread.is_alive())
        self.assertEqual([runtime.thread.ident]*2, owners)
        self.assertNotEqual(threading.get_ident(), owners[0])

    def test_shutdown_discards_pending_enable_and_cleans_up(self):
        entered, release, cleaned = threading.Event(), threading.Event(), threading.Event()
        runtime = ServiceRuntime(cleaned.set)
        calls = []
        runtime.submit('fps', lambda: (entered.set(), release.wait(3)))
        self.assertTrue(entered.wait(1))
        runtime.submit('lan', lambda: calls.append('enable'))
        runtime.stop()
        runtime.submit('lan', lambda: calls.append('late'))
        release.set()
        runtime.thread.join(2)
        self.assertTrue(cleaned.is_set())
        self.assertFalse(calls)

    def test_failure_is_reported_and_successful_retry_clears_it(self):
        completed = threading.Event()
        runtime = ServiceRuntime(completed.set, logging.getLogger('service-test'))
        try:
            runtime.submit('lan', lambda: False)
            deadline = time.monotonic()+1
            while not runtime.snapshot() and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertEqual({'lan':'lan_start_failed'}, runtime.snapshot())
            done = threading.Event()
            runtime.submit('lan', lambda: done.set())
            self.assertTrue(done.wait(1))
            self.assertEqual({}, runtime.snapshot())
        finally:
            runtime.stop()
            runtime.thread.join(2)
