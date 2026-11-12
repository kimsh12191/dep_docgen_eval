"""Counterfactual regressions for the SVG v2 scorer."""
import tempfile
import unittest
from pathlib import Path
from formgen import svg_eval_v2 as v2
from formgen import svg_cli


def sample(label="Name", fx=100, fy=30, kind="text", text="Name", tx=10, field=True, line=True):
    box = (f'<rect data-field="applicant.name" data-label="{label}" data-type="{kind}" '
           f'x="{fx}" y="{fy}" width="100" height="25" fill="none" stroke="none"/>') if field else ""
    rule = '<line x1="10" y1="80" x2="300" y2="80" stroke="black"/>' if line else ""
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" '
            f'viewBox="0 0 400 300"><text x="{tx}" y="20">{text}</text>{rule}{box}</svg>')


class ScorerV2Tests(unittest.TestCase):
    def test_identity_and_uncalibrated(self):
        r = v2.evaluate(sample(), sample())
        self.assertEqual(r["fields"]["field_located_semantic_f1"], 1)
        self.assertEqual(r["text_geometry"]["text_located_f1"], 1)
        self.assertEqual(r["legacy_svg_v1"]["located_field_f1"], 1)
        self.assertIsNone(r["final_pass"])

    def test_wrong_label_does_not_hide_correct_location(self):
        r = v2.evaluate(sample(), sample(label="Applicant"))
        self.assertEqual(r["fields"]["field_detection_f1"], 1)
        self.assertEqual(r["fields"]["field_located_f1"], 1)
        self.assertEqual(r["fields"]["field_label_f1"], 0)
        self.assertEqual(r["legacy_svg_v1"]["typed_field_f1"], 0)

    def test_wrong_location_does_not_hide_correct_label(self):
        r = v2.evaluate(sample(), sample(fx=135))
        self.assertEqual(r["fields"]["field_label_f1"], 1)
        self.assertLess(r["fields"]["field_located_f1"], 1)

    def test_far_away_same_label_is_not_a_detection(self):
        r = v2.evaluate(sample(), sample(fx=280, fy=220))
        self.assertEqual(r["fields"]["field_detection_f1"], 0)
        self.assertEqual(r["fields"]["missing_fields"], ["applicant.name"])

    def test_wrong_type(self):
        r = v2.evaluate(sample(), sample(kind="amount"))
        self.assertEqual(r["fields"]["field_detection_f1"], 1)
        self.assertEqual(r["fields"]["field_type_f1"], 0)

    def test_missing_field(self):
        r = v2.evaluate(sample(), sample(field=False))
        self.assertEqual(r["fields"]["field_detection_f1"], 0)

    def test_text_moved_recognition_unchanged(self):
        r = v2.evaluate(sample(), sample(tx=150))
        self.assertEqual(r["recognition"]["text_f1"], 1)
        self.assertEqual(r["text_geometry"]["text_located_f1"], 0)

    def test_hidden_root_invalid(self):
        r = v2.evaluate(sample(), sample().replace("<svg ", '<svg opacity="0" ', 1))
        self.assertFalse(r["valid"])
        self.assertIn("hidden_content", r["issues"])

    def test_visual_detects_missing_line(self):
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            self.skipTest("Pillow not installed")
        blank = Image.new("RGB", (200, 100), "white")
        rule = blank.copy()
        ImageDraw.Draw(rule).line((20, 40, 180, 40), fill="black", width=2)
        good, bad = v2.compare_rasters(rule, rule), v2.compare_rasters(rule, blank)
        self.assertEqual(good["ink"]["f1"], 1)
        self.assertEqual(good["edge"]["f1"], 1)
        self.assertEqual(bad["ink"]["f1"], 0)
        self.assertEqual(bad["edge"]["f1"], 0)

    def test_visual_aspect_mismatch(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        r = v2.compare_rasters(Image.new("RGB", (100, 200)), Image.new("RGB", (200, 100)))
        self.assertEqual(r["status"], "aspect_mismatch")

    def test_visual_without_source_is_missing(self):
        r = v2.evaluate(sample(), sample(), visual=True, output_dir="unused")
        self.assertEqual(r["visual"]["status"], "missing_source_image")
        self.assertIsNone(r["final_pass"])

    def test_summary_tracks_images_and_repeats(self):
        score = v2.evaluate(sample(), sample())
        rows = [{"id":"one", "tier":"하", **score}, {"id":"one", "tier":"하", **score}]
        summary = svg_cli._summary(rows)
        self.assertEqual(summary["all"]["n_images"], 1)
        self.assertEqual(summary["all"]["n_attempts"], 2)
        self.assertIsNone(summary["final_pass"])

    def test_cli_score(self):
        with tempfile.TemporaryDirectory() as d:
            ref, pred, out = (Path(d)/name for name in ("ref.svg","pred.svg","score.json"))
            ref.write_text(sample(), encoding="utf-8")
            pred.write_text(sample(label="Applicant"), encoding="utf-8")
            svg_cli.main(["score",str(ref),str(pred),"--out",str(out)])
            self.assertIn("field_label_f1",out.read_text())
