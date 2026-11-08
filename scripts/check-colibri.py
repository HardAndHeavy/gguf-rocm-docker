#!/usr/bin/env python3
"""Real inference smoke test, run inside the Colibri container (stdlib only)."""
import json
import os
import time
import urllib.request

url = "http://127.0.0.1:8080/v1"
headers = {"Authorization": "Bearer " + os.environ["COLI_API_KEY"],
           "Content-Type": "application/json"}
startup_timeout = float(os.environ.get("COLIBRI_SMOKE_STARTUP_TIMEOUT", "600"))
request_timeout = float(os.environ.get("COLIBRI_SMOKE_REQUEST_TIMEOUT", "300"))


def request(path, payload=None, timeout=request_timeout):
    req = urllib.request.Request(url + path, headers=headers,
                                 data=None if payload is None else json.dumps(payload).encode())
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


# The TCP healthcheck intentionally stays responsive while the engine is busy.
# Consequently healthy can precede the end of expert warmstart/host-pool setup:
# wait for the actual API instead of racing it with a single /models request.
deadline = time.monotonic() + startup_timeout
while True:
    try:
        timeout = min(10.0, max(1.0, deadline - time.monotonic()))
        model = request("/models", timeout=timeout)["data"][0]["id"]
        break
    except (OSError, KeyError, IndexError, TypeError) as error:
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Inference API was not ready within {startup_timeout:g}s") from error
        print(f"Waiting for inference API: {error}", flush=True)
        time.sleep(2)

start = time.monotonic()
result = request("/chat/completions", {
    "model": model,
    "messages": [{"role": "user", "content": "Сколько будет 2+2? Ответь только числом."}],
    "temperature": 0,
    "max_tokens": 512,
    "stream": False,
})
elapsed = time.monotonic() - start
choice = result["choices"][0]
answer = choice["message"]["content"].strip()
assert answer == "4", f"Unexpected answer: {answer!r}"
assert choice["finish_reason"] == "stop", choice
print(json.dumps({"model": model, "answer": answer, "seconds": round(elapsed, 3),
                  "usage": result.get("usage")}, ensure_ascii=False))
