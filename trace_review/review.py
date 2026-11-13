"""行動記録を、道具の台帳（権限区分）と承認の決まりに照らして点検する。"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict

HIGH_IMPACT = ("書き込み", "外部送信", "実行")
RULES = {
    "A01": ("高", "承認のない書き込み・送信・実行", "人の承認を経ずに、書き込み・外部送信・実行の道具が使われた", "ASI02, ASI09", "人間の判断の関与"),
    "A02": ("高", "却下された操作の実行", "承認で却下された後に、書き込み・外部送信・実行の道具が使われた", "ASI09, ASI10", "人間の判断の関与"),
    "A03": ("高", "台帳にない道具", "台帳（権限区分）に載っていない道具が使われた", "ASI02, ASI10", "アカウンタビリティ"),
    "A04": ("高", "失敗の後の書き込み・送信", "道具が失敗した後、同じ実行の中で書き込み・送信・実行を続けた", "ASI08 Cascading Failures", "安全性"),
    "A05": ("中", "同じ呼び出しの繰り返し", "同じ道具を同じ引数で繰り返し呼んでいる（堂々巡りの疑い）", "ASI08", "安全性"),
    "A06": ("中", "呼び出し回数の上限超え", "1回の実行で使った道具の数が上限を超えた", "ASI08, ASI10", "安全性"),
}


def _tier(policy: dict, tool: str) -> str | None:
    for tier, names in policy.get("tools", {}).items():
        if tool in names:
            return tier
    return None


def _args_digest(v) -> str:
    if v is None:
        return ""
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, sort_keys=True)
    try:
        s = json.dumps(json.loads(s), ensure_ascii=False, sort_keys=True)
    except (ValueError, TypeError):
        pass
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def review(spans: list[dict], policy: dict) -> dict:
    approvals = set(policy.get("approval_tools", []))
    attr = policy.get("approval_attribute", "app.approval.decision")
    scope = policy.get("approval_scope", "next")
    max_calls = int(policy.get("max_tool_calls_per_run", 20))
    max_repeat = int(policy.get("max_same_call_repeats", 3))
    by_trace = defaultdict(list)
    for s in spans:
        by_trace[s["trace"]].append(s)
    runs, findings = [], []
    for trace, items in by_trace.items():
        root = next((s for s in items if s["attrs"].get("gen_ai.operation.name") == "invoke_agent"), items[0])
        t0 = root["start"]
        tools = [s for s in items if s["attrs"].get("gen_ai.operation.name") == "execute_tool"]
        agent = root["attrs"].get("gen_ai.agent.name", root["name"])

        def add(rid, s, detail, _agent=agent, _trace=trace, _t0=t0):
            sev, title, why, owasp, guide = RULES[rid]
            findings.append({"ID": rid, "重さ": sev, "指摘": title, "実行": _trace[:8], "エージェント": _agent,
                             "経過秒": round((s["start"] - _t0) / 1e9, 1), "道具": s["attrs"].get("gen_ai.tool.name", ""),
                             "内容": detail, "理由": why, "OWASP": owasp, "AI事業者ガイドライン": guide})

        granted, rejected, failed = False, False, False
        seen, counted = defaultdict(int), defaultdict(bool)
        high = appr = err = 0
        for s in tools:
            name = s["attrs"].get("gen_ai.tool.name", "")
            if name in approvals:
                decision = str(s["attrs"].get(attr, "")).lower()
                granted, rejected = decision == "approved", decision == "rejected"
                appr += 1
                continue
            tier = _tier(policy, name)
            if tier is None:
                add("A03", s, f"{name}（権限区分なし）")
            elif tier in HIGH_IMPACT:
                high += 1
                if failed:
                    add("A04", s, f"{tier}：{name}")
                if rejected and not granted:
                    add("A02", s, f"{tier}：{name}")
                elif not granted:
                    add("A01", s, f"{tier}：{name}")
                if scope == "next":
                    granted, rejected = False, False
            key = (name, _args_digest(s["attrs"].get("gen_ai.tool.call.arguments")))
            seen[key] += 1
            if seen[key] > max_repeat and not counted[key]:
                counted[key] = True
                add("A05", s, f"{name} を {seen[key]} 回目" + (f"（引数のハッシュ {key[1]}）" if key[1] else "（引数の記録なし）"))
            if s["error"]:
                failed = True
                err += 1
        if len(tools) > max_calls:
            add("A06", tools[max_calls], f"{len(tools)} 回（上限 {max_calls}）")
        runs.append({"実行": trace[:8], "エージェント": agent, "道具の呼び出し": len(tools), "うち書き込み・送信・実行": high,
                     "承認": appr, "失敗": err, "所要秒": round((max(s["end"] for s in items) - t0) / 1e9, 1)})
    order = {"高": 0, "中": 1}
    return {"runs": runs, "findings": sorted(findings, key=lambda f: (f["実行"], f["経過秒"], order[f["重さ"]]))}


def to_markdown(result: dict) -> str:
    runs, fs = result["runs"], result["findings"]
    md = ["# 行動記録の点検結果", "", f"実行 {len(runs)} 件、道具の呼び出し {sum(r['道具の呼び出し'] for r in runs)} 回、"
          f"指摘 {len(fs)} 件（高 {sum(f['重さ'] == '高' for f in fs)}、中 {sum(f['重さ'] == '中' for f in fs)}）。", "",
          "## 実行ごとの集計", "| 実行 | エージェント | 道具の呼び出し | うち書き込み・送信・実行 | 承認 | 失敗 | 所要秒 |", "|---|---|---|---|---|---|---|"]
    for r in runs:
        cells = [r["実行"], r["エージェント"], r["道具の呼び出し"], r["うち書き込み・送信・実行"], r["承認"], r["失敗"], r["所要秒"]]
        md.append("| " + " | ".join(map(str, cells)) + " |")
    md += ["", "## 指摘", "| 重さ | ID | 実行 | 経過秒 | 指摘 | 内容 | 根拠 |", "|---|---|---|---|---|---|---|"]
    md += [f"| {f['重さ']} | {f['ID']} | {f['実行']} | {f['経過秒']} | {f['指摘']} | {f['内容']} | {f['OWASP']}／{f['AI事業者ガイドライン']} |" for f in fs]
    return "\n".join(md) + "\n"
