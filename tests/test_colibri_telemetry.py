"""CPU-only telemetry tests: all proc/sys inputs and Docker are synthetic."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location(
    'colibri_telemetry', Path(__file__).resolve().parents[1] / 'scripts/colibri_telemetry.py')
telemetry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(telemetry)


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('PROC', 'GPU', 'CPU'):
            path = self.root / name
            path.mkdir()
            patcher = patch.object(telemetry, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.docker = patch.object(telemetry.subprocess, 'run', return_value=Mock(stdout='worker image:v1\n')).start()
        self.addCleanup(patch.stopall)
        self.put('PROC/stat', 'cpu 100 0 20 200 30 0 0 0 50 0\ncpu0 100 0 20 200 30 0 0 0 50 0\n')
        self.put('PROC/loadavg', '1.25 2.50 3.75 2/100 999')
        self.put('PROC/meminfo', 'MemTotal: 2048 kB\nMemAvailable: 1024 kB\nSwapFree: 0 kB\n')
        for resource in ('cpu', 'io', 'memory'):
            self.put('PROC/pressure/' + resource, 'some avg10=1.25 avg60=0.50 avg300=0.25 total=12345\n')
        self.put('CPU/cpu0/cpufreq/scaling_cur_freq', '1400000')
        self.put('CPU/cpu0/cpufreq/scaling_governor', 'schedutil')
        for name in telemetry.GPU_FIELDS:
            self.put('GPU/' + name, '42' if name.endswith('busy_percent') else 'kernel text')
        for name, value in {'temp1_input': '45000', 'temp1_label': 'edge',
                            'power1_average': '125000000', 'power1_input': '120000000',
                            'power1_cap': '200000000', 'power1_label': 'PPT',
                            'freq1_input': '1800000000', 'freq1_label': 'sclk',
                            'fan1_input': '900', 'pwm1': 'ignored'}.items():
            self.put('GPU/hwmon/hwmon7/' + name, value)
        self.t = telemetry.Telemetry(self.root / 'out.jsonl', interval=0.01)

    def put(self, path, value):
        path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def test_cpu_deltas_exclude_iowait_and_guest_double_counting(self):
        self.assertEqual(self.t._cpu_busy(), {'cpu': None, 'cpu0': None})
        self.put('PROC/stat', 'cpu 120 0 30 240 50 0 0 10 65 0\ncpu0 120 0 30 240 50 0 0 10 65 0')
        self.assertEqual(self.t._cpu_busy(), {'cpu': 40.0, 'cpu0': 40.0})
        self.assertEqual(self.t._cpu_busy(), {'cpu': None, 'cpu0': None})
        self.put('PROC/stat', 'cpu 1 0 0 0 0 0 0 0\ncpu1 1 0 0 0 0 0 0 0')
        self.assertEqual(self.t._cpu_busy(), {'cpu': None, 'cpu1': None})

    def test_sample_units_timestamps_and_fields(self):
        sample = self.t._sample()
        self.assertTrue(sample['timestamp'].endswith('+00:00'))
        self.assertAlmostEqual(sample['time'], time.time(), delta=2)
        self.assertAlmostEqual(sample['monotonic'], time.monotonic(), delta=2)
        self.assertEqual(sample['phase'], 'startup')
        self.assertEqual(sample['loadavg']['1m'], 1.25)
        self.assertEqual(sample['loadavg']['running'], 2)
        self.assertEqual(sample['meminfo_kb']['MemAvailable'], 1024)
        self.assertEqual(sample['pressure']['cpu']['some']['total'], 12345)
        self.assertEqual(sample['gpu']['gpu_busy_percent'], 42)
        self.assertEqual(sample['gpu']['pp_dpm_sclk'], 'kernel text')
        sensors = sample['hwmon']['hwmon7']
        self.assertEqual(sensors['temp1_input'], 45000)
        self.assertEqual(sensors['power1_average'], 125000000)
        self.assertEqual(sensors['freq1_input'], 1800000000)
        self.assertEqual(sensors['temp1_label'], 'edge')
        self.assertEqual(sensors['fan1_input'], 900)
        self.assertNotIn('pwm1', sensors)
        self.assertEqual(sample['cpufreq']['cpu0']['scaling_cur_freq'], 1400000)
        self.assertEqual(sample['cpufreq']['cpu0']['scaling_governor'], 'schedutil')

    def test_missing_and_malformed_inputs_are_null(self):
        self.put('GPU/gpu_busy_percent', 'not a number')
        (self.root / 'GPU/mem_busy_percent').unlink()
        self.put('PROC/loadavg', 'invalid')
        self.put('PROC/stat', 'invalid')
        self.put('PROC/pressure/io', 'broken line')
        self.put('GPU/hwmon/hwmon7/temp1_input', 'invalid')
        sample = self.t._sample()
        for key in ('cpu_busy_percent', 'loadavg'):
            self.assertIsNone(sample[key])
            self.assertIn(key, sample['errors'])
        self.assertIsNone(sample['gpu']['gpu_busy_percent'])
        self.assertIsNone(sample['gpu']['mem_busy_percent'])
        self.assertIsNone(sample['pressure']['io'])
        self.assertIsNone(sample['hwmon']['hwmon7']['temp1_input'])
        self.assertIsNone(sample['meminfo_kb']['MemFree'])
        with patch.object(telemetry, '_read', side_effect=PermissionError('denied')):
            sample = self.t._sample()
        self.assertIsNone(sample['cpu_busy_percent'])
        self.assertIn('denied', sample['errors']['cpu_busy_percent'])

    def test_docker_only_names_images_every_ten_samples(self):
        for _ in range(21):
            sample = self.t._sample()
        self.assertEqual(self.docker.call_count, 3)
        self.docker.assert_called_with(
            ['docker', 'ps', '--format', '{{.Names}} {{.Image}}'],
            capture_output=True, text=True, timeout=2, check=True)
        self.assertEqual(sample['docker'], [{'name': 'worker', 'image': 'image:v1'}])

    def test_docker_failures_and_retry(self):
        for error in (FileNotFoundError('docker missing'),
                      subprocess.TimeoutExpired('docker', 2),
                      subprocess.CalledProcessError(1, 'docker')):
            with self.subTest(error=error):
                self.t._count = 0
                self.docker.side_effect = error
                self.assertIsNone(self.t._sample()['docker'])
                self.assertIn('docker', self.t._sample()['errors'])
        self.docker.side_effect = None
        self.t._count = 10
        self.assertNotIn('docker', self.t._sample()['errors'])

    def test_context_flush_phase_join_and_no_exception_suppression(self):
        self.t.phase = 'check'
        with self.assertRaisesRegex(RuntimeError, 'workload failed'):
            with self.t as active:
                self.assertIs(active, self.t)
                deadline = time.monotonic() + 3
                records = []
                while time.monotonic() < deadline:
                    lines = self.t.output_path.read_text().splitlines()
                    records = [json.loads(line) for line in lines]
                    if any(row['phase'] == 'decode-run1' for row in records):
                        break
                    if records:
                        self.t.mark('decode-run1')
                    time.sleep(0.005)
                self.assertTrue(records)
                self.assertEqual(records[0]['phase'], 'check')
                self.assertTrue(any(row['phase'] == 'decode-run1' for row in records))
                raise RuntimeError('workload failed')
        self.assertFalse(self.t._thread.is_alive())
        self.assertTrue(self.t._file.closed)
        self.assertIsNone(self.t.error)
        with self.assertRaises(RuntimeError):
            self.t.__enter__()

    def test_output_failure_is_reported(self):
        with telemetry.Telemetry(self.root / 'missing/out.jsonl') as active:
            self.assertIsNotNone(active.error)
        with patch.object(self.t, '_sample', side_effect=OSError('write failed')):
            with self.t:
                self.t._thread.join(timeout=2)
        self.assertEqual(self.t.error, 'write failed')

    def test_interval_validation(self):
        for value in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                telemetry.Telemetry(self.root / 'out', value)


if __name__ == '__main__':
    unittest.main()
