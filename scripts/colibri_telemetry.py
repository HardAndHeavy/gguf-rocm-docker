"""Read-only Linux telemetry, with no GPU utilities or clock/configuration writes.

Usage::

    with Telemetry("telemetry.jsonl", interval=1.0) as telemetry:
        telemetry.phase = "short-run-1"  # or telemetry.mark("short-run-1")
        run_workload()

Each flushed JSONL record has UTC ISO, Unix and monotonic timestamps. CPU busy
percent uses deltas (idle + iowait excluded); the first reading is null. Guest
counters are not added twice. Memory values retain /proc/meminfo kB units;
load/PSI and sysfs DPM/link strings retain kernel formatting. hwmon numbers are
RAW kernel units: temp milliC, power microW, freq Hz, fan RPM. CPU cpufreq is
kHz. GPU busy counters are percentages. Missing/unreadable/malformed fields are
null with details in `errors`. Docker names/images only are cached for ten
samples; no inspect, environment or process arguments are collected.

Input collection is best-effort. Output/open/thread errors are available as
`error` and do not hide workload exceptions. The output directory must exist.
"""

import datetime
import json
import math
from pathlib import Path
import re
import subprocess
import threading
import time

PROC = Path('/proc')
GPU = Path('/sys/class/drm/card1/device')
CPU = Path('/sys/devices/system/cpu')

GPU_FIELDS = (
    'gpu_busy_percent', 'mem_busy_percent', 'pp_dpm_sclk', 'pp_dpm_mclk',
    'power_dpm_force_performance_level', 'current_link_speed', 'current_link_width',
)
MEM_FIELDS = ('MemTotal', 'MemFree', 'MemAvailable', 'Buffers', 'Cached',
              'SwapTotal', 'SwapFree', 'Dirty', 'Writeback')
HWMON_FIELD = re.compile(r'(?:temp\d+_(?:input|label)|power\d+_(?:average|input|cap|label)|'
                         r'freq\d+_(?:input|label)|fan\d+_input)$')


def _read(path):
    return path.read_text().strip()


