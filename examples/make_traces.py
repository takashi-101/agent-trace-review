"""見本の行動記録（OTLP/JSON）を作る。架空の「窓口問い合わせエージェント」の2回の実行。"""
import json
from pathlib import Path

T0 = 1_794_800_000_000_000_000  # 起点（ナノ秒）


def attr(k, v):
    if isinstance(v, bool):
        return {"key": k, "value": {"boolValue": v}}
    if isinstance(v, int):
        return {"key": k, "value": {"intValue": str(v)}}
    return {"key": k, "value": {"stringValue": v}}


def run(trace, steps, agent="madoguchi-agent"):
    spans = [{"traceId": trace, "spanId": trace[:15] + "0", "name": f"invoke_agent {agent}", "kind": 1,
              "startTimeUnixNano": str(T0), "endTimeUnixNano": str(T0 + (len(steps) + 1) * 2_000_000_000),
              "attributes": [attr("gen_ai.operation.name", "invoke_agent"), attr("gen_ai.agent.name", agent)], "status": {}}]
    for i, (tool, args, extra, error) in enumerate(steps, start=1):
        a = [attr("gen_ai.operation.name", "execute_tool"), attr("gen_ai.tool.name", tool), attr("gen_ai.tool.type", "function"),
             attr("gen_ai.tool.call.id", f"call_{trace[:4]}_{i}")]
        if args is not None:
            a.append(attr("gen_ai.tool.call.arguments", json.dumps(args, ensure_ascii=False)))
        a += [attr(k, v) for k, v in extra.items()]
        spans.append({"traceId": trace, "spanId": f"{trace[:12]}{i:04d}", "parentSpanId": trace[:15] + "0",
                      "name": f"execute_tool {tool}", "kind": 1, "startTimeUnixNano": str(T0 + i * 2_000_000_000),
                      "endTimeUnixNano": str(T0 + i * 2_000_000_000 + 800_000_000), "attributes": a,
                      "status": {"code": 2, "message": "timeout"} if error else {}})
    return spans


good = run("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", [
    ("search_faq", {"q": "住民票 郵送 期間"}, {}, False),
    ("get_record", {"id": "R-1024"}, {}, False),
    ("request_human_approval", {"action": "send_email"}, {"app.approval.decision": "approved"}, False),
    ("send_email", {"to": "（記録しない）"}, {}, False),
])
bad = run("f0e1d2c3b4a5968778695a4b3c2d1e0f", [
    *[("search_faq", {"q": "転入 手続き 必要書類"}, {}, False)] * 5,
    ("update_record", {"id": "R-2048", "status": "回答済み"}, {}, False),
    ("request_human_approval", {"action": "send_email"}, {"app.approval.decision": "rejected"}, False),
    ("send_email", {"to": "（記録しない）"}, {}, False),
    ("export_csv", {"path": "out.csv"}, {}, True),
    ("send_email", {"to": "（記録しない）"}, {}, False),
    ("delete_all_records", None, {}, False),
])
doc = {"resourceSpans": [{"resource": {"attributes": [attr("service.name", "madoguchi-agent")]},
                          "scopeSpans": [{"scope": {"name": "example"}, "spans": good + bad}]}]}
Path(__file__).with_name("traces.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
