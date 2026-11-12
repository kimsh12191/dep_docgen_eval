"""python -m unittest discover -s tests   (모델 없이 돈다. 브라우저 엔진은 필요하다)"""
import base64
import json
import random
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tplgen import bench, check, config, data, gen, make, package
from tplgen.render import Renderer

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE, IMAGE = ROOT / "examples" / "hf153", ROOT / "samples" / "hf153.png"


def answer(edit=lambda name, text: text) -> str:
    """본보기 꾸러미를 모델 답의 꼴로. edit 로 일부러 망가뜨린다."""
    return "".join(f"=== {n} ===\n" + edit(n, (EXAMPLE / n).read_text(encoding="utf-8")) for n in package.FILES)


def folder(tmp, text: str) -> Path:
    package.save(package.split(text), Path(tmp) / "pkg")
    return Path(tmp) / "pkg"


class Rules(unittest.TestCase):
    def test_split_and_validate(self):
        parts = package.split("<think>=== template.html ===\nx</think>머리말\n" + answer().replace("=== schema.json ===\n", "=== schema.json ===\n```json\n", 1)
                              .replace("=== sample.json ===", "```\n=== sample.json ===", 1))
        self.assertEqual(set(parts), set(package.FILES))
        self.assertEqual(json.loads(parts["schema.json"])["title"], "질권설정등록청구서")
        self.assertEqual(package.load(EXAMPLE)["issues"], [])

    def test_broken_rules(self):
        t = lambda old, new: (lambda n, s: s.replace(old, new) if n == "template.html" else s)
        cases = {"forbidden:script": t("</body>", "<script>1</script></body>"), "forbidden:external": t("<style>", '<style>@import "x.css";'),
                 "forbidden:embed": t("</body>", '<img src="data:x"></body>'), "no_page": t('class="page"', 'class="sheet"'),
                 "template_error": t("{% endfor %}", ""), "not_in_template:recipient": t('data-field="recipient"', ""),
                 "no_row_loop:securities": t("securities.{{ loop.index0 }}.", "securities.0."),
                 "bad_type:fields.recipient": lambda n, s: s.replace('"type": "company"', '"type": "corp"') if n == "schema.json" else s,
                 "sample_missing:recipient": lambda n, s: s.replace('"recipient": "",', "") if n == "sample.json" else s,
                 "bad_json:schema.json": lambda n, s: s[:-5] if n == "schema.json" else s}
        for want, edit in cases.items():
            with tempfile.TemporaryDirectory() as d:
                issues = package.load(folder(d, answer(edit)))["issues"]
                self.assertTrue(any(i.startswith(want) for i in issues), (want, issues))

    def test_formats_and_language(self):
        self.assertEqual(data.fmt_amount(13032.62, "R # ###,##"), "R 13 032,62")
        self.assertEqual(data.fmt_amount(3658.63, "K #,###.##"), "K 3,658.63")
        self.assertEqual(data.fmt_amount(1234567, "#,###원"), "1,234,567원")
        self.assertEqual(data.fmt_date(2025, 10, 9, "DD/MM/YYYY"), "09/10/2025")
        schema = {"language": "en", "fields": [{"name": "n", "type": "text", "format": "IN#######"}, {"name": "c", "type": "company"},
                                                {"name": "a", "type": "amount", "format": "$#,###.##"}], "tables": []}
        d = data.make(schema, random.Random(0))
        self.assertRegex(d["n"], r"^IN\d{7}$")
        self.assertRegex(d["a"], r"^\$[\d,]+\.\d\d$")
        self.assertTrue(d["c"].isascii())

    def test_photo_is_flattened(self):
        """비스듬히 찍은 사진은 종이를 펴서 본다: 편 종이는 배경색이 거의 없다."""
        import numpy as np
        from PIL import Image
        im = Image.open(ROOT / "samples" / "invoice_photo_skewed.jpg").convert("L")
        flat = np.asarray(check.paper(im)).astype(float)
        self.assertLess((flat < 120).mean(), 0.03)
        self.assertEqual(check.paper(Image.open(IMAGE).convert("L")).size, Image.open(IMAGE).size)   # 스캔·렌더링은 그대로

    def test_data(self):
        schema = package.load(EXAMPLE)["schema"]
        for seed in range(20):
            d = data.make(schema, random.Random(seed))
            self.assertTrue(1 <= int(d["date_month"]) <= 12 and 1 <= int(d["date_day"]) <= 28 and len(d["date_year"]) == 4)
            self.assertIn(d["security_kind"], ["주권", "사채권", "증권", "예금"])
            self.assertTrue(1 <= len(d["securities"]) <= 20)
        self.assertEqual(len(data.make(schema, random.Random(0), rows=7)["securities"]), 7)


