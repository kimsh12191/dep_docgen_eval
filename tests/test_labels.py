"""정답 라벨 형식·일치 검사 (만들기 도구는 돌리지 않는다)."""
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETS = [ROOT / "evalset" / "v1", ROOT / "evalset" / "forms_candidates_v2"]


def items():
    for s in SETS:
        for d in sorted(p for p in s.iterdir() if p.is_dir() and any(p.glob("image.*"))):
            yield d


class Labels(unittest.TestCase):
    def test_every_item_has_valid_labels(self):
        n = 0
        for d in items():
            L = json.loads((d / "labels.json").read_text(encoding="utf-8"))
            image = d / L["image"]
            self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(), L["image_sha256"], d.name)
            W, H = (L["frame"]["width"], L["frame"]["height"]) if L.get("frame") else (L["width"], L["height"])
            self.assertTrue(L["texts"], d.name)
            for t in L["texts"]:
                self.assertIn(t["role"], ("fixed", "value"))
                self.assertTrue(t["text"].strip(), d.name)
                x0, y0, x1, y1 = t["box"]
                self.assertTrue(-3 <= x0 < x1 <= W + 3 and -3 <= y0 < y1 <= H + 3, (d.name, t))
                if t["role"] == "value":
                    self.assertTrue(t["key"], (d.name, t))
            for s in L["slots"]:
                self.assertIn(s["kind"], ("text", "check", "seal", "sign"))
            self.assertEqual(L["counts"]["texts"], len(L["texts"]))
            self.assertEqual(set(L["provenance"]), {"texts", "rules", "slots", "assets"})
            n += 1
        self.assertEqual(n, 9 + 60)

    def test_filled_items_have_values(self):
        """값을 채운 v1 문서는 값 라벨이 있고, 빈 서식 후보는 없다."""
        for d in items():
            L = json.loads((d / "labels.json").read_text(encoding="utf-8"))
            values = L["counts"]["values"]
            if d.parent.name == "v1" and d.name not in ("irs_f8949", "irs_fw9"):
                self.assertGreater(values, 0, d.name)
            if d.parent.name == "forms_candidates_v2":
                self.assertEqual(values, 0, d.name)


if __name__ == "__main__":
    unittest.main()
