#!/usr/bin/env python3
"""Real inference smoke test, run inside the Colibri container (stdlib only)."""
import json
import os
import time
import urllib.request

url = "http://127.0.0.1:8080/v1"
headers = {"Authorization": "Bearer " + os.environ["COLI_API_KEY"],
           "Content-Type": "application/json"}

def request(path, payload=None):
    req = urllib.request.Request(url + path, headers=headers,
                                 data=None if payload is None else json.dumps(payload).encode())
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.load(response)

model = request("/models")["data"][0]["id"]
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
