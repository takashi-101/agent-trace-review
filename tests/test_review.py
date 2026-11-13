import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trace_review import __main__ as cli  # noqa: E402
from trace_review import otlp, review  # noqa: E402

TRACES = ROOT / "examples" / "traces.json"
POLICY = json.loads((ROOT / "examples" / "policy.json").read_text(encoding="utf-8"))


def _result(policy=POLICY):
    return review.review(otlp.load(str(TRACES)), policy)


def _ids(result, run):
    return [(f["ID"], f["道具"]) for f in result["findings"] if f["実行"] == run]


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.r = _result()

    def test_good_run_has_no_findings(self):
        self.assertEqual(_ids(self.r, "a1b2c3d4"), [])

    def test_each_rule_fires_on_the_bad_run(self):
        got = set(_ids(self.r, "f0e1d2c3"))
        expected = {("A05", "search_faq"), ("A01", "update_record"), ("A02", "send_email"), ("A01", "export_csv"),
                    ("A04", "send_email"), ("A01", "send_email"), ("A03", "delete_all_records"), ("A06", "delete_all_records")}
        self.assertEqual(got, expected)

    def test_run_summary(self):
        bad = next(x for x in self.r["runs"] if x["実行"] == "f0e1d2c3")
        self.assertEqual((bad["道具の呼び出し"], bad["うち書き込み・送信・実行"], bad["承認"], bad["失敗"]), (11, 4, 1, 1))

    def test_approval_scope_run_covers_later_calls(self):
        spans = otlp.load(str(TRACES))
        good = [s for s in spans if s["trace"].startswith("a1b2")]
        extra = copy.deepcopy(good[-1])
        extra["start"] += 1_000_000_000
        policy = {**POLICY, "approval_scope": "run"}
        self.assertEqual(review.review(good + [extra], policy)["findings"], [])
        self.assertEqual(review.review(good + [extra], POLICY)["findings"][0]["ID"], "A01")

    def test_arguments_are_never_printed(self):
        md = review.to_markdown(self.r)
        self.assertNotIn("転入", md)
        self.assertIn("引数のハッシュ", md)


class LoaderTest(unittest.TestCase):
    def test_jsonl_and_string_status_code(self):
        doc = json.loads(TRACES.read_text(encoding="utf-8"))
        rs = doc["resourceSpans"][0]
        spans = rs["scopeSpans"][0]["spans"]
        for s in spans:
            if s.get("status", {}).get("code") == 2:
                s["status"]["code"] = "STATUS_CODE_ERROR"
        half = len(spans) // 2
        lines = [{"resourceSpans": [{**rs, "scopeSpans": [{"scope": {}, "spans": part}]}]} for part in (spans[:half], spans[half:])]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n")
        loaded = otlp.load(f.name)
        Path(f.name).unlink()
        self.assertEqual(len(loaded), len(spans))
        self.assertEqual(sum(s["error"] for s in loaded), 1)


class CliTest(unittest.TestCase):
    def test_gate(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(cli.main([str(TRACES), "--policy", str(ROOT / "examples/policy.json"), "--out", f"{d}/r.md", "--fail-on", "高"]), 1)
            self.assertIn("## 指摘", Path(f"{d}/r.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
