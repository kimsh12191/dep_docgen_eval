"""svg 벤치의 길 검사: 모델 없이 (--mock) 집계·이어하기·후보 거절이 기대대로인지."""
import json
import tempfile
import unittest
from pathlib import Path

from formgen import bench, selftest

ITEMS = Path(__file__).resolve().parents[1] / "bench" / "official_pilot_v1"


def args(out, **kw):
    base = dict(items=str(ITEMS), out=str(out), endpoint="", model="", max_tokens=16000, repeat=1, tiers=None, limit=0,
                allow_candidates=True, api_key=None, mock="ref")
    return type("Args", (), {**base, **kw})()


class BenchTests(unittest.TestCase):
    def test_candidates_refused_by_default(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(SystemExit):
            bench.run(args(Path(d) / "x", allow_candidates=False))

    def test_mock_ref_passes_and_tiers(self):
        with tempfile.TemporaryDirectory() as d:
            s = bench.run(args(Path(d) / "x", repeat=2))["summary"]
            self.assertEqual(s["all"]["images"], 3)
            self.assertEqual(s["all"]["attempts"], 6)
            self.assertEqual(s["all"]["image_pass"], 3)
            self.assertEqual([s["by_tier"][t]["images"] for t in bench.TIERS], [1, 1, 1])
            self.assertIn("진단용", (Path(d) / "x" / "report.md").read_text(encoding="utf-8"))

    def test_mock_nofields_fails_with_reason(self):
        with tempfile.TemporaryDirectory() as d:
            s = bench.run(args(Path(d) / "x", mock="nofields"))["summary"]
            self.assertEqual(s["all"]["image_pass"], 0)
            self.assertEqual(s["all"]["failures"], {"invalid:no_fields": 3})

    def test_resume_does_not_rerun(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "x"
            bench.run(args(out))
            before = (out / "results.jsonl").read_text(encoding="utf-8")
            bench.run(args(out))
            self.assertEqual((out / "results.jsonl").read_text(encoding="utf-8"), before)
            bench.run(args(out, repeat=2))
            self.assertEqual(len((out / "results.jsonl").read_text(encoding="utf-8").splitlines()), 6)

    def test_pass_rule_can_change_without_rerun(self):
        rows = [{"id": "a", "repeat": 0, "tier": "하", "valid": True, "typed_field_f1": 0.9, "located_field_f1": 0.7, "text_r": 0.9}]
        self.assertEqual(bench.summarize(rows)["all"]["failures"], {"low_position": 1})
        loose = {"version": "test", "typed_field_f1": 0.8}
        self.assertEqual(bench.summarize(rows, loose)["all"]["image_pass"], 1)

    def test_repeats_are_grouped_by_image(self):
        ok = {"tier": "하", "valid": True, "typed_field_f1": 1, "located_field_f1": 1, "text_r": 1}
        bad = {**ok, "valid": False, "issues": ["invalid_xml"]}
        rows = [{**ok, "id": "a", "repeat": 0}, {**bad, "id": "a", "repeat": 1}, {**bad, "id": "a", "repeat": 2}, {**ok, "id": "b", "repeat": 0}]
        b = bench.summarize(rows)["all"]
        self.assertEqual((b["images"], b["attempts"], b["attempt_pass"], b["image_pass"], b["images_unstable"]), (2, 4, 2, 1, 1))

    def test_scorer_selftest(self):
        self.assertEqual(selftest.run(ITEMS)["failed"], [])


if __name__ == "__main__":
    unittest.main()
