import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from benchmark import OpenAIClient, aggregate, parse_env_file, percentile  # noqa: E402


class FakeResponse:
    status = 200
    headers = {"x-colibri-queue-wait-ms": "12.5"}

    def __init__(self, events):
        self.lines = [b"data: " + json.dumps(event).encode() + b"\n\n" for event in events]
        self.lines.append(b"data: [DONE]\n\n")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def __iter__(self):
        for line in self.lines:
            time.sleep(0.001)
            yield line


class BenchmarkTests(unittest.TestCase):
    def test_dotenv_is_not_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "# comment\nPLAIN=value\nQUOTED='a b'\nINLINE=value # comment\n"
                "COMMAND=$(touch /tmp/must-not-exist)\nEMPTY=\n",
                encoding="utf-8",
            )
            values = parse_env_file(path)
        self.assertEqual(values["PLAIN"], "value")
        self.assertEqual(values["QUOTED"], "a b")
        self.assertEqual(values["INLINE"], "value")
        self.assertEqual(values["COMMAND"], "$(touch /tmp/must-not-exist)")
        self.assertEqual(values["EMPTY"], "")

    def test_percentile_interpolates(self):
        self.assertEqual(percentile([], 0.95), None)
        self.assertEqual(percentile([1, 2, 3, 4], 0.5), 2.5)
        self.assertAlmostEqual(percentile([1, 2, 3, 4], 0.95), 3.85)

    def test_stream_metrics_include_reasoning_and_answer_separately(self):
        client = OpenAIClient("http://unused/v1", None, 5)
        events = [
            {"choices": [{"delta": {"role": "assistant"}}]},
            {"choices": [{"delta": {"reasoning_content": "think"}}]},
            {"choices": [{"delta": {"content": "answer"}}]},
            {"choices": [{"delta": {"content": "!"}}], "usage": None},
            {"choices": [], "usage": {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11}},
        ]
        client.request = lambda *_: FakeResponse(events)
        args = argparse.Namespace(max_tokens=10, temperature=0, save_text=False)
        result = client.stream_chat("test-model", "unique prompt", args, {})
        self.assertNotIn("error", result)
        self.assertEqual(result["completion_tokens"], 3)
        self.assertEqual(result["reasoning_chars"], 5)
        self.assertEqual(result["content_chars"], 7)
        self.assertIsNotNone(result["ttft_s"])
        self.assertGreaterEqual(result["content_ttft_s"], result["reasoning_ttft_s"])
        self.assertEqual(result["queue_wait_ms"], 12.5)
        self.assertGreater(result["decode_tps"], 0)
        self.assertNotIn("content", result)

    def test_inline_think_is_not_visible_answer(self):
        client = OpenAIClient("http://unused/v1", None, 5)
        events = [
            {"choices": [{"delta": {"content": "<think>private"}}]},
            {"choices": [{"delta": {"content": " thought</think>visible"}}]},
            {"choices": [{"delta": {"content": " answer"}, "finish_reason": "stop"}]},
        ]
        client.request = lambda *_: FakeResponse(events)
        args = argparse.Namespace(max_tokens=10, temperature=0, save_text=True)
        result = client.stream_chat("test-model", "unique prompt", args, {})
        self.assertTrue(result["inline_reasoning"])
        self.assertEqual(result["reasoning_content"], "private thought")
        self.assertEqual(result["content"], "visible answer")
        self.assertIsNone(result["completion_tokens"])
        self.assertGreater(result["content_ttft_s"], result["reasoning_ttft_s"])

    def test_length_budget_is_exact_without_stream_usage(self):
        client = OpenAIClient("http://unused/v1", None, 5)
        events = [
            {"choices": [{"delta": {"content": "<think>still thinking"}}]},
            {"choices": [{"delta": {"content": " more"}, "finish_reason": "length"}]},
        ]
        client.request = lambda *_: FakeResponse(events)
        args = argparse.Namespace(max_tokens=4, temperature=0, save_text=False)
        result = client.stream_chat("test-model", "unique prompt", args, {})
        self.assertEqual(result["completion_tokens"], 4)
        self.assertEqual(result["completion_tokens_source"], "finish_reason_length")
        self.assertIsNone(result["content_ttft_s"])
        self.assertGreater(result["decode_tps"], 0)

    def test_aggregate_ignores_failed_runs(self):
        summary = aggregate([
            {"total_s": 2, "ttft_s": 0.2, "gross_tps": 50, "completion_tokens": 100},
            {"total_s": 4, "ttft_s": 0.4, "gross_tps": 50, "completion_tokens": 200},
            {"error": "timeout", "total_s": 10},
        ])
        self.assertEqual(summary["runs"], 3)
        self.assertEqual(summary["successful"], 2)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["total_s_median"], 3)
        self.assertEqual(summary["completion_tokens_median"], 150)


if __name__ == "__main__":
    unittest.main()
