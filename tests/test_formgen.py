"""python -m unittest discover -s tests   (모델 없이 돈다)"""
import base64
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from formgen import bench, config, selftest, svg
from formgen.make import extract_svg, make

ITEMS = Path(__file__).resolve().parents[1] / "bench" / "golden_v1"
SAMPLE = ('<svg xmlns="http://www.w3.org/2000/svg" width="794" height="1123" viewBox="0 0 794 1123"><text x="10" y="20">Name</text>'
          '<rect data-field="name" data-label="Name" data-type="text" x="100" y="30" width="100" height="20" fill="none" stroke="none"/></svg>')


def cfg(out, models, rounds=0, repeat=1):
    return {"items": str(ITEMS), "out": str(out), "repeat": repeat, "rounds": rounds, "models": models}


class Contract(unittest.TestCase):
    def test_invalid(self):
        bad = [SAMPLE.replace('x="100"', 'x="900"'), SAMPLE.replace("</svg>", "<script/></svg>"),
               SAMPLE.replace("</svg>", '<image href="file:///secret"/></svg>'), SAMPLE.replace("<text ", '<text style="display:none" '),
               SAMPLE.replace("<text ", '<text visibility="hidden" '), SAMPLE.replace('viewBox="0 0 794 1123"', 'viewBox="0 0 nan 1123"'),
               "<!DOCTYPE svg>" + SAMPLE, SAMPLE[:-10], SAMPLE.replace('data-type="text"', 'data-type="checkbox"')]
        for value in bad:
            self.assertFalse(svg.parse(value)["valid"], value)
        self.assertTrue(svg.parse(SAMPLE)["valid"])

    def test_extract(self):
        self.assertEqual(extract_svg("<think><svg>x</svg></think>```svg\n" + SAMPLE + "\n```"), SAMPLE)


class Scoring(unittest.TestCase):
    def test_position_first(self):
        self.assertEqual(svg.score(SAMPLE, SAMPLE)["field_recall"], 1)
        renamed = svg.score(SAMPLE, SAMPLE.replace('data-label="Name"', 'data-label="Other"'))
        self.assertEqual((renamed["field_recall"], renamed["label_acc"]), (1, 0))
        self.assertEqual(svg.score(SAMPLE, SAMPLE.replace('x="100"', 'x="500"'))["field_recall"], 0)
        self.assertEqual(svg.score(SAMPLE, SAMPLE.replace('data-type="text"', 'data-type="seal"'))["field_recall"], 0)
        self.assertEqual(svg.score(SAMPLE, SAMPLE.replace('data-type="text"', 'data-type="date"'))["type_acc"], 0)
        self.assertFalse(svg.score(SAMPLE, "not xml")["valid"])

    def test_selftest_on_golden(self):
        self.assertEqual(selftest.run(ITEMS)["failed"], [])


