import json
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import psutil
from fps_sessions import SessionRegistry


class SessionOwnershipTests(unittest.TestCase):
    def test_only_dead_recorded_owner_session_is_reclaimed(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'PresentMon.exe'
            registry = SessionRegistry(directory, executable, logging.getLogger('session-test'))
            name = 'HardwareMonitoring-' + 'a' * 32 + '-1'
            path = Path(directory) / (name + '.json')
            path.write_text(json.dumps(dict(name=name, executable=str(executable.resolve()), pid=123, created_at=100)), encoding='utf-8')
            with patch('fps_sessions.psutil.Process', return_value=SimpleNamespace(create_time=lambda: 100)), patch('fps_sessions.subprocess.run') as run:
                registry.reclaim()
                run.assert_not_called()
                self.assertTrue(path.exists())
            with patch('fps_sessions.psutil.Process', side_effect=psutil.NoSuchProcess(123)), patch('fps_sessions.subprocess.run', return_value=SimpleNamespace(returncode=0)) as run:
                registry.reclaim()
                args = run.call_args.args[0]
                self.assertEqual([str(executable.resolve()), '--session_name', name, '--terminate_existing_session'], args)
                self.assertNotIn('PresentMon', args[2:])
                self.assertFalse(path.exists())
