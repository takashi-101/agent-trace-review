"""使い方：python -m trace_review 記録.json ... --policy policy.json [--out 結果.md] [--fail-on 高]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import otlp, review


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="trace_review", description="AIエージェントの行動記録から承認漏れや暴走を見つける")
    p.add_argument("files", nargs="+", help="OTLP/JSON の記録")
    p.add_argument("--policy", required=True, help="道具の権限区分と承認の決まりを書いたJSON")
    p.add_argument("--out", help="結果のMarkdownの保存先")
    p.add_argument("--fail-on", choices=["高", "中"])
    a = p.parse_args(argv)
    spans = [s for f in a.files for s in otlp.load(f)]
    result = review.review(spans, json.loads(Path(a.policy).read_text(encoding="utf-8")))
    md = review.to_markdown(result)
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
    print(md)
    if a.fail_on:
        limit = {"高": 0, "中": 1}[a.fail_on]
        return 1 if any({"高": 0, "中": 1}[f["重さ"]] <= limit for f in result["findings"]) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
