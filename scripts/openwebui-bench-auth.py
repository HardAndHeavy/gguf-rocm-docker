#!/usr/bin/env python3
"""Create/reuse credentials only inside the disposable benchmark Open WebUI.

The generated dotenv file is mode 0600 and gitignored. No password, session
Token or API key is printed. The script never reads the user's real UI database.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import time
import urllib.error
import urllib.request

from benchmark import parse_env_file


def request(base: str, path: str, payload: dict | None = None,
            token: str | None = None, timeout: float = 15) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        base.rstrip("/") + path, data=body, headers=headers,
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:3300")
    parser.add_argument("--env-file", type=Path,
                        default=Path("data/open-webui-bench-auth.env"))
    parser.add_argument("--startup-timeout", type=float, default=300)
    args = parser.parse_args()

    values = parse_env_file(args.env_file)
    password = values.get("BENCH_WEBUI_PASSWORD") or secrets.token_urlsafe(24)
    deadline = time.monotonic() + args.startup_timeout
    token = None
    while time.monotonic() < deadline:
        try:
            config = request(args.url, "/api/config", timeout=5)
            if not isinstance(config, dict):
                raise RuntimeError("unexpected /api/config response")
            # A fresh database has no users. Existing benchmark credentials use
            # signin, avoiding the deliberately disabled public signup route.
            try:
                result = request(args.url, "/api/v1/auths/signin", {
                    "email": "benchmark@localhost", "password": password,
                })
            except urllib.error.HTTPError as error:
                if error.code not in (400, 401):
                    raise
                result = request(args.url, "/api/v1/auths/signup", {
                    "name": "Benchmark", "email": "benchmark@localhost",
                    "password": password, "profile_image_url": "/user.png",
                })
            token = result.get("token")
            if not token:
                raise RuntimeError("authentication returned no token")
            break
        except (OSError, ValueError, RuntimeError) as error:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"benchmark Open WebUI did not become ready: {error}"
                ) from error
            time.sleep(2)
    if not token:
        raise RuntimeError("benchmark Open WebUI authentication timed out")

    try:
        result = request(args.url, "/api/v1/auths/api_key", token=token)
        api_key = result.get("api_key")
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        result = request(args.url, "/api/v1/auths/api_key", {}, token=token)
        api_key = result.get("api_key")
    if not api_key:
        raise RuntimeError("Open WebUI returned no benchmark API key")

    # Verify the key on the exact route family used by the benchmark. Model
    # discovery may legitimately return an empty list before backend warmup.
    request(args.url, "/api/models", token=api_key)
    atomic_write(
        args.env_file,
        "# Disposable Open WebUI benchmark credentials; do not commit.\n"
        f"BENCH_WEBUI_PASSWORD={password}\n"
        f"OPENWEBUI_API_KEY={api_key}\n",
    )
    print(f"Benchmark Open WebUI is ready; credentials saved to {args.env_file} (0600)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
