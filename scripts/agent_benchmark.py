#!/usr/bin/env python3
"""Reproducible local coding/agent smoke benchmark using only the stdlib.

This is a small comparative smoke/functional benchmark for OpenAI-compatible
local servers. It is NOT SWE-bench, does not measure repository-scale software
engineering, and must not be presented as a substitute for that benchmark.

The agent case exposes only read_file, write_file and run_tests. File tools can
access one source file in a fresh temporary fixture, and run_tests always uses a
fixed ``python3 -m unittest`` command; model-supplied commands are never run.
Generated answer/reasoning text is deliberately omitted from JSON and CSV.
The temporary fixture prevents repository writes, but it is not a security
sandbox: generated Python is executed by unittest as the current user, so run
this benchmark only with models you trust.
"""
from __future__ import annotations

import argparse
import ast
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid


SOURCE_FILENAME = "statistics_utils.py"
TEST_FILENAME = "test_statistics_utils.py"
MAX_SOURCE_BYTES = 64 * 1024
MAX_TEST_OUTPUT_CHARS = 12_000
TEST_TIMEOUT_SECONDS = 30

BUGGY_SOURCE = '''"""Statistics helpers for small data-quality reports."""


def median(values):
    """Return the median of values; raise ValueError when values is empty."""
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle]
'''

VISIBLE_TESTS = '''import unittest

from statistics_utils import median


class MedianTests(unittest.TestCase):
    def test_odd_number_of_values(self):
        self.assertEqual(median([9, 1, 4]), 4)

    def test_even_number_of_values(self):
        self.assertEqual(median([10, 2, 8, 4]), 6)

    def test_duplicates_and_input_is_unchanged(self):
        values = [3, 1, 3, 2]
        self.assertEqual(median(values), 2.5)
        self.assertEqual(values, [3, 1, 3, 2])

    def test_empty_input(self):
        with self.assertRaises(ValueError):
            median([])


if __name__ == "__main__":
    unittest.main()
'''

AGENT_PROMPT = (
    "Fix the buggy Python module in the temporary coding fixture. You must use "
    "the provided tools: first read_file to inspect the module and run_tests to "
    "observe the failure, then write_file with a complete replacement and "
    "run_tests again. Finish as soon as the tests pass; do not merely describe "
    "a patch. The only file accessible to file tools is " + SOURCE_FILENAME +
    ". The visible tests below are already installed and are run by the "
    "fixed run_tests tool.\n\nVISIBLE TESTS:\n```python\n" + VISIBLE_TESTS +
    "\n```\n"
)

CODER_PROMPT = (
    "Repair the following Python module so every visible test passes. Return "
    "ONLY the complete replacement Python source file, with no explanation and "
    "no Markdown fences. Preserve the public function and its documented "
    "behavior.\n\nCURRENT SOURCE (" + SOURCE_FILENAME + "):\n```python\n" +
    BUGGY_SOURCE + "\n```\n\nVISIBLE TESTS (" + TEST_FILENAME + "):\n"
    "```python\n" + VISIBLE_TESTS + "\n```\n"
)

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the fixture source file. No other path is allowed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": SOURCE_FILENAME},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Replace the complete fixture source file (maximum 65536 UTF-8 bytes).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": SOURCE_FILENAME},
                    "content": {"type": "string", "description": "Complete Python source"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run the fixed visible unittest suite; accepts no command or other arguments.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
]


class ToolError(ValueError):
    """A safe, reportable tool argument or fixture error."""