class Telemetry:
    """Single-use context manager; `phase`/`mark` are thread-safe annotations."""

    def __init__(self, output_path, interval=1.0):
        self.output_path = Path(output_path)
        self.interval = float(interval)
        if not math.isfinite(self.interval) or self.interval <= 0:
            raise ValueError('interval must be positive and finite')
        self._lock = threading.Lock()
        self._phase = 'startup'
        self._stop = threading.Event()
        self._thread = None
        self._file = None
        self._entered = False
        self._previous_cpu = {}
        self._count = 0
        self._docker = None
        self._docker_error = None
        self.error = None

    @property
    def phase(self):
        with self._lock:
            return self._phase

    @phase.setter
    def phase(self, value):
        if not isinstance(value, str):
            raise TypeError('phase must be a string')
        with self._lock:
            self._phase = value

    def mark(self, phase):
        self.phase = phase

    def __enter__(self):
        if self._entered:
            raise RuntimeError('Telemetry contexts cannot be reused')
        self._entered = True
        try:
            self._file = self.output_path.open('w', encoding='utf-8')
            self._thread = threading.Thread(target=self._run, name='colibri-telemetry', daemon=True)
            self._thread.start()
        except Exception as exc:
            self.error = str(exc)
            if self._file is not None:
                self._file.close()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._stop.set()
        if self._thread is not None and self._thread.ident is not None:
            self._thread.join()
        if self._file is not None:
            try:
                self._file.close()
            except Exception as error:
                self.error = str(error)
        return False

    def _run(self):
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                sample = self._sample()
                self._file.write(json.dumps(sample, allow_nan=False) + '\n')
                self._file.flush()
            except Exception as exc:
                self.error = str(exc)
                break
            self._stop.wait(max(0.0, self.interval - (time.monotonic() - started)))

    def _sample(self):
        now = time.time()
        sample = {
            'timestamp': datetime.datetime.fromtimestamp(now, datetime.timezone.utc).isoformat(),
            'time': now, 'monotonic': time.monotonic(), 'phase': self.phase,
            'errors': {},
        }
        errors = sample['errors']

        def attempt(key, fn):
            try:
                return fn()
            except Exception as exc:
                errors[key] = str(exc)
                return None

        def field(path, key, convert=str):
            return attempt(key, lambda: convert(_read(path)))

        sample['cpu_busy_percent'] = attempt('cpu_busy_percent', self._cpu_busy)
        sample['loadavg'] = field(PROC / 'loadavg', 'loadavg', self._loadavg)
        sample['meminfo_kb'] = attempt('meminfo_kb', lambda: self._meminfo(errors))
        sample['pressure'] = {
            name: field(PROC / 'pressure' / name, 'pressure.' + name, self._pressure)
            for name in ('cpu', 'io', 'memory')
        }
        sample['gpu'] = {
            name: field(GPU / name, 'gpu.' + name,
                        int if name in ('gpu_busy_percent', 'mem_busy_percent') else str)
            for name in GPU_FIELDS
        }

        def hwmon():
            result = {}
            for directory in sorted((GPU / 'hwmon').glob('hwmon*')):
                sensors = {}
                for path in sorted(directory.iterdir()):
                    if HWMON_FIELD.fullmatch(path.name):
                        key = 'hwmon.' + directory.name + '.' + path.name
                        sensors[path.name] = field(path, key, str if path.name.endswith('_label') else int)
                result[directory.name] = sensors
            if not result:
                raise FileNotFoundError('no GPU hwmon directories')
            return result

        sample['hwmon'] = attempt('hwmon', hwmon)

        def cpufreq():
            result = {}
            for directory in sorted(CPU.glob('cpu[0-9]*')):
                if not re.fullmatch(r'cpu\d+', directory.name):
                    continue
                result[directory.name] = {
                    name: field(directory / 'cpufreq' / name, directory.name + '.' + name, convert)
                    for name, convert in (('scaling_cur_freq', int), ('scaling_governor', str))
                }
            if not result:
                raise FileNotFoundError('no CPU directories')
            return result

        sample['cpufreq'] = attempt('cpufreq', cpufreq)
        if self._count % 10 == 0:
            self._docker = attempt('docker', self._containers)
            self._docker_error = errors.get('docker')
        if self._docker_error is not None:
            errors['docker'] = self._docker_error
        sample['docker'] = self._docker
        sample['docker_refreshed'] = self._count % 10 == 0
        self._count += 1
        return sample

    def _cpu_busy(self):
        current = {}
        result = {}
        for line in _read(PROC / 'stat').splitlines():
            parts = line.split()
            if not parts or not re.fullmatch(r'cpu\d*', parts[0]):
                continue
            values = [int(value) for value in parts[1:9]]
            if len(values) < 4:
                raise ValueError('incomplete CPU counters')
            total = sum(values)
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            current[parts[0]] = (total, idle)
            previous = self._previous_cpu.get(parts[0])
            busy = None
            if previous is not None:
                delta, idle_delta = total - previous[0], idle - previous[1]
                if delta > 0 and 0 <= idle_delta <= delta:
                    busy = 100.0 * (delta - idle_delta) / delta
            result[parts[0]] = busy
        if 'cpu' not in current:
            raise ValueError('missing aggregate CPU counters')
        self._previous_cpu = current
        return result

    @staticmethod
    def _loadavg(text):
        parts = text.split()
        running, total = parts[3].split('/')
        return dict(zip(('1m', '5m', '15m'), map(float, parts[:3])),
                    running=int(running), total=int(total), last_pid=int(parts[4]))

    @staticmethod
    def _pressure(text):
        result = {}
        for line in text.splitlines():
            parts = line.split()
            values = dict(item.split('=', 1) for item in parts[1:])
            result[parts[0]] = {key: int(value) if key == 'total' else float(value)
                                for key, value in values.items()}
        if not result:
            raise ValueError('empty pressure counters')
        return result

    @staticmethod
    def _meminfo(errors):
        lines = dict(line.split(':', 1) for line in _read(PROC / 'meminfo').splitlines() if ':' in line)
        result = {}
        for name in MEM_FIELDS:
            try:
                result[name] = int(lines[name].split()[0])
            except (KeyError, IndexError, ValueError) as exc:
                result[name] = None
                errors['meminfo_kb.' + name] = str(exc)
        return result

    @staticmethod
    def _containers():
        completed = subprocess.run(
            ['docker', 'ps', '--format', '{{.Names}} {{.Image}}'],
            capture_output=True, text=True, timeout=2, check=True,
        )
        return [{'name': name, 'image': image} for name, image in
                (line.split(maxsplit=1) for line in completed.stdout.splitlines() if line.strip())]
