import unittest
from types import SimpleNamespace as Obj
from unittest.mock import patch
from app import DEFAULT_CONFIG, SensorReader


def hardware(identity, kind, sensors, fail=False):
    def update():
        if fail: raise RuntimeError('device failure')
    return Obj(Identifier=identity, Name=identity, HardwareType=kind, Sensors=sensors,
               SubHardware=[], Update=update)


def sensor(kind, name, value):
    return Obj(SensorType=kind, Name=name, Value=value)


class SensorDeviceTests(unittest.TestCase):
    def reader(self):
        with patch.object(SensorReader, '_init_lhm'):
            reader = SensorReader()
        reader._lhm_hardware = Obj(SensorType=Obj(Load='Load', Temperature='Temperature', Clock='Clock'))
        return reader

    def test_identity_bridge_does_not_wrap_identifier_class(self):
        reader = self.reader()
        class Hardware:
            @property
            def Identifier(self): raise AssertionError("must not wrap CLR Identifier")
        reader._identifier_reader = lambda hardware: "/gpu/opaque"
        self.assertEqual('/gpu/opaque', reader._hardware_identity(Hardware()))

    def test_gpu_selection_is_same_device_and_order_independent(self):
        reader = self.reader()
        a = hardware('/gpu/a', 'GpuNvidia', [sensor('Load', 'GPU Core', 80), sensor('Temperature', 'GPU Core', 70), sensor('SmallData', 'GPU Memory Total', 8000)])
        b = hardware('/gpu/b', 'GpuIntel', [sensor('Load', 'GPU Core', 10), sensor('SmallData', 'GPU Memory Used', 100)])
        reader._requested_gpu = '/gpu/b'
        for items in ([a, b], [b, a]):
            reader._lhm_computer = Obj(Hardware=items)
            values = reader._read_lhm_values()
            self.assertEqual(10, values['gpu_usage'])
            self.assertIsNone(values['gpu_temp'])
            self.assertEqual(100, values['gpu_memory_used'])
            self.assertIsNone(values['gpu_memory_total'])

    def test_bad_gpu_preserves_cpu(self):
        reader = self.reader()
        cpu = hardware('/cpu', 'Cpu', [sensor('Temperature', 'CPU Package', 50)])
        gpu = hardware('/gpu', 'GpuNvidia', [], fail=True)
        reader._lhm_computer = Obj(Hardware=[gpu, cpu])
        self.assertEqual(50, reader._read_lhm_values()['cpu_temp'])
        self.assertFalse(reader.device_outcomes['/gpu'])
        self.assertTrue(reader.device_outcomes['/cpu'])

    def test_smi_multiline_retains_uuid_and_partial_values(self):
        reader = self.reader()
        reader._nvidia_smi = 'nvidia-smi'
        with patch.object(reader, '_run_cmd', return_value='GPU-a,A,10,50,1000,80,100,8000\nGPU-b,B,20,N/A,1200,90,200,24000'):
            result = reader._read_smi_devices()
        self.assertEqual(8000, result['nvidia:GPU-a'][1]['gpu_memory_total'])
        self.assertEqual(200, result['nvidia:GPU-b'][1]['gpu_memory_used'])
        self.assertIsNone(result['nvidia:GPU-b'][1]['gpu_temp'])

    def test_io_baseline_resets_on_topology_and_clock_is_monotonic(self):
        reader = self.reader()
        reader._nvidia_smi = None
        values = dict(cpu_temp=None, gpu_temp=None, memory_freq=None)
        config = DEFAULT_CONFIG.copy()
        config['show_network_latency'] = False
        counters = lambda value: {'nic': Obj(bytes_sent=value, bytes_recv=value)}
        with patch.object(reader, '_read_lhm_values', return_value=values), patch.object(reader, '_read_fallback_values', return_value=values), patch('app.psutil.disk_io_counters', return_value={}), patch('app.psutil.net_io_counters', side_effect=[counters(0), counters(1048576), {}, counters(99999999), counters(101048575)]), patch('app.time.monotonic', side_effect=[1, 2, 3, 4, 5]):
            samples = [reader.read_metrics(config) for _ in range(5)]
        self.assertEqual('--', samples[0].network_up)
        self.assertEqual('1.0 MB/s', samples[1].network_up)
        self.assertEqual('--', samples[2].network_up)
        self.assertEqual('--', samples[3].network_up)
        self.assertEqual('1.0 MB/s', samples[4].network_up)
