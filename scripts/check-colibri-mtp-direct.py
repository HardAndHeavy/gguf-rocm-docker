#!/usr/bin/env python3
"""Bounded direct-Docker integration B. No dotenv/Compose; output contains no API key.
Run: python3 scripts/check-colibri-mtp-direct.py [--seconds 540] [--cases ...]
Metadata files are hashed, never model shards. Each case starts from its own copy.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'sha256:e888c06f9db6a2d55997c43f2b0bd45c0face5d3ff428eba2b8a19dc65a299cc'
MODEL = 'Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf'
HEAD = 'mtp-Qwen3.8-Flash-Next-Q2_0.gguf'
CASES = {'off': {'Q38_MTP': '0'}, 'cpu': {'Q38_MTP_CHAIN': '0'},
         'full': {}, 'full-serialized': {'AMD_SERIALIZE_KERNEL': '3', 'AMD_SERIALIZE_COPY': '3'}, 'full-sk0': {'COLI_CUDA_GEMV_SK': '0'},
         'full-w40': {'COLI_CUDA_GEMV_W4': '0'}}
FAIL = re.compile(r'HSA_STATUS_ERROR_MEMORY_FAULT|memory access fault|engine exited|dispatcher stopped|segmentation fault|GPU coredump|HIP error|Aborted', re.I)


def case_environment(name, force_verify=False):
    env = dict(COLI_CUDA='1', COLI_VULKAN='0', COLI_CUDA_HOST_POOL='0',
        COLI_CUDA_CHAIN_POOL='1', COLI_CUDA_CHAIN_LAYERWISE='1', COLI_CUDA_CHAIN_ROWS='64',
        COLI_LOOKUP='0', Q38_MTP='1', Q38_MTP_CHAIN='1', Q38_MTP_DRAFTS='0',
        COLI_CUDA_CHAIN_MTP_CARD='1', COLI_CUDA_CHAIN_MTP_POOL='1',
        COLI_NO_OMP_TUNE='1', OMP_NUM_THREADS='8', COLI_ALLOWED_HOSTS='localhost,127.0.0.1')
    if force_verify:
        env.update(Q38_MTP_DRAFTS='3', Q38_MTP_PSTEP='0', COLI_SPEC_GATE='0')
    env.update(CASES[name])
    return env


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def cmd(args, timeout=15, **kwargs):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, **kwargs)
    return {'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}


def resolve_image(reference):
    """Resolve a local reference once; launch only its immutable ID, never pull."""
    inspected = cmd(['docker', 'image', 'inspect', reference])
    if inspected['returncode']:
        raise RuntimeError('Local image missing: ' + reference)
    info = json.loads(inspected['stdout'])[0]
    image_id = info['Id']
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
        raise RuntimeError('Invalid immutable image ID')
    return image_id, {'requested_reference': reference, 'id': image_id,
                      'labels': info.get('Config', {}).get('Labels', {}),
                      'repo_digests': info.get('RepoDigests', [])}


def manifest(path):
    return [{'path': str(p.relative_to(path)), 'bytes': p.stat().st_size,
             'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(path.rglob('*')) if p.is_file()]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--image', default=IMAGE, help='Local reference resolved to immutable ID; never pulled')
    ap.add_argument('--seconds', type=int, default=540)
    ap.add_argument('--ready-seconds', type=int, default=360)
    ap.add_argument('--force-verify', action='store_true',
                    help='Separate maintainer scenario: DRAFTS=3 PSTEP=0 SPEC_GATE=0, not historical baseline')
    ap.add_argument('--cases', nargs='+', choices=CASES, default=list(CASES))
    a = ap.parse_args()
    image_id, image_details = resolve_image(a.image)
    if not 1 <= a.ready_seconds <= 480:
        ap.error('--ready-seconds must be 1..480')
    if not 1 <= a.seconds <= 570:
        ap.error('--seconds must be 1..570 (cleanup reserved inside ten minutes)')
    start = time.monotonic()
    deadline = start + a.seconds
    out = ROOT / 'data/colibri-investigation/integration' / time.strftime('%Y%m%d-%H%M%S')
    out.mkdir(parents=True)
    spec = importlib.util.spec_from_file_location('benchmark', ROOT / 'scripts/benchmark.py')
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    source = ROOT / 'data/colibri-mtp-dev-control'
    if not source.is_dir() or not any(source.rglob('config.json')):
        raise RuntimeError('Required common control snapshot is missing: data/colibri-mtp-dev-control')
    original = manifest(source)
    save(out / 'common-snapshot-manifest.json', original)
    # Only shard metadata is recorded: explicitly NOT a model-content hash.
    save(out / 'model-metadata-NOT-content-hashes.json', [
        {'name': p.name, 'bytes': p.stat().st_size, 'mtime_ns': p.stat().st_mtime_ns}
        for p in sorted((ROOT / 'data/models').glob('*.gguf'))
        if p.name in (MODEL, MODEL.replace('00001', '00002'), HEAD)])
    save(out / 'image-id.json', image_details)
    save(out / 'prompts.json', {k: bench.PROMPTS[k] for k in ('short', 'decode')})
    save(out / 'provenance.json', {'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
         'benchmark_sha256': hashlib.sha256((ROOT/'scripts/benchmark.py').read_bytes()).hexdigest(),
         'image': image_id, 'seconds': a.seconds, 'ready_seconds': a.ready_seconds, 'force_verify': a.force_verify, 'cases': a.cases,
         'core_policy': 'Docker ulimit core=0:0; HSA_COREDUMP not set (not documented in installed runtime).',
         'note': 'No dotenv; API secret exists only in client/process environment. Model files not hashed.'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    key = secrets.token_urlsafe(32)
    results = []
    active = None
    def cleanup():
        nonlocal active
        if active:
            name_to_remove = active
            try:
                cmd(['docker', 'stop', '-t', '10', name_to_remove], timeout=15)
            finally:
                try:
                    cmd(['docker', 'rm', '-f', name_to_remove], timeout=15)
                finally:
                    active = None
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    def http(path, payload=None, timeout=2):
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        return opener.open(urllib.request.Request('http://127.0.0.1:18080/v1' + path,
            data=data, headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}), timeout=timeout)
    def snapshot(d, label):
        logs = cmd(['docker', 'logs', '--timestamps', active])
        (d / f'{label}-docker.log').write_text(logs['stdout'] + logs['stderr'])
        save(d / f'{label}-state.json', cmd(['docker', 'inspect', '--format', '{{json .State}}', active]))
        save(d / f'{label}-processes.json', cmd(['docker', 'top', active, '-eo', 'pid,ppid,stat,comm']))
        return logs['stdout'] + logs['stderr']
    def gpu_ok(d):
        # Runtime enumeration, not just existence of /dev/kfd; use only our named container.
        nonlocal active
        active = 'colibri-direct-probe-' + secrets.token_hex(5)
        try:
            r = cmd(['docker', 'run', '--name', active, '--pull', 'never', '--network', 'none',
                     '--device', '/dev/kfd', '--device', '/dev/dri', '--ulimit', 'core=0:0',
                     '--entrypoint', '/opt/rocm/bin/rocminfo', image_id], timeout=12)
            save(d / 'gpu-probe.json', r)
            return r['returncode'] == 0 and 'gfx1201' in r['stdout']
        except subprocess.TimeoutExpired:
            save(d / 'gpu-probe.json', {'error': 'runtime enumeration timeout'})
            return False
        finally:
            cleanup()
    try:
        for name in a.cases:
            if time.monotonic() + 25 > deadline:
                results.append({'case': name, 'status': 'skipped-total-budget'})
                continue
            d = out / name
            d.mkdir()
            # Bind test fails closed rather than stopping anybody else's server.
            with socket.socket() as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('127.0.0.1', 18080))
            shutil.copytree(source, d / 'state')
            save(d / 'pre-run-manifest.json', manifest(d / 'state'))
            env = case_environment(name, a.force_verify)
            save(d / 'environment-public.json', env)
            active = 'colibri-direct-' + name + '-' + secrets.token_hex(5)
            run = ['docker', 'run', '-d', '--name', active, '--pull', 'never', '--network', 'host',
                '--init', '--device', '/dev/kfd', '--device', '/dev/dri', '--ulimit', 'memlock=-1:-1',
                '--ulimit', 'core=0:0', '--shm-size', '2g', '--no-healthcheck']
            for gid in sorted({os.stat('/dev/kfd').st_gid, os.stat('/dev/dri/card1').st_gid}):
                run += ['--group-add', str(gid)]
            for k, v in env.items():
                run += ['-e', k + '=' + v]
            import_head = '--no-mtp' if name == 'off' else '--mtp /models/' + HEAD
            run += ['-e', 'COLI_API_KEY', '-v', str(ROOT/'data/models')+':/models:ro',
                '-v', str(d/'state')+':/state', '--entrypoint', 'bash', image_id, '-lc',
                'ulimit -c 0; python3 ./coli import /models/'+MODEL+' --out /state/'+MODEL[:-5]+'.colibri --mode link '+import_head+
                ' && exec python3 ./coli serve --model /state/'+MODEL[:-5]+'.colibri --ctx 8192 --ram 48 --host 127.0.0.1 --port 18080']
            save(d / 'command.json', run)
            result = {'case': name, 'status': 'starting'}
            results.append(result)
            print(name, 'starting', flush=True)
            model_id = None
            case_start = time.monotonic()
            try:
                launched = cmd(run, env={**os.environ, 'COLI_API_KEY': key})
                save(d/'launch.json', launched)
                if launched['returncode']:
                    raise RuntimeError('docker run failed; see launch.json')
                ready_end = min(deadline-12, time.monotonic()+a.ready_seconds)
                model_id = None
                while time.monotonic() < ready_end:
                    logs = snapshot(d, 'readiness')
                    if FAIL.search(logs):
                        raise RuntimeError('engine failure in docker logs during readiness')
                    try:
                        with http('/models') as response:
                            models = json.load(response)
                        save(d/'models.json', models)
                        model_id = models['data'][0]['id']
                        break
                    except Exception as exc:
                        save(d/'readiness-http-error.json', {'error': str(exc)})
                        time.sleep(1)
                if not model_id:
                    raise TimeoutError('readiness deadline exceeded')
                result['readiness_seconds'] = time.monotonic() - case_start
                for prompt_name in ('short', 'decode'):
                    payload = dict(model=model_id, messages=[{'role':'user','content':bench.PROMPTS[prompt_name]}],
                        temperature=0, max_tokens=192, presence_penalty=0, frequency_penalty=0,
                        chat_template_kwargs={'enable_thinking':False}, stream=True, stream_options={'include_usage':True})
                    save(d/(prompt_name+'-request.json'), payload)
                    record = {'content':'', 'reasoning_content':'', 'events':[]}
                    save(d/(prompt_name+'-result.json'), record)
                    request_end = min(deadline-12, time.monotonic()+90)
                    def stream():
                        with http('/chat/completions', payload, timeout=max(1,min(10,request_end-time.monotonic()))) as response:
                            record['http_status'] = response.status
                            with (d/(prompt_name+'-response.sse')).open('wb') as rawout:
                                for line in response:
                                    rawout.write(line); rawout.flush()
                                    if time.monotonic() >= request_end:
                                        raise TimeoutError('stream total deadline')
                                    if not line.startswith(b'data:'): continue
                                    data = line[5:].strip()
                                    if data == b'[DONE]':
                                        record['done'] = True
                                        break
                                    event = json.loads(data)
                                    record['events'].append(event)
                                    for choice in event.get('choices', []):
                                        for k in ('content','reasoning_content'):
                                            record[k] += choice.get('delta',{}).get(k) or ''
                                    save(d/(prompt_name+'-result.json'), record)
                    # Main thread polls engine diagnostics even when API worker is hung.
                    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                    future = pool.submit(stream)
                    try:
                        while not future.done():
                            if FAIL.search(snapshot(d, prompt_name)):
                                raise RuntimeError('engine failure in docker logs during '+prompt_name)
                            if time.monotonic() >= request_end:
                                raise TimeoutError('request wall-clock deadline')
                            time.sleep(1)
                        future.result()
                        if not record.get('done'):
                            raise RuntimeError('stream ended without DONE')
                        if record.get('http_status') != 200 or not any(isinstance(e.get('usage'), dict) for e in record['events']):
                            raise RuntimeError('stream missing HTTP 200 or usage')
                        if any('error' in e for e in record['events']):
                            raise RuntimeError('error event in stream')
                    except Exception as exc:
                        record['error'] = str(exc)
                        save(d/(prompt_name+'-result.json'), record)
                        raise
                    finally:
                        pool.shutdown(wait=False, cancel_futures=True)
                    save(d/(prompt_name+'-result.json'), record)
                result['status'] = 'completed'
            except Exception as exc:
                result.update(status=('inconclusive-startup' if not model_id else 'failed'), error=str(exc))
            finally:
                logs = snapshot(d, 'final')
                result['engine_fault_detected'] = bool(FAIL.search(logs))
                result['elapsed_seconds'] = time.monotonic() - case_start
                if result['engine_fault_detected']:
                    result['status'] = 'failed-engine'
                cleanup()
                save(d/'post-run-manifest.json', manifest(d/'state'))
                save(out/'results.json', results)
            print(name, result['status'], result.get('error',''), flush=True)
            if result.get('engine_fault_detected') and not gpu_ok(d):
                results.append({'status':'stopped-gpu-unavailable', 'remaining_cases': a.cases[a.cases.index(name)+1:]})
                break
    finally:
        cleanup()
        save(out/'results.json', results)
        save(out/'snapshot-integrity.json', {'unchanged': manifest(source) == original})
        (out/'SUMMARY.md').write_text('# Direct integration B\n\n'+ '\n'.join('- '+json.dumps(r) for r in results)+
            '\n\nFresh processes, metadata snapshot copies, host networking, loopback bind only. No model content hashes. '+
            'Core ulimit is zero; unsupported HSA_COREDUMP variable deliberately not guessed. '+
            'A passing request is not exhaustive correctness or performance evidence.\n')
        print('Artifacts:', out, flush=True)


if __name__ == '__main__':
    main()