class TrajectoryError(RuntimeError):
    """A malformed model response that ends the current trajectory."""


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
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


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
            self.base_url + path,
            data=body,
            headers=self.headers,
            method="GET" if body is None else "POST",
        )
        return urllib.request.urlopen(request, timeout=self.timeout)

    def model(self, requested: str | None) -> str:
        if requested:
            return requested
        with self.request("/models") as response:
            payload = json.load(response)
        models = payload.get("data") or []
        if not models or not isinstance(models[0], dict) or not models[0].get("id"):
            raise RuntimeError("GET /models returned no usable model id")
        return str(models[0]["id"])

    def chat(
        self,
        model: str,
        messages: list[dict],
        args: argparse.Namespace,
        extra: dict,
        tools: list[dict] | None = None,
    ) -> dict:
        # Extra backend fields may override generation defaults, but never the
        # benchmark's messages, safe tools, model, or non-streaming protocol.
        payload = {
            "model": model,
            "messages": messages,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            **extra,
        }
        payload.update({"model": model, "messages": messages, "stream": False})
        if tools is not None:
            payload["tools"] = tools
        with self.request("/chat/completions", payload) as response:
            result = json.load(response)
        if not isinstance(result, dict):
            raise RuntimeError("Chat completion response was not a JSON object")
        return result


class BenchmarkFixture:
    """One disposable fixture; only ``source`` is accessible to model tools."""

    def __init__(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="local-coding-benchmark-")
        self.root = Path(self._temporary.name).resolve()
        self.source = self.root / SOURCE_FILENAME
        self.tests = self.root / TEST_FILENAME
        self.source.write_text(BUGGY_SOURCE, encoding="utf-8")
        self.tests.write_text(VISIBLE_TESTS, encoding="utf-8")
        self._resolved_source = self.source.resolve()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._temporary.cleanup()

    def resolve_source(self, path: str) -> Path:
        if not isinstance(path, str) or not path or "\x00" in path:
            raise ToolError("path must be a non-empty string")
        supplied = Path(path)
        if ".." in supplied.parts:
            raise ToolError("parent-directory traversal is not allowed")
        candidate = supplied if supplied.is_absolute() else self.root / supplied
        try:
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError) as error:
            raise ToolError(f"cannot resolve path: {error}") from error
        if resolved != self._resolved_source:
            raise ToolError(f"only {SOURCE_FILENAME} is accessible")
        return self.source

    def read_file(self, path: str) -> str:
        source = self.resolve_source(path)
        try:
            if source.stat().st_size > MAX_SOURCE_BYTES:
                raise ToolError("source file exceeds the size limit")
            content = source.read_text(encoding="utf-8")
        except UnicodeError as error:
            raise ToolError(f"source is not valid UTF-8: {error}") from error
        if len(content.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ToolError("source file exceeds the size limit")
        return content

    def write_file(self, path: str, content: str) -> None:
        source = self.resolve_source(path)
        if not isinstance(content, str):
            raise ToolError("content must be a string")
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_SOURCE_BYTES:
            raise ToolError("source file exceeds the 65536-byte limit")
        source.write_bytes(encoded)

    @staticmethod
    def _timeout_text(value) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", "replace")
        return value or ""

    def run_tests(self) -> dict:
        # Deliberately no model-controlled command, cwd, environment or options.
        command = [
            "python3", "-m", "unittest", "discover", "-s", ".",
            "-p", "test_*.py", "-v",
        ]
        environment = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
        }
        try:
            completed = subprocess.run(
                command,
                cwd=self.root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=TEST_TIMEOUT_SECONDS,
                check=False,
                shell=False,
            )
            output = (completed.stdout or "") + (completed.stderr or "")
            return {
                "passed": completed.returncode == 0,
                "returncode": completed.returncode,
                "timed_out": False,
                "output": output[-MAX_TEST_OUTPUT_CHARS:],
            }
        except subprocess.TimeoutExpired as error:
            output = self._timeout_text(error.stdout) + self._timeout_text(error.stderr)
            return {
                "passed": False,
                "returncode": None,
                "timed_out": True,
                "output": output[-MAX_TEST_OUTPUT_CHARS:],
            }


