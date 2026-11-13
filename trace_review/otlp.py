"""OTLP/JSON（OpenTelemetryの標準の書き出し形式）を読み、スパンの一覧にする。"""
from __future__ import annotations

import json
from pathlib import Path

ERROR = {2, "2", "STATUS_CODE_ERROR"}


def _value(v: dict):
    for k in ("stringValue", "boolValue", "doubleValue"):
        if k in v:
            return v[k]
    if "intValue" in v:
        return int(v["intValue"])
    if "arrayValue" in v:
        return [_value(x) for x in v["arrayValue"].get("values", [])]
    return None


def _attrs(items) -> dict:
    return {a["key"]: _value(a.get("value", {})) for a in items or []}


def load(path: str) -> list[dict]:
    """1ファイルに1つのJSON、または1行に1つのJSON（Collectorのfile exporter）を読む。"""
    text = Path(path).read_text(encoding="utf-8")
    try:
        docs = [json.loads(text)]
    except json.JSONDecodeError:
        docs = [json.loads(x) for x in text.splitlines() if x.strip()]
    spans = []
    for doc in docs:
        for rs in doc.get("resourceSpans", []):
            res = _attrs((rs.get("resource") or {}).get("attributes"))
            for ss in rs.get("scopeSpans", []):
                for s in ss.get("spans", []):
                    spans.append({
                        "trace": s.get("traceId", ""), "span": s.get("spanId", ""), "parent": s.get("parentSpanId", ""),
                        "name": s.get("name", ""), "start": int(s.get("startTimeUnixNano", 0)), "end": int(s.get("endTimeUnixNano", 0)),
                        "error": (s.get("status") or {}).get("code") in ERROR, "attrs": _attrs(s.get("attributes")),
                        "service": res.get("service.name", ""),
                    })
    return sorted(spans, key=lambda x: (x["trace"], x["start"]))
