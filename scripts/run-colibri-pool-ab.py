#!/usr/bin/env python3
"""Issue #2757: pinned-dev pool-path AB/BA and promotion BC/CB. No Compose/dotenv.
Only this runner's container is stopped. API binds loopback via host networking.
Outputs contain no API secret; model metadata is NOT a content hash.
"""
from __future__ import annotations
import argparse
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
import uuid

ROOT = Path(__file__).resolve().parents[1]

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def bus_comparison_plan(old_image, new_image):
    """Four independent processes: old/new/new/old, forced bus throughout."""
    return [dict(build=build, image=image, profile='B') for build, image in
            [('old', old_image), ('new', new_image), ('new', new_image), ('old', old_image)]]


def experiment_settings(gemv_sk=None, promote=None):
    return dict(COLI_CUDA_GEMV_SK=gemv_sk, COLI_CUDA_CHAIN_PROMOTE=promote)


def check_resume_settings(provenance, settings):
    if provenance.get('experiment_settings', experiment_settings()) != settings:
        raise RuntimeError('resume experiment settings mismatch')


def environment_arguments(env):
    return [arg for key, value in env.items() for arg in ('-e', key+'='+value)]


def process_environment(profile, gemv_sk=None, promote=None):
    env = dict(COLI_CUDA='1', COLI_VULKAN='0',COLI_CUDA_HOST_POOL='0',COLI_CUDA_CHAIN_POOL='1',COLI_CUDA_CHAIN_LAYERWISE='1',COLI_CUDA_CHAIN_ROWS='64',COLI_LOOKUP='0',Q38_MTP='0',Q38_MTP_CHAIN='1',Q38_MTP_DRAFTS='0',COLI_CUDA_CHAIN_MTP_CARD='1',COLI_CUDA_CHAIN_MTP_POOL='1',COLI_NO_OMP_TUNE='1',OMP_NUM_THREADS='8',COLI_ALLOWED_HOSTS='localhost,127.0.0.1')
    if profile in ('B','C'):
        env['COLI_CUDA_CHAIN_POOL_READ']='1'
    if profile == 'C':
        env['COLI_CUDA_CHAIN_PROMOTE_HITS']='90'
    for key, value in experiment_settings(gemv_sk, promote).items():
        if value is not None:
            env[key] = value
    return env