def extract_source(response_text: str) -> str:
    """Return raw Python or exactly one Python fence; reject mixed explanations."""
    if not isinstance(response_text, str) or not response_text.strip():
        raise ValueError("empty response")
    if len(response_text.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("response exceeds the source size limit")
    text = response_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if "```" in text:
        lines = text.split("\n")
        if len(lines) < 3 or not re.fullmatch(r"```(?:python|py)?[ \t]*", lines[0], re.I):
            raise ValueError("expected exactly one complete Python fenced block")
        if lines[-1].strip() != "```":
            raise ValueError("text outside the fenced block or a missing closing fence")
        if any(line.strip().startswith("```") for line in lines[1:-1]):
            raise ValueError("multiple fenced blocks or patches are not allowed")
        source = "\n".join(lines[1:-1]) + "\n"
    else:
        source = text + "\n"
    try:
        ast.parse(source, filename=SOURCE_FILENAME)
    except (SyntaxError, ValueError) as error:
        raise ValueError(f"response is not one valid Python source file: {error}") from error
    return source


def execute_tool(fixture: BenchmarkFixture, name: str, arguments: dict) -> dict:
    if name == "read_file":
        if set(arguments) != {"path"}:
            raise ToolError("read_file requires exactly path")
        return {"ok": True, "content": fixture.read_file(arguments["path"])}
    if name == "write_file":
        if set(arguments) != {"path", "content"}:
            raise ToolError("write_file requires exactly path and content")
        fixture.write_file(arguments["path"], arguments["content"])
        return {"ok": True, "bytes": fixture.source.stat().st_size}
    if name == "run_tests":
        if arguments:
            raise ToolError("run_tests accepts no arguments")
        return {"ok": True, **fixture.run_tests()}
    raise ToolError("unknown tool")


def new_result(phase: str, run: int, prompt: str) -> dict:
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return {
        "phase": phase,
        "run": run,
        "wall_time_s": 0.0,
        "http_requests": 0,
        "usage": usage,
        **usage,
        "tool_call_count": 0,
        "tool_calls_by_name": {"read_file": 0, "write_file": 0, "run_tests": 0},
        "invalid_tool_calls": 0,
        "tests_passed": False,
        "success": False,
        "error": None,
        "source_sha256": None,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }


def add_usage(result: dict, response: dict) -> None:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return
    for key in result["usage"]:
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result["usage"][key] += value
            result[key] += value


def response_message(response: dict) -> dict:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RuntimeError("response contained no usable first choice")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise RuntimeError("response choice contained no message object")
    return message


def source_hash(fixture: BenchmarkFixture) -> str | None:
    try:
        return hashlib.sha256(fixture.source.read_bytes()).hexdigest()
    except OSError:
        return None


def run_agent(
    client: OpenAIClient,
    model: str,
    args: argparse.Namespace,
    extra: dict,
    marker: str,
    phase: str = "run",
    run: int = 1,
) -> dict:
    prompt = marker + "\n" + AGENT_PROMPT
    result = new_result(phase, run, prompt)
    started = time.monotonic()
    with BenchmarkFixture() as fixture:
        messages = [{"role": "user", "content": prompt}]

        def malformed(message: str):
            result["invalid_tool_calls"] += 1
            raise TrajectoryError(message)

        try:
            for _turn in range(1, args.max_turns + 1):
                result["http_requests"] += 1
                response = client.chat(model, messages, args, extra, TOOL_SCHEMAS)
                add_usage(result, response)
                message = response_message(response)
                calls = message.get("tool_calls")
                if not isinstance(calls, list) or not calls:
                    raise TrajectoryError("assistant returned no tool calls before tests passed")
                messages.append({
                    "role": "assistant",
                    "content": message.get("content"),
                    "tool_calls": calls,
                })
                for call in calls:
                    result["tool_call_count"] += 1
                    if not isinstance(call, dict) or call.get("type") != "function":
                        malformed("malformed tool call object")
                    call_id = call.get("id")
                    function = call.get("function")
                    if not isinstance(call_id, str) or not call_id or not isinstance(function, dict):
                        malformed("tool call requires an id and function object")
                    name = function.get("name")
                    raw_arguments = function.get("arguments")
                    if name not in ("read_file", "write_file", "run_tests"):
                        malformed("model requested an unavailable tool")
                    if not isinstance(raw_arguments, str):
                        malformed("tool arguments were not a JSON string")
                    try:
                        arguments = json.loads(raw_arguments)
                    except (json.JSONDecodeError, RecursionError) as error:
                        malformed(f"malformed tool argument JSON: {error}")
                    if not isinstance(arguments, dict):
                        malformed("tool arguments must decode to an object")
                    result["tool_calls_by_name"][name] += 1
                    try:
                        tool_result = execute_tool(fixture, name, arguments)
                    except (ToolError, OSError, UnicodeError) as error:
                        result["invalid_tool_calls"] += 1
                        tool_result = {"ok": False, "error": str(error)}
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": name,
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    })
                    if name == "run_tests" and tool_result.get("passed") is True:
                        result["tests_passed"] = True
                        result["success"] = True
                        break
                if result["success"]:
                    break
            else:
                result["error"] = f"reached max_turns={args.max_turns} without passing tests"
        except Exception as error:
            # A bad trajectory is data, not a benchmark crash. Do not retain
            # response text, reasoning, arguments or authorization headers.
            result["error"] = f"{type(error).__name__}: {error}"
        finally:
            result["source_sha256"] = source_hash(fixture)
    result["wall_time_s"] = time.monotonic() - started
    return result


