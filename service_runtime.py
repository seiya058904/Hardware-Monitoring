"""Serialize native service changes off Tk, coalescing pending requests."""
import logging
import threading


class ServiceRuntime:
    def __init__(self, cleanup, logger=None):
        self.cleanup = cleanup
        self.logger = logger or logging.getLogger(__name__)
        self.condition = threading.Condition()
        self.pending = {}
        self.errors = {}
        self.stopping = False
        self.thread = threading.Thread(target=self._run, name='service-runtime', daemon=True)
        self.thread.start()

    def submit(self, key, action):
        with self.condition:
            if self.stopping:
                return
            self.pending[key] = action
            self.errors.pop(key, None)
            self.condition.notify()

    def snapshot(self):
        with self.condition:
            return dict(self.errors)

    def stop(self):
        with self.condition:
            self.stopping = True
            self.pending.clear()
            self.condition.notify()

    def _run(self):
        try:
            while True:
                with self.condition:
                    self.condition.wait_for(lambda: self.stopping or self.pending)
                    if self.stopping:
                        return
                    key = next(iter(self.pending))
                    action = self.pending.pop(key)
                try:
                    success = action()
                    with self.condition:
                        if key not in self.pending and not self.stopping:
                            if success is False:
                                self.errors[key] = key + '_start_failed'
                            else:
                                self.errors.pop(key, None)
                except Exception:
                    self.logger.exception('%s service change failed', key)
                    with self.condition:
                        if key not in self.pending and not self.stopping:
                            self.errors[key] = key + '_start_failed'
        finally:
            self.cleanup()
