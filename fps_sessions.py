"""Only reclaim ETW sessions whose recorded owner has exited."""
import json
import os
import re
import subprocess
from pathlib import Path
import psutil


class SessionRegistry:
    def __init__(self, directory, executable, logger):
        self.directory = Path(directory)
        self.executable = str(Path(executable).resolve())
        self.logger = logger

    def _terminate(self, name):
        result = subprocess.run([self.executable, '--session_name', name, '--terminate_existing_session'],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=3, creationflags=0x08000000)
        return result.returncode == 0

    def reclaim(self):
        if not self.directory.exists():
            return
        for path in self.directory.glob('HardwareMonitoring-*.json'):
            try:
                raw = path.read_bytes()
                record = json.loads(raw)
                name = record['name']
                if (not re.fullmatch(r'HardwareMonitoring-[0-9a-f]{32}-[0-9]+', name)
                        or path.stem != name or record['executable'] != self.executable):
                    continue
                try:
                    owner = psutil.Process(record['pid'])
                    if owner.create_time() == record['created_at']:
                        continue
                except psutil.NoSuchProcess:
                    pass
                if self._terminate(name) and path.read_bytes() == raw:
                    path.unlink()
            except (OSError, ValueError, KeyError, TypeError, psutil.Error, subprocess.SubprocessError):
                self.logger.warning('Could not reclaim an owned PresentMon session')

    def register(self, name):
        self.directory.mkdir(parents=True, exist_ok=True)
        record = dict(name=name, pid=os.getpid(), created_at=psutil.Process().create_time(), executable=self.executable)
        path = self.directory / (name + '.json')
        with path.open('x', encoding='utf-8') as output:
            json.dump(record, output)
            output.flush()
            os.fsync(output.fileno())
        return path

    def finish(self, name, path):
        try:
            if self._terminate(name):
                path.unlink(missing_ok=True)
        except (OSError, subprocess.SubprocessError):
            self.logger.warning('Owned PresentMon session cleanup incomplete: %s', name)
