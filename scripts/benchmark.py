#!/usr/bin/env python3
"""Benchmark an OpenAI-compatible streaming endpoint using only the stdlib.

The client deliberately bypasses Open WebUI. It records response headers, the
first reasoning/answer token, exact server token usage, throughput and GPU/RAM
samples. Every measured prompt starts with a unique marker to defeat exact
prefix-cache reuse between runs.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid


PROMPTS = {
    "short": "Ответь одним словом: какой элемент обозначается символом Fe?",
    "decode": (
        "Напиши подробный технический дневник тестирования большой языковой "
        "модели на AMD GPU: последовательно опиши подготовку, холодный запуск, "
        "prefill, decode, контроль памяти, повторяемость и типичные ошибки. "
        "Пиши развёрнуто, не менее 1200 слов, без сокращения ответа."
    ),
    "prefill": (
        "Ниже дан журнал из нескольких независимых наблюдений.\n"
        + "\n".join(
            f"{i:02d}. На итерации {i} проверили стабильность драйвера, "
            f"размещение весов, очередь запросов и целостность результата; "
            f"показатель контрольной партии равен {i * 37 % 101}."
            for i in range(1, 65)
        )
        + "\nСоставь подробный аналитический отчёт по всем наблюдениям, "
          "выдели закономерности и предложи план дальнейших проверок. "
          "Не менее 1000 слов."
    ),
}


def parse_env_file(path: Path) -> dict[str, str]:
    """Read the small Compose dotenv subset without executing shell code."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            # Compose permits an unquoted inline comment preceded by whitespace.
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def read_number(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


class ResourceMonitor:
    """Low-frequency host telemetry; samples never pretend to be engine metrics."""

    def __init__(self, gpu_device: str | None, interval: float = 0.25):
        self.gpu_device = Path(gpu_device) if gpu_device else self.find_gpu()
        self.interval = interval
        self.samples: list[dict[str, int | float]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def find_gpu() -> Path | None:
        candidates = sorted(Path("/sys/class/drm").glob("card[0-9]*/device"))
        candidates = [p for p in candidates if (p / "mem_info_vram_total").is_file()]
        return candidates[0] if len(candidates) == 1 else None

    def snapshot(self) -> dict[str, int | float]:
        sample: dict[str, int | float] = {"time": time.monotonic()}
        if self.gpu_device:
            for metric in ("mem_info_vram_total", "mem_info_vram_used", "gpu_busy_percent"):
                value = read_number(self.gpu_device / metric)
                if value is not None:
                    sample[metric] = value
        try:
            fields = {}
            for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
                key, value = line.split(":", 1)
                fields[key] = int(value.strip().split()[0]) * 1024
            sample["ram_available"] = fields["MemAvailable"]
            sample["ram_total"] = fields["MemTotal"]
        except (OSError, KeyError, ValueError):
            pass
        return sample

    def _run(self) -> None:
        while not self._stop.is_set():
            self.samples.append(self.snapshot())
            self._stop.wait(self.interval)

    def __enter__(self):
        self.samples.append(self.snapshot())
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.samples.append(self.snapshot())

    def summary(self) -> dict[str, int | float | str | None]:
        result: dict[str, int | float | str | None] = {
            "gpu_device": str(self.gpu_device) if self.gpu_device else None,
            "sample_count": len(self.samples),
        }
        for key in ("mem_info_vram_total", "mem_info_vram_used", "gpu_busy_percent",
                    "ram_available", "ram_total"):
            values = [int(s[key]) for s in self.samples if key in s]
            if values:
                result[key + "_min"] = min(values)
                result[key + "_max"] = max(values)
                result[key + "_median"] = int(statistics.median(values))
        return result


class OpenAIClient:
    def __init__(self, base_url: str, api_key: str | None, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if api_key:
            self.headers["Authorization"] = "Bearer " + api_key

    def request(self, path: str, payload: dict | None = None):
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        request = urllib.request.Request(
            self.base_url + path, data=body, headers=self.headers,
            method="GET" if body is None else "POST",
        )
        return urllib.request.urlopen(request, timeout=self.timeout)

    def model(self, requested: str | None) -> str:
        if requested:
            return requested
        with self.request("/models") as response:
            payload = json.load(response)
        models = payload.get("data") or []
        if not models or not models[0].get("id"):
            raise RuntimeError("GET /v1/models returned no usable model id")
        return models[0]["id"]

    def stream_chat(self, model: str, prompt: str, args: argparse.Namespace,
                    extra: dict) -> dict:
        messages = [{"role": "user", "content": prompt}]
        payload = {
            "model": model,
            "messages": messages,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            **extra,
        }
        # Callers may override optional generation defaults, but not the metric protocol.
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        started = time.monotonic()
        result: dict = {
            "model": model,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "request": {k: v for k, v in payload.items() if k != "messages"},
        }
        content_parts: list[str] = []
        raw_content_events: list[tuple[float, str]] = []
        reasoning_parts: list[str] = []
        token_events = 0
        event_times: list[float] = []
        first_token = first_reasoning = first_content = last_token = None
        first_event = None
        usage = None
        finish_reason = None
        queue_wait_ms = None
        try:
            response = self.request("/chat/completions", payload)
            with response:
                result["headers_s"] = time.monotonic() - started
                result["http_status"] = response.status
                queue_wait_ms = response.headers.get("x-colibri-queue-wait-ms")
                for raw in response:
                    now = time.monotonic()
                    if not raw.startswith(b"data:"):
                        continue
                    data = raw[5:].strip()
                    if data == b"[DONE]":
                        break
                    event = json.loads(data)
                    if first_event is None:
                        first_event = now - started
                    if event.get("error"):
                        raise RuntimeError(event["error"])
                    if isinstance(event.get("usage"), dict):
                        usage = event["usage"]
                    for choice in event.get("choices") or []:
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
                        delta = choice.get("delta") or {}
                        # /v1/completions is intentionally not mixed into chat metrics.
                        reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
                        content = delta.get("content") or ""
                        if reasoning:
                            reasoning_parts.append(reasoning)
                            if first_reasoning is None:
                                first_reasoning = now - started
                        if content:
                            content_parts.append(content)
                            raw_content_events.append((now - started, content))
                            if first_content is None:
                                first_content = now - started
                        if reasoning or content:
                            if first_token is None:
                                first_token = now - started
                            last_token = now - started
                            token_events += 1
                            event_times.append(now)
            result["total_s"] = time.monotonic() - started
        except urllib.error.HTTPError as error:
            result["total_s"] = time.monotonic() - started
            result["http_status"] = error.code
            result["error"] = error.read().decode("utf-8", "replace")[:4000]
        except Exception as error:
            result["total_s"] = time.monotonic() - started
            result["error"] = f"{type(error).__name__}: {error}"

        # llama-cpp-python exposes reasoning as literal <think> markup inside
        # content instead of reasoning_content. Keep TTFT at the first token,
        # but do not mislabel that markup as the visible answer. Event times
        # are retained so the first text after </think> gets its own TTFT.
        raw_content = "".join(content_parts)
        if not reasoning_parts and raw_content.lstrip().startswith("<think>"):
            opening = raw_content.index("<think>")
            close = raw_content.find("</think>", opening + len("<think>"))
            reasoning_end = close if close >= 0 else len(raw_content)
            visible_start = close + len("</think>") if close >= 0 else len(raw_content)
            reasoning_text = raw_content[opening + len("<think>"):reasoning_end]
            visible_text = raw_content[visible_start:]
            reasoning_parts = [reasoning_text]
            content_parts = [visible_text]
            first_reasoning = raw_content_events[0][0] if raw_content_events else None
            first_content = None
            offset = 0
            for event_time, text in raw_content_events:
                end = offset + len(text)
                if end > visible_start and offset < len(raw_content):
                    first_content = event_time
                    break
                offset = end
            result["inline_reasoning"] = True
            result["raw_content_sha256"] = hashlib.sha256(raw_content.encode()).hexdigest()
        else:
            result["inline_reasoning"] = False

        result.update({
            "first_event_s": first_event,
            "ttft_s": first_token,
            "reasoning_ttft_s": first_reasoning,
            "content_ttft_s": first_content,
            "last_token_s": last_token,
            "token_events": token_events,
            "finish_reason": finish_reason,
            "usage": usage,
            "queue_wait_ms": float(queue_wait_ms) if queue_wait_ms is not None else None,
            "content_chars": sum(map(len, content_parts)),
            "reasoning_chars": sum(map(len, reasoning_parts)),
            "content_sha256": hashlib.sha256("".join(content_parts).encode()).hexdigest(),
        })
        completion_tokens = (usage or {}).get("completion_tokens")
        completion_tokens_source = "stream_usage" if isinstance(completion_tokens, int) else None
        if not isinstance(completion_tokens, int) and finish_reason == "length":
            # OpenAI length semantics prove that the actual generation budget
            # was reached. This is exact, unlike treating SSE chunks as tokens.
            completion_tokens = payload["max_tokens"]
            completion_tokens_source = "finish_reason_length"
        result["completion_tokens"] = completion_tokens
        result["completion_tokens_source"] = completion_tokens_source
        if isinstance(completion_tokens, int):
            result["gross_tps"] = completion_tokens / result["total_s"] if result["total_s"] > 0 else None
            decode_seconds = ((last_token - first_token)
                              if first_token is not None and last_token is not None else None)
            result["decode_window_s"] = decode_seconds
            result["decode_tps"] = (
                (completion_tokens - 1) / decode_seconds
                if decode_seconds and decode_seconds > 0 and completion_tokens > 1 else None
            )
        gaps = [(b - a) * 1000 for a, b in zip(event_times, event_times[1:])]
        result["event_gap_p50_ms"] = percentile(gaps, 0.50)
        result["event_gap_p95_ms"] = percentile(gaps, 0.95)
        if args.save_text:
            result["content"] = "".join(content_parts)
            result["reasoning_content"] = "".join(reasoning_parts)
        return result


def aggregate(runs: list[dict]) -> dict:
    successful = [r for r in runs if not r.get("error")]
    result: dict = {"runs": len(runs), "successful": len(successful), "failed": len(runs) - len(successful)}
    for key in ("total_s", "headers_s", "ttft_s", "content_ttft_s", "gross_tps",
                "decode_tps", "event_gap_p95_ms"):
        values = [r[key] for r in successful if isinstance(r.get(key), (int, float))]
        if values:
            result[key + "_median"] = statistics.median(values)
            result[key + "_min"] = min(values)
            result[key + "_max"] = max(values)
    tokens = [r["completion_tokens"] for r in successful if isinstance(r.get("completion_tokens"), int)]
    if tokens:
        result["completion_tokens_median"] = statistics.median(tokens)
    return result


def print_run(case: str, phase: str, index: int, result: dict) -> None:
    if result.get("error"):
        print(f"{case:8s} {phase} {index}: ERROR {result['error']}", flush=True)
        return
    def fmt(value, digits=3):
        return "n/a" if not isinstance(value, (int, float)) else f"{value:.{digits}f}"
    print(
        f"{case:8s} {phase} {index}: total={fmt(result.get('total_s'))}s "
        f"TTFT={fmt(result.get('ttft_s'))}s answer={fmt(result.get('content_ttft_s'))}s "
        f"tokens={result.get('completion_tokens')} gross={fmt(result.get('gross_tps'), 2)}tok/s "
        f"decode={fmt(result.get('decode_tps'), 2)}tok/s finish={result.get('finish_reason')}",
        flush=True,
    )


def write_outputs(output: Path, report: dict) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    csv_path = output.with_suffix(".csv")
    fields = [
        "case", "phase", "run", "model", "total_s", "headers_s", "ttft_s",
        "reasoning_ttft_s", "content_ttft_s", "completion_tokens",
        "completion_tokens_source", "inline_reasoning", "gross_tps",
        "decode_tps", "event_gap_p50_ms", "event_gap_p95_ms", "finish_reason",
        "content_chars", "reasoning_chars", "error",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for case in report["cases"]:
            for run in case["runs"]:
                writer.writerow({"case": case["name"], **run})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True, help="Human-readable label saved with the result")
    parser.add_argument("--url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--model", help="Model id; default: first id returned by /models")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--api-key-env", default="COLI_API_KEY")
    parser.add_argument("--case", action="append", choices=sorted(PROMPTS),
                        help="Repeatable; default: short and decode")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=192)
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--gpu-device", help="sysfs device path; auto-detected when unambiguous")
    parser.add_argument("--request-json", default="{}", help="Extra OpenAI request fields as a JSON object")
    parser.add_argument("--save-text", action="store_true", help="Include generated text in JSON (off by default)")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.runs < 1 or args.warmups < 0 or args.max_tokens < 1:
        parser.error("--runs and --max-tokens must be positive; --warmups cannot be negative")
    try:
        extra = json.loads(args.request_json)
        if not isinstance(extra, dict):
            raise ValueError("not an object")
    except ValueError as error:
        parser.error(f"--request-json must be a JSON object: {error}")
    env = parse_env_file(args.env_file)
    api_key = os.environ.get(args.api_key_env) or env.get(args.api_key_env)
    client = OpenAIClient(args.url, api_key, args.timeout)
    try:
        model = client.model(args.model)
    except Exception as error:
        parser.exit(2, f"Cannot discover model at {args.url}: {type(error).__name__}: {error}\n")
    cases = args.case or ["short", "decode"]
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_backend = "".join(c if c.isalnum() or c in "-_" else "-" for c in args.backend)
    output = args.output or Path("data/benchmarks") / f"{timestamp}-{safe_backend}.json"
    report = {
        "schema_version": 1,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "backend": args.backend,
        "url": args.url,
        "model": model,
        "parameters": {
            "cases": cases, "runs": args.runs, "warmups": args.warmups,
            "max_tokens": args.max_tokens, "temperature": args.temperature,
            "request": extra, "unique_prompt_prefix": True,
        },
        "host": {"platform": platform.platform(), "python": platform.python_version()},
        "cases": [],
    }
    print(f"Backend={args.backend} model={model} output={output}", flush=True)
    failed = 0
    with ResourceMonitor(args.gpu_device) as monitor:
        for case_name in cases:
            case_report = {"name": case_name, "runs": []}
            report["cases"].append(case_report)
            for phase, count in (("warmup", args.warmups), ("run", args.runs)):
                for index in range(1, count + 1):
                    marker = f"Benchmark request {uuid.uuid4()}; do not mention this marker.\n"
                    result = client.stream_chat(model, marker + PROMPTS[case_name], args, extra)
                    result["phase"] = phase
                    result["run"] = index
                    print_run(case_name, phase, index, result)
                    if phase == "run":
                        case_report["runs"].append(result)
                        failed += bool(result.get("error"))
                    case_report["summary"] = aggregate(case_report["runs"])
                    # Preserve partial results after every request, including a later timeout.
                    report["resources"] = monitor.summary()
                    write_outputs(output, report)
    report["resources"] = monitor.summary()
    write_outputs(output, report)
    print(json.dumps({c["name"]: c["summary"] for c in report["cases"]}, ensure_ascii=False, indent=2))
    print(f"Saved {output} and {output.with_suffix('.csv')}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