class Bench(unittest.TestCase):
    def test_golden_set(self):
        tiers = [json.loads((p / "meta.json").read_text(encoding="utf-8"))["tier"] for p in ITEMS.iterdir() if p.is_dir()]
        self.assertEqual({t: tiers.count(t) for t in bench.TIERS}, {"하": 4, "중": 4, "상": 4})

    def test_mock_runs_resume_compare(self):
        with tempfile.TemporaryDirectory() as d:
            models = [{"name": "good", "mock": "ref"}, {"name": "bad", "mock": "nofields"}]
            bench.run(cfg(d, models, repeat=2))
            good, bad = Path(d) / "good", Path(d) / "bad"
            lines = (good / "results.jsonl").read_text(encoding="utf-8")
            bench.run(cfg(d, models, repeat=2))   # 이어하기: 다시 돌리지 않는다
            self.assertEqual((good / "results.jsonl").read_text(encoding="utf-8"), lines)
            s = bench.summarize(bench.load(good)[1])
            self.assertEqual((s["전체"]["images"], s["전체"]["attempts"], s["전체"]["image_pass"]), (12, 24, 12))
            self.assertEqual(bench.summarize(bench.load(bad)[1])["전체"]["failures"], {"invalid:no_fields": 24})
            table = (Path(d) / "compare.md").read_text(encoding="utf-8")
            self.assertIn("| good | 0 | 4/4", table)
            self.assertIn("| bad | 0 | 0/4", table)
            with self.assertRaises(SystemExit):
                bench.run(cfg(d, [{"name": "good", "mock": "empty"}]))   # 다른 설정을 같은 폴더에 섞지 않는다

    def test_self_fix_rounds(self):
        """회차마다 따로 채점되고, 0회차(한 번만)와 마지막 회차(고친 뒤)가 나란히 나온다."""
        with tempfile.TemporaryDirectory() as d:
            bench.run(cfg(d, [{"name": "fix", "mock": "nofields,ref"}, {"name": "worse", "mock": "ref,empty"}], rounds=2))
            run, rows = bench.load(Path(d) / "fix")
            self.assertEqual(len(rows), 36)
            self.assertEqual(bench.summarize(bench.at(rows, 0))["전체"]["image_pass"], 0)
            self.assertEqual(bench.summarize(bench.at(rows, 2))["전체"]["image_pass"], 12)
            self.assertEqual(bench.change(rows, 2), {"up": 12, "down": 0, "same": 0})
            self.assertEqual(bench.change(bench.load(Path(d) / "worse")[1], 2), {"up": 0, "down": 12, "same": 0})
            table = (Path(d) / "compare.md").read_text(encoding="utf-8")
            self.assertIn("| fix | 0 | 0/4", table)
            self.assertIn("| fix | 2 | 4/4", table)
            self.assertIn("오름 12 · 내림 0", (Path(d) / "fix" / "report.md").read_text(encoding="utf-8"))

    def test_config_checks(self):
        for bad in [{"models": []}, {"models": [{"name": "a"}]}, {"models": [{"name": "a b", "mock": "ref"}]},
                    {"models": [{"name": "a", "mock": "ref", "temprature": 0}]}, {"modles": []},
                    {"models": [{"name": "a", "mock": "ref"}, {"name": "a", "mock": "ref"}]}]:
            with self.assertRaises(SystemExit, msg=bad):
                config.load(bad)
        c = config.load({"defaults": {"max_tokens": 100, "extra": {"top_p": 0.9}},
                         "models": [{"name": "a", "endpoint": "http://x/v1", "model": "m", "extra": {"seed": 1}}]})
        self.assertEqual((c["models"][0]["max_tokens"], c["models"][0]["extra"]), (100, {"top_p": 0.9, "seed": 1}))
        for path in Path(ITEMS.parents[1], "configs").glob("*.json"):
            config.load(path)

    def test_repeats_grouped_by_image(self):
        ok = {"tier": "하", "valid": True, "field_recall": 1, "text_f1": 1}
        bad = {**ok, "field_recall": 0.5}
        rows = [{**ok, "id": "a", "repeat": 0}, {**bad, "id": "a", "repeat": 1}, {**bad, "id": "a", "repeat": 2}, {**ok, "id": "b", "repeat": 0}]
        b = bench.summarize(rows)["전체"]
        self.assertEqual((b["images"], b["attempts"], b["attempt_pass"], b["image_pass"], b["unstable"]), (2, 4, 2, 1, 1))
        self.assertEqual(b["failures"], {"ok": 2, "low_fields": 2})


class Transport(unittest.TestCase):
    def test_http_and_fix_round(self):
        """vLLM 옵션이 요청에 실리고, 고치기 회차에는 원본 + 직전 svg 그림 + 직전 svg 원문이 간다."""
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                body = json.dumps({"choices": [{"message": {"content": SAMPLE}, "finish_reason": "stop"}], "usage": {"completion_tokens": 7}}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as d:
                m = config.load({"models": [{"name": "fake", "endpoint": f"http://127.0.0.1:{server.server_port}/v1", "model": "fake",
                                             "extra": {"top_p": 0.5}}]})["models"][0]
                logs = make(ITEMS / "hf138" / "image.png", Path(d) / "out", m, rounds=1)
                self.assertEqual([log["valid"] for log in logs], [True, True])
                self.assertEqual(seen[0]["top_p"], 0.5)
                first, second = seen[0]["messages"][1]["content"], seen[1]["messages"][1]["content"]
                self.assertEqual([p["type"] for p in first], ["image_url", "text"])
                picture = logs[1]["feedback"]["picture"]
                self.assertEqual([p["type"] for p in second], ["image_url"] + ["image_url"] * picture + ["text"])
                self.assertIn(SAMPLE, second[-1]["text"])
                raw = lambda p: base64.b64decode(p["image_url"]["url"].split(",", 1)[1])
                self.assertEqual(raw(second[0]), (ITEMS / "hf138" / "image.png").read_bytes())   # 고치기에도 원본이 먼저 간다
                if picture:
                    self.assertEqual(raw(second[1]), (Path(d) / "out" / "round0" / "view.png").read_bytes())
                self.assertEqual((Path(d) / "out" / "round1" / "out.svg").read_text(encoding="utf-8"), SAMPLE)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
