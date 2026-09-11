import json
import ctypes
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == 'nt', 'Windows transaction script')
class InstallTransactionTests(unittest.TestCase):
    def run_script(self, mode, root, source):
        return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                               '-File', str(Path(__file__).resolve().parents[1] / 'scripts/install-transaction.ps1'),
                               '-Mode', mode, '-InstallRoot', str(root), '-SourceRoot', str(source)],
                              capture_output=True, timeout=45)

    def test_upgrade_uninstall_only_manage_manifest_files(self):
        with tempfile.TemporaryDirectory() as directory:
            source, root = Path(directory) / 'source', Path(directory) / 'installed'
            source.mkdir(); root.mkdir()
            (source / 'Hardware Monitoring.exe').write_bytes(b'fixture v1')
            (root / 'personal.txt').write_text('preserve', encoding='utf-8')
            result = self.run_script('Install', root, source)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            (source / 'Hardware Monitoring.exe').write_bytes(b'fixture v2')
            result = self.run_script('Install', root, source)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(b'fixture v2', (root / 'Hardware Monitoring.exe').read_bytes())
            result = self.run_script('Uninstall', root, source)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(['personal.txt'], sorted(path.name for path in root.iterdir()))

    def test_manifest_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'installed'
            root.mkdir()
            outside = Path(directory) / 'outside.txt'
            outside.write_text('keep', encoding='utf-8')
            (root / 'managed-files.json').write_text(json.dumps(['../outside.txt']), encoding='utf-8')
            result = self.run_script('Uninstall', root, root)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual('keep', outside.read_text(encoding='utf-8'))
            self.assertTrue((root / 'managed-files.json').exists())

    def test_locked_upgrade_preserves_old_file_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            source, root = Path(directory) / 'source', Path(directory) / 'installed'
            source.mkdir()
            (source / 'Hardware Monitoring.exe').write_bytes(b'v1')
            self.assertEqual(0, self.run_script('Install', root, source).returncode)
            manifest = (root / 'managed-files.json').read_bytes()
            (source / 'Hardware Monitoring.exe').write_bytes(b'v2')
            create = ctypes.windll.kernel32.CreateFileW
            create.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
            create.restype = ctypes.c_void_p
            close = ctypes.windll.kernel32.CloseHandle
            close.argtypes = [ctypes.c_void_p]
            close.restype = ctypes.c_int
            handle = create(str(root / 'Hardware Monitoring.exe'), 0x80000000, 1, None, 3, 0, None)
            self.assertNotEqual(ctypes.c_void_p(-1).value, handle)
            try:
                result = self.run_script('Install', root, source)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(b'v1', (root / 'Hardware Monitoring.exe').read_bytes())
                self.assertEqual(manifest, (root / 'managed-files.json').read_bytes())
            finally:
                close(handle)
