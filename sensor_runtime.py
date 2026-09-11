"""Thread-owned sensor lifecycle and the single sampling-health boundary."""
import logging
import threading
import time
from dataclasses import asdict


class SensorRuntime:
    def __init__(self, reader_factory, config_provider, empty_factory, logger=None,
                 monotonic=time.monotonic):
        self.factory = reader_factory
        self.config_provider = config_provider
        self.empty_factory = empty_factory
        self.logger = logger or logging.getLogger(__name__)
        self.clock = monotonic
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.metrics = empty_factory()
        self.last_success_monotonic = None
        self.updated_at = 0
        self.sample_generation = 0
        self.runtime_generation = 0
        self.error_code = "not_sampled"
        self.state = "unavailable"
        self.devices = {}
        self.gpus = []

    def start(self):
        if self.thread is not None:
            return
        self.runtime_generation += 1
        self.thread = threading.Thread(target=self._run, name="sensor-runtime", daemon=True)
        self.thread.start()

    def stop(self):
        with self.lock:
            self.state = "stopping"
            self.stop_event.set()

    def snapshot(self):
        with self.lock:
            age = None if self.last_success_monotonic is None else max(0, int((self.clock() - self.last_success_monotonic) * 1000))
            state = self.state
            if state != "stopping" and age is not None and age > max(5000, 3 * self.config_provider()["refresh_interval_ms"]):
                state = "stale"
            return dict(metrics=asdict(self.metrics), sample_state=state,
                        sample_age_ms=age, sample_generation=self.sample_generation,
                        error_code="sample_stale" if state == "stale" else self.error_code,
                        updated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.updated_at)) if self.updated_at else "",
                        gpu_devices=list(self.gpus))

    def _recover_devices(self, reader):
        now = self.clock()
        outcomes = dict(getattr(reader, "device_outcomes", {}))
        for identity in self.devices:
            outcomes.setdefault(identity, False)
        rebuild = False
        for identity, success in outcomes.items():
            record = self.devices.setdefault(identity, dict(failures=0, successes=0, delay=30, due=None))
            if success:
                record["successes"] += 1
                record["failures"] = 0
                if record["successes"] >= 3:
                    record.update(delay=30, due=None)
            else:
                record["successes"] = 0
                record["failures"] += 1
                if record["failures"] >= 3 and record["due"] is None:
                    record["due"] = now + record["delay"]
                if record["due"] is not None and now >= record["due"]:
                    record["delay"] = min(300, record["delay"] * 2)
                    record["due"] = now + record["delay"]
                    rebuild = True
        if rebuild and not self.stop_event.is_set():
            reader.close()
            reader._init_lhm()

    def _run(self):
        reader = None
        delay = 1
        try:
            while not self.stop_event.is_set():
                try:
                    if reader is None:
                        reader = self.factory()
                    config = dict(self.config_provider())
                    metrics = reader.read_metrics(config)
                    outcomes = getattr(reader, "device_outcomes", {})
                    degraded = any(not good for good in outcomes.values())
                    meaningful = [value for key, value in asdict(metrics).items() if key not in ("source_status", "temp_hint", "target_process", "fps", "fps_low_1", "battery_percent")]
                    available = any(value not in (None, "", "--", "N/A") for value in meaningful)
                    with self.lock:
                        if self.stop_event.is_set():
                            break
                        if available:
                            self.metrics = metrics
                            self.last_success_monotonic = self.clock()
                            self.updated_at = time.time()
                            self.sample_generation += 1
                        self.state = ("degraded" if degraded else "ok") if available else "unavailable"
                        self.error_code = ("device_read_failed" if degraded else "") if available else "no_sensor_data"
                        self.gpus = list(getattr(reader, "gpu_devices", []))
                    self._recover_devices(reader)
                    delay = 1
                    self.stop_event.wait(config["refresh_interval_ms"] / 1000)
                except Exception:
                    with self.lock:
                        if self.stop_event.is_set():
                            break
                        self.error_code = "sample_read_failed"
                        self.state = "degraded" if self.last_success_monotonic is not None else "unavailable"
                    self.logger.warning("Sampling failed; retry in %ss", delay, exc_info=True)
                    self.stop_event.wait(delay)
                    delay = min(30, delay * 2)
        finally:
            if reader is not None:
                try:
                    reader.close()
                except Exception:
                    self.logger.exception("Sampler cleanup failed")