def run_coder(
    client: OpenAIClient,
    model: str,
    args: argparse.Namespace,
    extra: dict,
    marker: str,
    phase: str = "run",
    run: int = 1,
) -> dict:
    prompt = marker + "\n" + CODER_PROMPT
    result = new_result(phase, run, prompt)
    started = time.monotonic()
    with BenchmarkFixture() as fixture:
        try:
            result["http_requests"] = 1
            response = client.chat(model, [{"role": "user", "content": prompt}], args, extra)
            add_usage(result, response)
            content = response_message(response).get("content")
            if not isinstance(content, str):
                raise ValueError("coder response content was not a string")
            try:
                source = extract_source(content)
            except ValueError as error:
                raise ValueError(f"source extraction failed: {error}") from error
            fixture.write_file(SOURCE_FILENAME, source)
            test_result = fixture.run_tests()
            result["tests_passed"] = test_result["passed"]
            result["success"] = test_result["passed"]
            if not result["success"]:
                if test_result["timed_out"]:
                    result["error"] = f"tests timed out after {TEST_TIMEOUT_SECONDS} seconds"
                else:
                    result["error"] = f"tests failed with exit status {test_result['returncode']}"
        except Exception as error:
            result["error"] = f"{type(error).__name__}: {error}"
        finally:
            result["source_sha256"] = source_hash(fixture)
    result["wall_time_s"] = time.monotonic() - started
    return result


def aggregate(runs: list[dict]) -> dict:
    successful = sum(run.get("success") is True for run in runs)
    summary = {
        "runs": len(runs),
        "successful": successful,
        "failed": len(runs) - successful,
        "success_rate": successful / len(runs) if runs else 0.0,
    }
    for key in (
        "wall_time_s", "http_requests", "prompt_tokens", "completion_tokens",
        "total_tokens", "tool_call_count", "invalid_tool_calls",
    ):
        values = [
            run[key] for run in runs
            if isinstance(run.get(key), (int, float)) and not isinstance(run.get(key), bool)
        ]
        if values:
            summary[key + "_median"] = statistics.median(values)
    return summary


