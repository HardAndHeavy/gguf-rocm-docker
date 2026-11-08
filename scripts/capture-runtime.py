#!/usr/bin/env python3
"""Capture non-secret container/image memory and host GPU telemetry as JSON."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import subprocess


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("container")
    parser.add_argument("output", type=Path)
    parser.add_argument("--gpu-device", default="/sys/class/drm/card1/device")
    args = parser.parse_args()

    inspected = json.loads(command("docker", "inspect", args.container))[0]
    image = json.loads(command("docker", "image", "inspect", inspected["Image"]))[0]
    stats = json.loads(command(
        "docker", "stats", "--no-stream", "--format", "{{json .}}", args.container
    ))
    cgroup = {}
    for name in ("memory.current", "memory.peak", "memory.stat"):
        result = subprocess.run(
            ["docker", "exec", args.container, "sh", "-c",
             f"cat /sys/fs/cgroup/{name} 2>/dev/null"],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            cgroup[name] = result.stdout.strip()

    gpu = {}
    device = Path(args.gpu_device)
    for name in ("mem_info_vram_total", "mem_info_vram_used", "gpu_busy_percent"):
        try:
            gpu[name] = int((device / name).read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            pass

    report = {
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "container": args.container,
        "image": inspected["Config"]["Image"],
        "image_id": inspected["Image"],
        "repo_digests": image.get("RepoDigests"),
        "image_labels": image["Config"].get("Labels"),
        "command": inspected["Config"].get("Cmd"),
        "docker_stats": stats,
        "cgroup": cgroup,
        "gpu_sysfs": gpu,
        "note": "Docker MemUsage excludes inactive file pages; cgroup memory.current includes them.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({
        "output": str(args.output), "memory": stats.get("MemUsage"),
        "cgroup_current": cgroup.get("memory.current"),
        "cgroup_peak": cgroup.get("memory.peak"), "gpu": gpu,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
