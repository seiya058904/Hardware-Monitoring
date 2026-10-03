import unittest
from unittest.mock import patch

from app import DEFAULT_CONFIG, SensorReader


class FallbackTtlTests(unittest.TestCase):
    def reader(self):
        with patch.object(SensorReader, '_init_lhm'):
            return SensorReader()

    def test_complete_sample_uses_ten_monotonic_seconds_across_wall_clock_jumps(self):
        reader = self.reader()
        clock, wall = [100.0], [1000.0]
        config = dict(DEFAULT_CONFIG, show_memory_freq=True, show_network_latency=True)
        empty = dict(cpu_temp=None, gpu_temp=None, memory_freq=None)
        with patch('app.time.monotonic', side_effect=lambda: clock[0]), \
             patch('app.time.time', side_effect=lambda: wall[0]), \
             patch('app.psutil.cpu_percent', return_value=0), \
             patch.object(reader, '_read_lhm_values', return_value=empty), \
             patch.object(reader, '_read_smi_devices', return_value={}), \
             patch.object(reader, '_read_coretemp_shared_memory', side_effect=[51, 62, 73]) as core, \
             patch.object(reader, '_fallback_memory_freq', side_effect=[3200, 3600, 4000]) as memory, \
             patch.object(reader, '_fallback_ohm_wmi_cpu_temp') as ohm, \
             patch.object(reader, '_read_ping', side_effect=[11, 22, 33]) as ping:
            for mono, utc, temperature, mhz, latency, count in [
                (100, 1000, 51, 3200, 11, 1),
                (109.999, -5000, 51, 3200, 11, 1),
                (110, -5000, 62, 3600, 22, 2),
                (119.999, 999999, 62, 3600, 22, 2),
                (120, 999999, 73, 4000, 33, 3),
            ]:
                clock[0], wall[0] = mono, utc
                sample = reader.read_metrics(config)
                self.assertEqual(f'{temperature:.1f} °C', sample.cpu_temp)
                self.assertEqual(f'{mhz} MHz', sample.memory_freq)
                self.assertEqual(f'{latency} ms', sample.network_latency)
                self.assertEqual([count] * 3, [core.call_count, memory.call_count, ping.call_count])
            ohm.assert_not_called()

    def test_first_sample_at_monotonic_zero_and_fallback_priority(self):
        reader = self.reader()
        empty = dict(cpu_temp=None, gpu_temp=None, memory_freq=None)
        with patch('app.time.monotonic', return_value=0), \
             patch.object(reader, '_read_coretemp_shared_memory', return_value=None) as core, \
             patch.object(reader, '_fallback_ohm_wmi_cpu_temp', return_value=55) as ohm, \
             patch.object(reader, '_fallback_lhm_wmi_cpu_temp') as lhm, \
             patch.object(reader, '_fallback_cpu_temp') as acpi:
            self.assertEqual(55, reader._read_fallback_values(empty, DEFAULT_CONFIG)['cpu_temp'])
            core.assert_called_once()
            ohm.assert_called_once()
            lhm.assert_not_called()
            acpi.assert_not_called()

    def test_disabled_or_primary_available_never_queries_fallback(self):
        reader = self.reader()
        with patch.object(reader, '_read_coretemp_shared_memory') as core, \
             patch.object(reader, '_fallback_memory_freq') as memory:
            reader._read_fallback_values({}, dict(DEFAULT_CONFIG, show_cpu_temperature=False, show_memory_freq=False))
            reader._read_fallback_values({'cpu_temp': 55, 'memory_freq': 3200}, dict(DEFAULT_CONFIG, show_memory_freq=True))
            core.assert_not_called()
            memory.assert_not_called()