def write_outputs(output: Path, report: dict) -> None:
    """Atomically replace both reports, including after partial benchmarks."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)

    csv_path = output.with_suffix(".csv")
    csv_temporary = csv_path.with_suffix(csv_path.suffix + ".tmp")
    fields = [
        "case", "phase", "run", "wall_time_s", "http_requests", "prompt_tokens",
        "completion_tokens", "total_tokens", "tool_call_count",
        "read_file_calls", "write_file_calls", "run_tests_calls",
        "invalid_tool_calls", "tests_passed", "success", "error", "source_sha256",
        "prompt_sha256",
    ]
    with csv_temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for case in report["cases"]:
            for phase in ("warmups", "runs"):
                for run in case[phase]:
                    by_name = run["tool_calls_by_name"]
                    writer.writerow({
                        "case": case["name"],
                        **run,
                        "read_file_calls": by_name["read_file"],
                        "write_file_calls": by_name["write_file"],
                        "run_tests_calls": by_name["run_tests"],
                    })
    csv_temporary.replace(csv_path)


def redact_request_fields(value, key: str = ""):
    """Retain reproducible extras without persisting obvious secret values."""
    if isinstance(value, dict):
        return {str(k): redact_request_fields(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_request_fields(item) for item in value]
    if re.search(r"(?:api[_-]?key|authorization|password|secret|token)", key, re.I):
        return "<redacted>"
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True, help="Human-readable backend label saved in the report")
    parser.add_argument("--url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--api-key-env", default="COLI_API_KEY")
    parser.add_argument("--model", help="Model id; default: first id returned by /models")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument("--max-tokens", type=int, default=768)
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--output", type=Path, help="Default: data/benchmarks/TIMESTAMP-BACKEND.json")
    parser.add_argument("--case", action="append", choices=("agent", "coder"),
                        help="Repeatable; default: agent and coder")
    parser.add_argument("--request-json", default="{}", help="Extra OpenAI request fields as a JSON object")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.runs < 1 or args.warmups < 0 or args.max_turns < 1 or args.max_tokens < 1:
        parser.error("--runs, --max-turns and --max-tokens must be positive; --warmups cannot be negative")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        extra = json.loads(args.request_json)
        if not isinstance(extra, dict):
            raise ValueError("not an object")
    except (json.JSONDecodeError, ValueError) as error:
        parser.error(f"--request-json must be a JSON object: {error}")

    env = parse_env_file(args.env_file)
    api_key = os.environ.get(args.api_key_env) or env.get(args.api_key_env)
    client = OpenAIClient(args.url, api_key, args.timeout)
    try:
        model = client.model(args.model)
    except Exception as error:
        parser.exit(2, f"Cannot discover model at {args.url}: {type(error).__name__}: {error}\n")

    cases = args.case or ["agent", "coder"]
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
            "cases": cases,
            "runs": args.runs,
            "warmups": args.warmups,
            "max_turns": args.max_turns,
            "max_tokens": args.max_tokens,
            "temperature": args.temperature,
            "timeout": args.timeout,
            "request": redact_request_fields(extra),
            "unique_run_markers": True,
            "test_command": "python3 -m unittest discover -s . -p test_*.py -v",
        },
        "host": {"platform": platform.platform(), "python": platform.python_version()},
        "cases": [],
        "summary": aggregate([]),
    }
    print(f"Backend={args.backend} model={model} output={output}", flush=True)
    failed = 0
    for case_name in cases:
        case_report = {"name": case_name, "warmups": [], "runs": [], "summary": aggregate([])}
        report["cases"].append(case_report)
        runner = run_agent if case_name == "agent" else run_coder
        for phase, count in (("warmup", args.warmups), ("run", args.runs)):
            for index in range(1, count + 1):
                marker = f"Benchmark run marker {uuid.uuid4()}; do not repeat or discuss this marker."
                result = runner(client, model, args, extra, marker, phase, index)
                destination = case_report["warmups" if phase == "warmup" else "runs"]
                destination.append(result)
                if phase == "run":
                    failed += not result["success"]
                    case_report["summary"] = aggregate(case_report["runs"])
                measured = [r for case in report["cases"] for r in case["runs"]]
                report["summary"] = aggregate(measured)
                write_outputs(output, report)
                status = "PASS" if result["success"] else "FAIL"
                print(
                    f"{case_name:5s} {phase:6s} {index}: {status} "
                    f"wall={result['wall_time_s']:.3f}s requests={result['http_requests']} "
                    f"tools={result['tool_call_count']} invalid={result['invalid_tool_calls']} "
                    f"error={result['error'] or '-'}",
                    flush=True,
                )
    print(json.dumps({case["name"]: case["summary"] for case in report["cases"]}, indent=2))
    print(f"Saved {output} and {output.with_suffix('.csv')}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
