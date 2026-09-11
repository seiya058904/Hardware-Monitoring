import json
import logging
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app import FpsService, LanDashboardService, preserve_invalid_config, OverlayApp, Metrics, DEFAULT_CONFIG
from sensor_runtime import SensorRuntime
from fps_stream import CaptureStream


class RuntimeRegressions(unittest.TestCase):
    def test_public_snapshot_does_not_leak_internal_diagnostics(self):
        application = OverlayApp.__new__(OverlayApp)
        application.config = DEFAULT_CONFIG.copy()
        application.sensor_runtime = SensorRuntime(None, lambda: application.config, Metrics)
        application.sensor_runtime.metrics = Metrics(cpu_usage="10%", source_status=r"Missing DLL: C:\Users\private-user\secret\file.dll")
        application.sensor_runtime.last_success_monotonic = time.monotonic()
        application.sensor_runtime.state = "degraded"
        application.sensor_runtime.sample_generation = 1
        application.fps_service = FpsService(Path('.'), Path('.'), logging.getLogger('privacy-test'))
        payload = application._dashboard_payload()
        self.assertNotIn("private-user", json.dumps(payload))
        self.assertEqual("degraded", payload['metrics']['source_status'])
        self.assertIn("private-user", application.sensor_runtime.snapshot()['metrics']['source_status'])
        self.assertNotIn('battery_percent', payload['metrics'])

    def test_schema_backup_is_once_and_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            raw = b'{"lan_dashboard_enabled":"false"}'
            path.write_bytes(raw)
            preserve_invalid_config(path)
            preserve_invalid_config(path)
            backups = list(path.parent.glob('config.invalid-*.json'))
            self.assertEqual(1, len(backups))
            self.assertEqual(raw, backups[0].read_bytes())

    def test_old_connection_cannot_read_after_stop(self):
        calls = []
        service = LanDashboardService(lambda: calls.append(1) or {}, lambda: '')
        service.start(0)
        server = service._server
        client = socket.create_connection(('127.0.0.1', service.port), timeout=2)
        try:
            deadline = time.monotonic() + 1
            while not server.handlers and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(server.handlers)
            self.assertTrue(service.stop())
            try:
                client.sendall(b'GET /api/metrics HTTP/1.0\r\n\r\n')
                self.assertNotIn(b'200', client.recv(4096))
            except OSError:
                pass
            self.assertFalse(calls)
            self.assertFalse(any(t.is_alive() for t in server.handlers))
        finally:
            client.close()
            service.stop()

    def test_trickle_cannot_extend_total_deadline(self):
        service = LanDashboardService(lambda: {}, lambda: '')
        service.start(0)
        server = service._server
        server.request_deadline = .2
        client = socket.create_connection(('127.0.0.1', service.port), timeout=1)
        try:
            for _ in range(12):
                try:
                    client.sendall(b'G')
                except OSError:
                    break
                time.sleep(.04)
            deadline = time.monotonic() + 1
            while server.connections and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertFalse(server.connections)
        finally:
            client.close()
            service.stop()

    def test_late_frame_cannot_publish(self):
        service = FpsService(Path('.'), Path('.'), logging.getLogger('test'))
        entered, released = threading.Event(), threading.Event()
        class Capture:
            selected = (1, 2, 'a')
            def consume(self, line):
                entered.set()
                released.wait(2)
                return 60, 16.6, False
        capture = Capture()
        service._capture = capture
        worker = threading.Thread(target=service._consume_line, args=('frame', 0, capture))
        worker.start()
        self.assertTrue(entered.wait(1))
        service.stop()
        released.set()
        worker.join(2)
        self.assertEqual('关闭', service._display_text)
        self.assertEqual(0, len(service._frame_ms_samples))

    def test_stream_identity_and_bounded_process_queries(self):
        now = [0]
        starts = {1: 10, 2: 20}
        calls = []
        class Process:
            def __init__(self, pid): self.pid = pid; calls.append(pid)
            def is_running(self): return True
            def create_time(self): return starts[self.pid]
        capture = CaptureStream(lambda: now[0], Process)
        capture.consume('ProcessID,SwapChainAddress,MsBetweenPresents')
        for _ in range(100): capture.consume('1,a,16')
        self.assertEqual([1], calls)
        now[0] = 1.1
        self.assertEqual((62.5, 16, True), capture.consume('1,a,16'))
        self.assertIsNone(capture.consume('1,b,16'))
        for bad in ('nan', 'inf', '-inf', '0', '-1', '', '1e-320'):
            self.assertIsNone(capture.consume('1,a,' + bad))
        self.assertEqual((62.5, 16, False), capture.consume('1,a,16'))
        starts[1] = 30
        now[0] = 2.2
        self.assertEqual((None, None, True), capture.consume('1,a,16'))
