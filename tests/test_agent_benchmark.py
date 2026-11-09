import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from agent_benchmark import (  # noqa: E402
    BUGGY_SOURCE,
    OpenAIClient,
    SOURCE_FILENAME,
    TOOL_SCHEMAS,
    BenchmarkFixture,
    ToolError,
    extract_source,
    run_agent,
    run_coder,
)


FIXED_SOURCE = '''"""Statistics helpers for small data-quality reports."""


def median(values):
    """Return the median of values; raise ValueError when values is empty."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("median requires at least one value")
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2
'''


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self):
        return self.payload


def completion(content=None, tool_calls=None, usage=None):
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    response = {"choices": [{"message": message, "finish_reason": "stop"}]}
    if usage is not None:
        response["usage"] = usage
    return response


def tool_call(number, name, arguments):
    return {
        "id": f"call_{number}",
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def arguments():
    return argparse.Namespace(max_turns=8, max_tokens=768, temperature=0)


class ExtractionTests(unittest.TestCase):
    def test_raw_and_single_fenced_source(self):
        self.assertEqual(extract_source(FIXED_SOURCE), FIXED_SOURCE)
        self.assertEqual(extract_source("```python\n" + FIXED_SOURCE + "```\n"), FIXED_SOURCE)
        self.assertEqual(extract_source("```py\r\n" + FIXED_SOURCE.replace("\n", "\r\n") + "```"), FIXED_SOURCE)

    def test_explanations_and_multiple_patches_are_rejected(self):
        invalid = [
            "Here is the repair:\n" + FIXED_SOURCE,
            "Explanation\n```python\n" + FIXED_SOURCE + "```",
            "```python\n" + FIXED_SOURCE + "```\nThis fixes the bug.",
            "```python\n" + FIXED_SOURCE + "```\n```python\n" + FIXED_SOURCE + "```",
            "```python\n" + FIXED_SOURCE,  # missing closing fence
            "not valid Python !!!",
        ]
        for response in invalid:
            with self.subTest(response=response[:35]), self.assertRaises(ValueError):
                extract_source(response)


class FixtureTests(unittest.TestCase):
    def test_path_traversal_and_other_files_are_rejected(self):
        with BenchmarkFixture() as fixture:
            paths = [
                "../outside.py",
                "subdir/../../outside.py",
                "test_statistics_utils.py",
                str(fixture.root / "outside.py"),
            ]
            for path in paths:
                with self.subTest(path=path), self.assertRaises(ToolError):
                    fixture.read_file(path)
                with self.subTest(path=path, write=True), self.assertRaises(ToolError):
                    fixture.write_file(path, FIXED_SOURCE)
            self.assertEqual(fixture.source.read_text(encoding="utf-8"), BUGGY_SOURCE)
            self.assertEqual(fixture.read_file("./" + SOURCE_FILENAME), BUGGY_SOURCE)

    def test_source_size_is_capped(self):
        with BenchmarkFixture() as fixture:
            with self.assertRaises(ToolError):
                fixture.write_file(SOURCE_FILENAME, "x" * (64 * 1024 + 1))


class AgentBenchmarkTests(unittest.TestCase):
    def test_successful_agent_trajectory_uses_tools_and_passes(self):
        responses = [
            completion(tool_calls=[tool_call(1, "read_file", json.dumps({"path": SOURCE_FILENAME}))]),
            completion(tool_calls=[tool_call(2, "run_tests", "{}")]),
            completion(tool_calls=[tool_call(
                3, "write_file", json.dumps({"path": SOURCE_FILENAME, "content": FIXED_SOURCE}),
            )]),
            completion(
                tool_calls=[tool_call(4, "run_tests", "{}")],
                usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            ),
        ]
        client = OpenAIClient("http://unused/v1", None, 5)
        requests = []

        def fake_request(path, payload=None):
            requests.append((path, copy.deepcopy(payload)))
            return FakeResponse(responses.pop(0))

        client.request = fake_request
        result = run_agent(client, "test-model", arguments(), {}, "unique-marker")

        self.assertTrue(result["success"], result["error"])
        self.assertTrue(result["tests_passed"])
        self.assertIsNone(result["error"])
        self.assertEqual(result["http_requests"], 4)
        self.assertEqual(result["tool_call_count"], 4)
        self.assertEqual(result["tool_calls_by_name"], {
            "read_file": 1, "write_file": 1, "run_tests": 2,
        })
        self.assertEqual(result["invalid_tool_calls"], 0)
        self.assertEqual(result["total_tokens"], 14)
        self.assertEqual(result["source_sha256"], hashlib.sha256(FIXED_SOURCE.encode()).hexdigest())
        self.assertNotIn("content", result)
        self.assertNotIn("reasoning_content", result)
        self.assertEqual(len(requests), 4)
        for path, payload in requests:
            self.assertEqual(path, "/chat/completions")
            self.assertIs(payload["stream"], False)
            self.assertEqual(payload["tools"], TOOL_SCHEMAS)
        final_messages = requests[-1][1]["messages"]
        tool_messages = [message for message in final_messages if message["role"] == "tool"]
        self.assertEqual(len(tool_messages), 3)
        self.assertTrue(all(message["tool_call_id"] for message in tool_messages))
        self.assertTrue(all(message["name"] in {"read_file", "write_file", "run_tests"}
                            for message in tool_messages))

    def test_malformed_tool_json_fails_gracefully(self):
        client = OpenAIClient("http://unused/v1", None, 5)
        client.request = lambda *_: FakeResponse(completion(
            tool_calls=[tool_call(1, "write_file", "{not-json")],
        ))
        result = run_agent(client, "test-model", arguments(), {}, "unique-marker")
        self.assertFalse(result["success"])
        self.assertFalse(result["tests_passed"])
        self.assertEqual(result["invalid_tool_calls"], 1)
        self.assertEqual(result["http_requests"], 1)
        self.assertIn("malformed tool argument JSON", result["error"])
        self.assertEqual(result["source_sha256"], hashlib.sha256(BUGGY_SOURCE.encode()).hexdigest())

    def test_max_turns_bounds_agent(self):
        client = OpenAIClient("http://unused/v1", None, 5)
        client.request = lambda *_: FakeResponse(completion(
            tool_calls=[tool_call(1, "read_file", json.dumps({"path": SOURCE_FILENAME}))],
        ))
        args = arguments()
        args.max_turns = 2
        result = run_agent(client, "test-model", args, {}, "unique-marker")
        self.assertFalse(result["success"])
        self.assertEqual(result["http_requests"], 2)
        self.assertIn("max_turns=2", result["error"])

    def test_coder_test_failure_is_recorded(self):
        client = OpenAIClient("http://unused/v1", None, 5)
        client.request = lambda *_: FakeResponse(completion(
            content=BUGGY_SOURCE,
            usage={"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
        ))
        result = run_coder(client, "test-model", arguments(), {}, "unique-marker")
        self.assertFalse(result["success"])
        self.assertFalse(result["tests_passed"])
        self.assertEqual(result["http_requests"], 1)
        self.assertEqual(result["tool_call_count"], 0)
        self.assertEqual(result["total_tokens"], 25)
        self.assertIn("tests failed", result["error"])

    def test_coder_accepts_one_fence_and_passes(self):
        client = OpenAIClient("http://unused/v1", None, 5)
        client.request = lambda *_: FakeResponse(completion(content="```python\n" + FIXED_SOURCE + "```"))
        result = run_coder(client, "test-model", arguments(), {}, "unique-marker")
        self.assertTrue(result["success"], result["error"])
        self.assertTrue(result["tests_passed"])
        self.assertEqual(result["source_sha256"], hashlib.sha256(FIXED_SOURCE.encode()).hexdigest())

    def test_fixed_test_runner_never_uses_model_command(self):
        with BenchmarkFixture() as fixture:
            with mock.patch("agent_benchmark.subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = "OK"
                run.return_value.stderr = ""
                fixture.run_tests()
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["python3", "-m", "unittest"])
        self.assertIs(run.call_args.kwargs["shell"], False)
        self.assertNotIn("sh", command)


if __name__ == "__main__":
    unittest.main()
