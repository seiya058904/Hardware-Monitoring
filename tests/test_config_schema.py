import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import load_config, validate_config


class ConfigSchemaTests(unittest.TestCase):
    def test_numeric_overflow_and_bool_matrix(self):
        for value in ('false', 0, 1, [], {}, None):
            self.assertFalse(validate_config({'lan_dashboard_enabled': value})[0]['lan_dashboard_enabled'])
        self.assertTrue(validate_config({'lan_dashboard_enabled': True})[0]['lan_dashboard_enabled'])
        result, errors = validate_config({'refresh_interval_ms': 10 ** 400, 'font_scale': float('inf')})
        self.assertEqual(1000, result['refresh_interval_ms'])
        self.assertEqual(1.0, result['font_scale'])
        self.assertEqual(2, len(errors))
        self.assertEqual(2000, validate_config({'update_interval_ms': 2000})[0]['refresh_interval_ms'])

    def test_invalid_types_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            raw = json.dumps({'theme': [], 'lan_dashboard_enabled': 'false',
                              'window_opacity': float('nan'), 'gpu_device_id': []})
            (path / 'config.json').write_text(raw, encoding='utf-8')
            with patch('app.runtime_data_dir', return_value=path):
                config = load_config()
            self.assertFalse(config['lan_dashboard_enabled'])
            self.assertEqual('深色蓝', config['theme'])
            self.assertEqual(.96, config['window_opacity'])
            self.assertIsNone(config['gpu_device_id'])
            self.assertEqual(raw, (path / 'config.json').read_text(encoding='utf-8'))
