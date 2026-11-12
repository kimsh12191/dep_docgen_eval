"""python -m unittest discover -s tests   (모델 없이 돈다)"""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from formgen import bench, selftest, svg
from formgen.make import extract_svg, make

ITEMS = Path(__file__).resolve().parents[1] / "bench" / "golden_v1"
SAMPLE = ('<svg xmlns="http://www.w3.org/2000/svg" width="794" height="1123" viewBox="0 0 794 1123"><text x="10" y="20">Name</text>'
          '<rect data-field="name" data-label="Name" data-type="text" x="100" y="30" width="100" height="20" fill="none" stroke="none"/></svg>')


def args(out, **kw):
    base = dict(items=str(ITEMS), out=str(out), endpoint="", model="", max_tokens=32000, repeat=1, api_key=None, mock="ref")
    return type("Args", (), {**base, **kw})()


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
            good, bad = Path(d) / "good", Path(d) / "bad"
            bench.run(args(good, repeat=2))
            lines = (good / "results.jsonl").read_text(encoding="utf-8")
            bench.run(args(good, repeat=2))   # 이어하기: 다시 돌리지 않는다
            self.assertEqual((good / "results.jsonl").read_text(encoding="utf-8"), lines)
            s = bench.summarize(bench.load(good)[1])
            self.assertEqual((s["전체"]["images"], s["전체"]["attempts"], s["전체"]["image_pass"]), (12, 24, 12))
            bench.run(args(bad, mock="nofields"))
            self.assertEqual(bench.summarize(bench.load(bad)[1])["전체"]["failures"], {"invalid:no_fields": 12})
            table = bench.compare([good, bad])
            self.assertIn("| mock:ref | 4/4", table)
            self.assertIn("| mock:nofields | 0/4", table)
            with self.assertRaises(SystemExit):
                bench.run(args(good, mock="empty"))   # 다른 설정을 같은 폴더에 섞지 않는다

    def test_repeats_grouped_by_image(self):
        ok = {"tier": "하", "valid": True, "field_recall": 1, "text_f1": 1}
        bad = {**ok, "field_recall": 0.5}
        rows = [{**ok, "id": "a", "repeat": 0}, {**bad, "id": "a", "repeat": 1}, {**bad, "id": "a", "repeat": 2}, {**ok, "id": "b", "repeat": 0}]
        b = bench.summarize(rows)["전체"]
        self.assertEqual((b["images"], b["attempts"], b["attempt_pass"], b["image_pass"], b["unstable"]), (2, 4, 2, 1, 1))
        self.assertEqual(b["failures"], {"ok": 2, "low_fields": 2})


class Transport(unittest.TestCase):
    def test_http(self):
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
                image = Path(d) / "image.png"
                image.write_bytes(b"fake")
                log = make(image, Path(d) / "out", f"http://127.0.0.1:{server.server_port}/v1", "fake")
                self.assertTrue(log["valid"])
                self.assertEqual(seen[0]["messages"][1]["content"][0]["type"], "image_url")
                self.assertEqual((Path(d) / "out" / "out.svg").read_text(encoding="utf-8"), SAMPLE)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
