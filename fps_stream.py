"""Per-capture CSV and process/renderer identity. No per-frame OS queries."""
import csv
import math
import time
from collections import Counter
import psutil


class CaptureStream:
    def __init__(self, clock=time.monotonic, process_factory=psutil.Process):
        self.clock = clock
        self.process_factory = process_factory
        self.index = {}
        self.processes = {}
        self.counts = Counter()
        self.observing_since = None
        self.selected = None
        self.last_selected_at = 0

    def consume(self, line):
        try:
            row = next(csv.reader([line]))
            lower = [value.strip().lower() for value in row]
            if 'processid' in lower and ('msbetweenpresents' in lower or 'fps' in lower):
                self.index = {key: i for i, key in enumerate(lower)}
                return None
            def field(name):
                return row[self.index[name]].strip()
            def positive(name):
                try:
                    value = float(field(name))
                    return value if math.isfinite(value) and value > 0 else None
                except (KeyError, IndexError, ValueError):
                    return None
            ms = positive('msbetweenpresents') or positive('msbetweenpresent') or positive('msuntildisplayed')
            fps = positive('fps') or positive('avgfps')
            if fps is None and ms is not None:
                fps = 1000 / ms
            if fps is None or not math.isfinite(fps) or fps <= 0:
                return None
            ms = ms if ms is not None else 1000 / fps
            if not math.isfinite(ms) or ms <= 0 or not math.isfinite(1000 / ms):
                return None
            pid = int(field('processid'))
            swap = field('swapchainaddress')
            now = self.clock()
            cached = self.processes.get(pid)
            if cached is None or now - cached[1] >= 1:
                try:
                    process = self.process_factory(pid)
                    identity = process.create_time() if process.is_running() else None
                except (psutil.Error, OSError):
                    identity = None
                cached = (identity, now)
                self.processes[pid] = cached
                # Bound caches even when many short-lived target processes appear.
                self.processes = {p: value for p, value in self.processes.items() if now - value[1] < 8}
            if cached[0] is None:
                return None
            identity = (pid, cached[0], swap)
            changed = False
            if self.selected and self.selected[0] == pid and self.selected[1] != cached[0]:
                self.selected = None
                self.counts.clear()
                self.observing_since = None
                changed = True
            if self.selected and now - self.last_selected_at >= 4:
                self.selected = None
                self.counts.clear()
                self.observing_since = None
                changed = True
            if self.selected is None:
                if self.observing_since is None:
                    self.observing_since = now
                if len(self.counts) < 128 or identity in self.counts:
                    self.counts[identity] += 1
                if now - self.observing_since < 1:
                    return (None, None, True) if changed else None
                self.selected = min(self.counts, key=lambda key: (-self.counts[key], key))
                self.counts.clear()
                self.last_selected_at = now
                changed = True
            if identity != self.selected:
                return (None, None, True) if changed else None
            self.last_selected_at = now
            return fps, ms, changed
        except (ValueError, IndexError, KeyError, OverflowError, csv.Error):
            return None
