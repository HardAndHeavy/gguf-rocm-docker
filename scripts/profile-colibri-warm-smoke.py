#!/usr/bin/env python3
"""Bounded owned-container warmed-engine attach smoke; no production changes."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/file)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--image', required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--tokens', type=int, choices=[16,64], default=16)
    ap.add_argument('--expanded', action='store_true')
    ap.add_argument('--scratch-trace', action='store_true', help='Add ROCr scratch allocation/free events')
    ap.add_argument('--scratch-limit', choices=['1073741824'], help='Explicit HSA_SCRATCH_SINGLE_LIMIT before engine startup; default unset')
    args=ap.parse_args()
    h=load('direct', 'check-colibri-mtp-direct.py'); b=load('bench', 'benchmark.py')
    image, details=h.resolve_image(args.image)
    out=args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    source=ROOT/'data/colibri-mtp-dev-control'; original=h.manifest(source)
    state=out/'state'; shutil.copytree(source,state)
    h.save(out/'pre-run-manifest.json',h.manifest(state)); h.save(out/'image.json',details)
    trace=out/'trace'; trace.mkdir()
    # Reuse the verified SK0 profile's actual Docker launch, replacing only own mounts/name/image.
    template=ROOT/'data/colibri-investigation/pool-ab/20261113-144141/01-B'
    cmd=json.loads((template/'command.json').read_text())
    name='colibri-prof-smoke-'+time.strftime('%Y%m%d-%H%M%S')
    cmd[cmd.index('--name')+1]=name
    for i,v in enumerate(cmd):
        if v.endswith(':/state'): cmd[i]=str(state)+':/state'
    cmd[cmd.index('--entrypoint')+2]=image
    cmd[2:2]=['--cap-add=SYS_PTRACE','-e','ROCP_TOOL_ATTACH=1','-v',str(trace)+':/trace']
    public_env={**json.loads((template/'environment-public.json').read_text()),'ROCP_TOOL_ATTACH':'1'}
    if args.scratch_limit:
        cmd[2:2]=['-e', 'HSA_SCRATCH_SINGLE_LIMIT='+args.scratch_limit]
        public_env['HSA_SCRATCH_SINGLE_LIMIT']=args.scratch_limit
    h.save(out/'command.json',cmd)
    h.save(out/'environment-public.json',public_env)
    key=secrets.token_urlsafe(32)
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
    client=b.OpenAIClient('http://127.0.0.1:18080/v1',key,90)
    profiler=None
    telemetry=load('telemetry','colibri_telemetry.py').Telemetry(out/'telemetry.jsonl')
    telemetry.__enter__()
    try:
        launch=h.cmd(cmd,env={**os.environ,'COLI_API_KEY':key});h.save(out/'launch.json',launch)
        if launch['returncode']: raise RuntimeError('launch failed')
        start=time.monotonic()
        while True:
            logs=h.cmd(['docker','logs',name]); text=logs['stdout']+logs['stderr']; (out/'startup.log').write_text(text)
            if h.FAIL.search(text): raise RuntimeError('engine fault')
            if time.monotonic()-start>480: raise TimeoutError('startup')
            try:
                model=b.OpenAIClient(client.base_url,key,2).model(None);break
            except Exception:time.sleep(3)
        options=argparse.Namespace(temperature=0.0,max_tokens=args.tokens,save_text=True)
        prompt=b.PROMPTS['decode']
        for label in ['warmup','unprofiled']:
            telemetry.mark(label)
            r=client.stream_chat(model,prompt,options,{})
            h.save(out/(label+'.json'),r)
            if r.get('error'):raise RuntimeError(label+' request failed')
        inspection=h.cmd(['docker','exec',name,'bash','-lc', 'for p in /proc/[0-9]*; do [ "$(cat "$p/comm" 2>/dev/null)" = qwen38 ] && echo "${p##*/}"; done; true'])
        pids=inspection['stdout'].split()
        if len(pids)!=1:raise RuntimeError('expected one actual qwen38 PID')
        pid=pids[0]
        check=h.cmd(['docker','exec',name,'bash','-lc',f'readlink /proc/{pid}/exe; cat /proc/{pid}/task/*/comm; grep -E "rocprofiler|rocattach" /proc/{pid}/maps'])
        h.save(out/'engine-inspection.json',check)
        if '/app/c/qwen38' not in check['stdout'] or 'rocp-bg-attach' not in check['stdout']:raise RuntimeError('engine attach prerequisite absent')
        prof=['docker','exec',name,'/opt/rocm/bin/rocprofv3','--pid',pid,'--attach-children=false','--attach-duration-msec','15000','--attach-sync-output=true','--kernel-trace','--stats','--output-config','--output-format','csv','json','--output-directory','/trace','--output-file','smoke']
        if args.expanded:
            prof += ['--hip-runtime-trace','--memory-copy-trace','--memory-allocation-trace']
        if args.scratch_trace:
            prof += ['--scratch-memory-trace']
        h.save(out/'profiler-command.json',prof)
        with (out/'profiler.log').open('w') as f:
            profiler=subprocess.Popen(prof,stdout=f,stderr=subprocess.STDOUT)
            start=time.monotonic()
            while True:
                text=(out/'profiler.log').read_text()
                if ':: success' in text:break
                if profiler.poll() is not None:raise RuntimeError('profiler ended before successful attach')
                if time.monotonic()-start>60:raise TimeoutError('attach readiness')
                time.sleep(.25)
            telemetry.mark('profiled')
            request_start=time.time_ns()
            r=client.stream_chat(model,prompt,options,{})
            h.save(out/'profiled.json',dict(request_start_epoch_ns=request_start,request_end_epoch_ns=time.time_ns(),response=r))
            if r.get('error'):raise RuntimeError('profiled request failed')
            rc=profiler.wait(timeout=180)
            h.save(out/'profiler-exit.json',dict(returncode=rc))
            if rc:raise RuntimeError('profiler failed')
        h.save(out/'result.json',dict(status='capture-completed-needs-record-validation'))
    except Exception as e:
        h.save(out/'result.json',dict(status='failed',error=str(e)))
        raise
    finally:
        if profiler and profiler.poll() is None:
            # Give bounded capture a chance to finish/detach normally before owned engine cleanup.
            try:profiler.wait(timeout=180)
            except subprocess.TimeoutExpired:profiler.terminate();profiler.wait(timeout=10)
        logs=h.cmd(['docker','logs',name]);(out/'final.log').write_text(logs['stdout']+logs['stderr'])
        h.cmd(['docker','stop','-t','10',name],timeout=20);h.cmd(['docker','rm','-f',name],timeout=20)
        telemetry.__exit__(None,None,None)
        h.save(out/'source-integrity.json',dict(unchanged=h.manifest(source)==original))
        h.save(out/'final-check.json',dict(fault_signature=bool(h.FAIL.search(logs['stdout']+logs['stderr'])),telemetry_error=telemetry.error))

if __name__=='__main__': main()
