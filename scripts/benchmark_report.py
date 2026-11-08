#!/usr/bin/env python3
"""Render one or more benchmark.py JSON files as a compact Markdown table."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def number(value, digits=2):
    return "—" if not isinstance(value, (int, float)) else f"{value:.{digits}f}"


def render(paths: list[Path]) -> str:
    lines = [
        "# OpenAI API benchmark",
        "",
        "Все значения ниже — медианы успешных streaming-запросов после warm-up. "
        "`TTFT` включает reasoning; `Answer` — первый видимый `content`. "
        "`Decode` использует `usage.completion_tokens` (либо явно обозначенный в JSON "
        "достигнутый length budget); `Gross` включает prefill и весь запрос.",
        "",
        "| Backend | Model | Case | Runs | TTFT, s | Answer, s | Decode, tok/s | Gross, tok/s | Total, s | VRAM max, GiB |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        resources = report.get("resources") or {}
        vram = resources.get("mem_info_vram_used_max")
        vram_gib = vram / 1024**3 if isinstance(vram, int) else None
        for case in report.get("cases", []):
            summary = case.get("summary") or {}
            lines.append(
                "| {backend} | {model} | {case} | {ok}/{total} | {ttft} | {answer} | "
                "{decode} | {gross} | {total_s} | {vram} |".format(
                    backend=report.get("backend", path.stem),
                    model=report.get("model", "—"),
                    case=case.get("name", "—"),
                    ok=summary.get("successful", 0), total=summary.get("runs", 0),
                    ttft=number(summary.get("ttft_s_median"), 3),
                    answer=number(summary.get("content_ttft_s_median"), 3),
                    decode=number(summary.get("decode_tps_median")),
                    gross=number(summary.get("gross_tps_median")),
                    total_s=number(summary.get("total_s_median"), 3),
                    vram=number(vram_gib),
                )
            )
    lines += ["", "## Source files", ""]
    lines += [f"- `{path}`" for path in paths]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    text = render(args.files)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
