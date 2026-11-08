#!/usr/bin/env python3
"""Manage the isolated Open WebUI benchmark sidecar without sourcing dotenv files."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys

from benchmark import parse_env_file


CONFIG = Path("data/open-webui-bench.env")
COMPOSE = Path("compose.bench-webui.yaml")
PROJECT = "gguf-rocm-bench-ui"


def write_config(values: dict[str, str]) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG.with_suffix(".tmp")
    temporary.write_text(
        "# Disposable benchmark UI configuration; no real chats/uploads.\n"
        + "".join(f"{key}={values[key]}\n" for key in sorted(values)),
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(CONFIG)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("up", "down", "auth"))
    parser.add_argument("--backend-url", help="Container URL, e.g. http://colibri:8080/v1")
    parser.add_argument("--backend-key-env", default="COLI_API_KEY")
    parser.add_argument("--port", default="3300")
    parser.add_argument("--network", default="gguf-rocm_default")
    args = parser.parse_args()

    saved = parse_env_file(CONFIG)
    port = args.port if args.action == "up" else saved.get("BENCH_WEBUI_PORT", args.port)
    secret = saved.get("BENCH_WEBUI_SECRET") or secrets.token_urlsafe(32)
    backend_url = args.backend_url or saved.get("BENCH_BACKEND_URL", "http://localhost:8080/v1")
    if args.action == "up":
        key = parse_env_file(Path(".env")).get(args.backend_key_env, "")
        if not key and args.backend_key_env != "LLAMA_API_KEY":
            parser.error(f"{args.backend_key_env} is absent/empty in .env")
        if not args.backend_url:
            parser.error("--backend-url is required for up")
        write_config({
            "BENCH_BACKEND_URL": backend_url,
            "BENCH_BACKEND_NETWORK": args.network,
            "BENCH_WEBUI_PORT": port,
            "BENCH_WEBUI_SECRET": secret,
        })
        # llama-server ignores this placeholder; its host port is loopback-only.
        backend_key = key or "llama-server-no-auth"
    else:
        # Compose interpolates required variables even for down/auth. Do not
        # persist or print a backend key merely to tear down the sidecar.
        backend_key = "not-used-by-this-command"

    environment = {
        **os.environ,
        "BENCH_BACKEND_URL": backend_url,
        "BENCH_BACKEND_API_KEY": backend_key,
        "BENCH_BACKEND_NETWORK": saved.get("BENCH_BACKEND_NETWORK", args.network),
        "BENCH_WEBUI_PORT": port,
        "BENCH_WEBUI_SECRET": secret,
    }
    if args.action == "auth":
        return subprocess.run([
            sys.executable, "scripts/openwebui-bench-auth.py",
            "--url", f"http://127.0.0.1:{port}",
        ]).returncode
    command = ["docker", "compose", "-p", PROJECT, "-f", str(COMPOSE)]
    command += ["up", "-d"] if args.action == "up" else ["down", "--remove-orphans"]
    return subprocess.run(command, env=environment).returncode


if __name__ == "__main__":
    sys.exit(main())