def main():
    helper = load('direct_helper', 'check-colibri-mtp-direct.py')
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--startup-timeout', type=int, default=480)
    ap.add_argument('--resume', type=Path, help='Resume this runner\'s interrupted series; retain original corpus/snapshot')
    ap.add_argument('--sequence', nargs='+', choices=['A','B','C'], default=list('ABBABCCB'))
    ap.add_argument('--compare-bus-image', help='Compare --image (old) with this new image as old/new/new/old, all forced bus; no resume')
    ap.add_argument('--telemetry', action='store_true', help='Read-only 1 Hz sysfs/proc telemetry annotated by request phase')
    ap.add_argument('--image', default=helper.IMAGE, help='Image reference resolved to an immutable ID before launch')
    ap.add_argument('--require-auto-decision', action='store_true', help='Require profile A to log its measured automatic pool choice before timing')
    ap.add_argument('--gemv-sk', choices=['0','1'], default=None, help='Explicit container COLI_CUDA_GEMV_SK (default unset)')
    ap.add_argument('--promote', choices=['0','1'], default=None, help='Explicit container COLI_CUDA_CHAIN_PROMOTE (default unset)')
    args = ap.parse_args()
    settings = experiment_settings(args.gemv_sk, args.promote)
    image_id, image_details = helper.resolve_image(args.image)
    comparison_details = None
    if args.compare_bus_image:
        if args.resume or args.require_auto_decision:
            ap.error('bus comparison cannot resume or require auto decision')
        comparison_id, comparison_details = helper.resolve_image(args.compare_bus_image)
        if comparison_id == image_id:
            ap.error('comparison images must differ')
        plan = bus_comparison_plan(image_id, comparison_id)
        args.sequence = ['B'] * 4
    else:
        plan = [dict(build='single', image=image_id, profile=p) for p in args.sequence]
    telemetry_module = load('colibri_telemetry', 'colibri_telemetry.py') if args.telemetry else None
    bench = load('pool_benchmark', 'benchmark.py')
    # Explicitly bypass host proxy settings for the loopback-only API.
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
    stamp = time.strftime('%Y%m%d-%H%M%S')
    out = args.resume.resolve() if args.resume else ROOT / 'data/colibri-investigation/pool-ab' / stamp
    out.mkdir(parents=True, exist_ok=bool(args.resume))
    save = helper.save
    if args.resume:
        provenance = json.loads((out/'provenance.json').read_text())
        check_resume_settings(provenance, settings)
        if provenance.get('image') != image_id:
            raise RuntimeError('resume immutable image mismatch')
        if provenance.get('sequence') != args.sequence:
            raise RuntimeError('resume sequence mismatch')
    source = ROOT / 'data/colibri-mtp-dev-control'
    original = helper.manifest(source)
    if not original:
        raise RuntimeError('missing control state')
    snapshot = out / 'snapshot'
    if not args.resume:
        shutil.copytree(source, snapshot)
        save(out/'snapshot-manifest.json', original)
    elif helper.manifest(snapshot) != original:
        raise RuntimeError('resume source/snapshot mismatch')
    state = out / 'working-state'
    save(out/(f'resume-{stamp}-image.json' if args.resume else 'image.json'), image_details)
    if comparison_details:
        save(out/'comparison-image.json', comparison_details)
    save(out/'model-metadata-NOT-content-hashes.json', [dict(name=p.name, bytes=p.stat().st_size,mtime_ns=p.stat().st_mtime_ns) for p in sorted((ROOT/'data/models').glob('Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-*.gguf'))])
    save(out/'host.json', {k: helper.cmd(cmd) for k,cmd in {'cpu':['lscpu'], 'kernel':['uname','-a'], 'containers':['docker','ps','--format','{{.Names}} {{.Image}}']}.items()})
    if not args.resume:
        save(out/'provenance.json', dict(experiment_settings=settings, sequence=args.sequence, process_plan=plan, telemetry=args.telemetry, telemetry_sha256=hashlib.sha256((ROOT/'scripts/colibri_telemetry.py').read_bytes()).hexdigest() if args.telemetry else None, script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), benchmark_sha256=hashlib.sha256((ROOT/'scripts/benchmark.py').read_bytes()).hexdigest(), image=image_id, note='Same snapshot restored to same path before every process. No page-cache flush, affinity, clock or power changes. Correctness short/decode, short warmup+3, decode warmup+3; no prefill. Thinking override absent. UUID corpus replayed across processes, fresh within each process.'))
    corpus = {case: [f'Benchmark request {uuid.uuid4()}; do not mention this marker.\n'+bench.PROMPTS[case] for _ in range(4)] for case in ('short','decode')}
    if args.resume:
        corpus = json.loads((out/'prompts.json').read_text())['throughput']
        save(out/f'resume-{stamp}.json', dict(script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), reason='Port preflight now uses SO_REUSEADDR to allow prior connection TIME_WAIT; no protocol change.'))
    else:
        save(out/'prompts.json', dict(correctness={k:bench.PROMPTS[k] for k in corpus}, throughput=corpus))
    key = secrets.token_urlsafe(32)
    active = None
    results = [r for r in json.loads((out/'results.json').read_text()) if r['status']=='completed'] if args.resume else []
    def stop():
        nonlocal active
        if active:
            try:
                helper.cmd(['docker','stop','-t','10',active], timeout=20)
            finally:
                helper.cmd(['docker','rm','-f',active], timeout=20)
                active = None
    def interrupted(*_):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    options = argparse.Namespace(temperature=0.0,max_tokens=192,save_text=True)
    client = bench.OpenAIClient('http://127.0.0.1:18080/v1',key,90)
    try:
        for i, process in enumerate(plan,1):
            profile = process['profile']
            process_image = process['image']
            if any(r['index']==i and r['profile']==profile for r in results):
                continue
            d = out / f'{i:02d}-{profile}'
            d.mkdir(exist_ok=bool(args.resume))
            result = dict(index=i,profile=profile,build=process['build'],image=process_image,status='starting')
            results.append(result)
            save(out/'results.json',results)
            with socket.socket() as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(('127.0.0.1',18080))
            if state.exists():
                shutil.rmtree(state)
            shutil.copytree(snapshot,state)
            before = helper.manifest(state)
            save(d/'pre-run-manifest.json',before)
            if before != original:
                raise RuntimeError('snapshot mismatch')
            env = process_environment(profile, args.gemv_sk, args.promote)
            save(d/'environment-public.json',env)
            active = f'colibri-pool-ab-{stamp}-{i}'
            run = ['docker','run','-d','--name',active,'--pull','never','--network','host','--init','--device','/dev/kfd','--device','/dev/dri','--ulimit','memlock=-1:-1','--ulimit','core=0:0','--shm-size','2g','--no-healthcheck']
            for gid in sorted({os.stat('/dev/kfd').st_gid,os.stat('/dev/dri/card1').st_gid}):
                run += ['--group-add',str(gid)]
            run += environment_arguments(env)
            model = '/state/'+helper.MODEL[:-5]+'.colibri'
            run += ['-e','COLI_API_KEY','-v',str(ROOT/'data/models')+':/models:ro','-v',str(state)+':/state','--entrypoint','bash',process_image,'-lc',f'ulimit -c 0; python3 ./coli import /models/{helper.MODEL} --out {model} --mode link --no-mtp && exec python3 ./coli serve --model {model} --ctx 8192 --ram 48 --host 127.0.0.1 --port 18080']
            save(d/'command.json',run)
            print(i,process['build'],profile,'starting',flush=True)
            telemetry = telemetry_module.Telemetry(d/'telemetry.jsonl') if telemetry_module else None
            if telemetry:
                telemetry.__enter__()
            try:
                launch = helper.cmd(run,env={**os.environ,'COLI_API_KEY':key})
                save(d/'launch.json',launch)
                if launch['returncode']:
                    raise RuntimeError('docker launch failed')
                started = time.monotonic()
                while True:
                    logs = helper.cmd(['docker','logs',active])
                    text = logs['stdout']+logs['stderr']
                    (d/'startup.log').write_text(text)
                    if helper.FAIL.search(text):
                        raise RuntimeError('engine fault during startup')
                    if time.monotonic()-started > args.startup_timeout:
                        raise TimeoutError('startup timeout')
                    try:
                        # Use a short discovery timeout, not generation timeout.
                        discovery = bench.OpenAIClient(client.base_url,key,2)
                        model_id = discovery.model(None)
                        break
                    except Exception:
                        time.sleep(3)
                result['startup_s'] = time.monotonic()-started
                print(i,profile,'ready',round(result['startup_s'],1),flush=True)
                report = dict(profile=profile,index=i,model=model_id,correctness=[],cases=[])
                with bench.ResourceMonitor(None) as monitor:
                    for case in ('short','decode'):
                        if telemetry: telemetry.mark('check-'+case)
                        r = client.stream_chat(model_id,bench.PROMPTS[case],options,{})
                        report['correctness'].append(dict(case=case,**r))
                        save(d/'measurements.json',report)
                        if r.get('error'):
                            raise RuntimeError('correctness request failed: '+r['error'])
                    logs = helper.cmd(['docker','logs',active])
                    text = logs['stdout']+logs['stderr']
                    (d/'pre-measurement.log').write_text(text)
                    if helper.FAIL.search(text):
                        raise RuntimeError('engine fault before measurement')
                    if args.require_auto_decision and profile == 'A':
                        if not re.search(r"a decode step's pooled experts (read by the device over the bus|on the CPU):", text):
                            raise RuntimeError('automatic pool decision not measured before timing')
                    for case in ('short','decode'):
                        group = dict(name=case,runs=[])
                        report['cases'].append(group)
                        for n,prompt in enumerate(corpus[case]):
                            if telemetry: telemetry.mark(case + ('-warmup' if n == 0 else '-run-' + str(n)))
                            r = client.stream_chat(model_id,prompt,options,{})
                            r.update(phase='warmup' if n==0 else 'run',run=n)
                            group['runs'].append(r)
                            bench.print_run(case,r['phase'],n,r)
                            report['resources'] = monitor.summary()
                            save(d/'measurements.json',report)
                            if r.get('error'):
                                raise RuntimeError('throughput request failed: '+r['error'])
                result['status']='completed'
            except Exception as exc:
                result.update(status='failed',error=str(exc))
            finally:
                if telemetry: telemetry.mark('cleanup')
                if active:
                    logs=helper.cmd(['docker','logs','--timestamps',active])
                    text = logs['stdout']+logs['stderr']
                    (d/'final.log').write_text(text)
                    if helper.FAIL.search(text):
                        result.update(status='failed',error='engine fault in final log')
                    save(d/'container-state.json',helper.cmd(['docker','inspect','--format','{{json .State}}',active]))
                    stop()
                if telemetry:
                    telemetry.__exit__(None, None, None)
                    result['telemetry_error'] = telemetry.error
                save(d/'post-run-manifest.json',helper.manifest(state))
                save(out/'results.json',results)
            print(i,profile,result['status'],result.get('error',''),flush=True)
            if result['status']!='completed':
                break  # No repeated failing startup/fault or fabricated comparisons.
    finally:
        stop()
        save(out/'source-integrity.json',dict(unchanged=helper.manifest(source)==original))
        save(out/'results.json',results)
        print('Artifacts:',out,flush=True)

if __name__=='__main__':
    main()