class Scores(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = Renderer().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.r.__exit__()

    def run_check(self, edit=None):
        with tempfile.TemporaryDirectory() as d:
            return check.check(folder(d, answer(edit)) if edit else EXAMPLE, IMAGE, renderer=self.r)

    def test_example_is_usable(self):
        res = self.run_check()
        self.assertTrue(res["pass"], check.brief(res))
        self.assertEqual((res["robust"], res["leak"], res["tables"], res["assets"]), (1.0, 0, 1, 2))
        self.assertEqual(set(res["tests"]), {"sample", "random", "long", "empty", "rows_1", "rows_many"})

    def test_all_examples(self):
        """본보기 셋: 깨끗한 서식 · 스캔처럼 만든 것 · 찍은 영수증 · 긴 표. 다른 문서의 이미지와는 닮지 않아야 한다."""
        pairs = {"hf153": "hf153.png", "receipt_photo": "receipt_photo.jpg", "statement": "statement.jpg", "irs_f8949": "irs_f8949.png",
                 "irs_fw9": "irs_fw9.png", "invoice_photo_skewed": "invoice_photo_skewed.jpg", "invoice_handwritten": "invoice_handwritten.jpg"}
        for name, image in pairs.items():
            res = check.check(ROOT / "examples" / name, ROOT / "samples" / image, renderer=self.r)
            self.assertTrue(res["pass"], (name, check.brief(res)))
        self.assertTrue(check.check(EXAMPLE, ROOT / "samples" / "hf153_scan.jpg", renderer=self.r)["pass"])
        for other in ("hf138.png", "hf225.png", "statement.jpg", "receipt_photo.jpg"):
            self.assertLess(check.check(EXAMPLE, ROOT / "samples" / other, renderer=self.r)["layout"], check.PASS_RULE["layout"], other)

    def test_broken_is_caught(self):
        t = lambda old, new: (lambda n, s: s.replace(old, new) if n == "template.html" else s)
        leak = self.run_check(t("{{ pledgor_name }}", "박찬연"))
        self.assertEqual((leak["leak"], leak["pass"]), (1, False))
        wide = self.run_check(t("table { width: 100%;", "table { width: 900px;"))
        self.assertIn("overflow_x", wide["tests"]["sample"])
        fixed = self.run_check(t("th, td { border: 1px solid #000; height: 25px;", "td { overflow: hidden } th, td { border: 1px solid #000; height: 25px; white-space: nowrap;"))
        self.assertTrue(any(p.startswith("clipped") for p in fixed["tests"]["long"]), fixed["tests"])
        static = self.run_check(t("{% for row in securities %}", "{% for row in securities[:5] %}"))   # 행이 늘지 않는 표
        self.assertTrue(any(p.startswith("missing:securities.5") for p in static["tests"]["rows_many"]))
        self.assertFalse(wide["pass"] or fixed["pass"] or static["pass"])
        empty = self.run_check(t('<div class="body">', '<div class="body" style="display:none">'))   # 본문이 빠지면 닮음이 내려간다
        self.assertLess(empty["layout"], self.run_check()["layout"])

    def test_generate_with_labels(self):
        pkg = package.load(EXAMPLE)
        with tempfile.TemporaryDirectory() as d:
            values = data.make(pkg["schema"], random.Random(1), rows=12)
            shot = gen.one(pkg, values, Path(d) / "a", self.r)
            self.assertEqual(shot["problems"], [])
            label = json.loads((Path(d) / "a.json").read_text(encoding="utf-8"))
            cells = [l for l in label["labels"] if l["field"].startswith("securities.")]
            self.assertEqual(len(cells), 12 * 7)
            self.assertEqual(next(l["text"] for l in label["labels"] if l["field"] == "securities.11.kind"), values["securities"][11]["kind"])
            self.assertTrue((Path(d) / "a.png").stat().st_size > 10000)
            more = gen.one(pkg, data.make(pkg["schema"], random.Random(1), rows=30), Path(d) / "b", self.r)
            self.assertGreater(more["height"], shot["height"])   # 행이 늘면 쪽이 길어진다 (아래 내용이 밀린다)


class Harness(unittest.TestCase):
    def test_loop_picks_best_round(self):
        bad = lambda n, s: s.replace("table { width: 100%;", "table { width: 900px;") if n == "template.html" else s
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "bad.txt", Path(d) / "good.txt"
            a.write_text(answer(bad), encoding="utf-8")
            b.write_text(answer(), encoding="utf-8")
            images = Path(d) / "images"
            images.mkdir()
            (images / "hf153.png").write_bytes(IMAGE.read_bytes())
            cfg = {"images": str(images), "out": str(Path(d) / "run"), "rounds": 2,
                   "models": [{"name": "fixes", "mock": f"{a},{b}"}, {"name": "breaks", "mock": f"{b},{a}"},
                              {"name": "junk", "mock": str(Path(d) / "junk.txt")}]}
            (Path(d) / "junk.txt").write_text("죄송합니다. 만들 수 없습니다.", encoding="utf-8")
            table = bench.run(cfg)
            picked = lambda name: json.loads((Path(d) / "run" / name / "hf153" / "final" / "result.json").read_text(encoding="utf-8"))
            self.assertEqual((picked("fixes")["round"], picked("fixes")["pass"]), (2, True))
            self.assertEqual((picked("breaks")["round"], picked("breaks")["pass"]), (0, True))   # 고치다 망가지면 앞의 것을 고른다
            self.assertFalse(picked("junk")["valid"])
            self.assertIn("| fixes | 한 번만 생성 | 0/1", table)
            self.assertIn("| fixes | 고치기 2회 중 고른 것 | 1/1", table)
            self.assertIn("| junk | 한 번만 생성 | 0/1 | 0/1", table)
            before = (Path(d) / "run" / "fixes" / "results.jsonl").read_text(encoding="utf-8")
            bench.run(cfg)   # 이어하기: 다시 돌리지 않는다
            self.assertEqual((Path(d) / "run" / "fixes" / "results.jsonl").read_text(encoding="utf-8"), before)

    def test_http_requests(self):
        """vLLM 옵션이 실리고, 고치기 회차에는 원본 이미지 + 직전 꾸러미를 그린 그림 + 시험 결과·직전 파일이 간다."""
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                body = json.dumps({"choices": [{"message": {"content": answer()}, "finish_reason": "stop"}], "usage": {"completion_tokens": 9}}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as d:
                m = config.load({"models": [{"name": "fake", "endpoint": f"http://127.0.0.1:{server.server_port}/v1", "model": "fake", "extra": {"top_p": 0.5}}]})["models"][0]
                logs = make.make(IMAGE, Path(d) / "out", m, rounds=1)
                self.assertEqual([g["result"]["pass"] for g in logs], [True, True])
                self.assertEqual(seen[0]["top_p"], 0.5)
                first, second = seen[0]["messages"][1]["content"], seen[1]["messages"][1]["content"]
                self.assertEqual([p["type"] for p in first], ["image_url", "text"])
                self.assertEqual([p["type"] for p in second], ["image_url", "image_url", "text"])
                raw = lambda p: base64.b64decode(p["image_url"]["url"].split(",", 1)[1])
                self.assertEqual(raw(second[0]), IMAGE.read_bytes())
                self.assertEqual(raw(second[1]), (Path(d) / "out" / "round0" / "tests" / "sample.png").read_bytes())
                self.assertIn("rows_many: 이상 없음", second[2]["text"])
                self.assertIn("=== schema.json ===", second[2]["text"])
        finally:
            server.shutdown()
            server.server_close()

    def test_config(self):
        for bad in [{"models": []}, {"models": [{"name": "a"}]}, {"models": [{"name": "a b", "mock": "x"}]}, {"modles": []},
                    {"models": [{"name": "a", "mock": "x", "temprature": 0}]}]:
            with self.assertRaises(SystemExit, msg=bad):
                config.load(bad)
        config.load(ROOT / "configs" / "example.json")


if __name__ == "__main__":
    unittest.main()
