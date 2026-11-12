"""평가용 정답 라벨 만들기: 원본 이미지의 무엇이 어디에 있는가 → <항목>/labels.json. 형식은 evalset/LABELS.md.

평가 때는 이 파일만 읽는다 (OCR·PDF 불필요). 이 도구는 라벨을 만들 때만 쓴다: pip install -r requirements-data.txt (+ rapidocr-onnxruntime: OCR 항목)

  python tools/build_labels.py candidates --set evalset/forms_candidates_v2 --docgen ../document_gen
  python tools/build_labels.py v1 --set evalset/v1 --docgen ../document_gen --irs <fw9.pdf·f8949.pdf 가 있는 폴더>
  python tools/build_labels.py v1_ocr --set evalset/v1         # PDF 가 없는 4개: OCR 위치 + 기준 꾸러미 글자 + tools/labels_manual/ 의 고침

라벨의 출처 (provenance 에 항목마다 적는다):
  pdf_text_layer    원본 PDF 의 글자 줄과 위치            정확
  pdf_vector        원본 PDF 의 선(가로·세로)과 그림 자리    정확
  docgen_label      docgen 이 채운 값과 위치 (같은 seed 로 다시 만들어 이미지 해시가 같은지 확인)   정확
  fields_json       서식 정의(fields.json)의 기재란 칸     정확 (서식 정의가 맞다면)
  pdf_widgets       PDF 입력 칸(AcroForm)                 정확
  scan_transform    깨끗한 원본의 라벨을 스캔 변환(회전)과 같은 식으로 옮김   정확 (변환을 아는 경우)
  ocr+manual        OCR 위치 + 사람·모델이 고쳐 쓴 글자     검수 필요
  image_lines       이미지에서 찾은 긴 가로·세로 선          대략
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

VERSION = 1
ROUND = lambda box: [round(v, 1) for v in box]


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def clean(text: str) -> str:
    return "".join(ch for ch in text if ch >= " " and ch not in "￾￿").strip()


# ---------- PDF ----------

def from_pdf(pdf_path, page_no: int, scale: float) -> dict:
    """글자 줄 · 선 · 그림 자리. 좌표는 PDF pt × scale (= 이미지 px)."""
    import pymupdf
    page = pymupdf.open(pdf_path)[page_no]
    texts = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = clean("".join(s["text"] for s in line["spans"]))
            if text:
                texts.append({"text": text, "box": ROUND([v * scale for v in line["bbox"]]), "role": "fixed", "key": None})
    rules = []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] == "l":
                a, b = it[1], it[2]
                seg = [a.x, a.y, b.x, b.y]
            elif it[0] == "re":
                r = it[1]
                if d.get("fill") is not None and min(r.width, r.height) <= 2.0:      # 얇게 칠한 사각형 = 선
                    seg = [r.x0, (r.y0 + r.y1) / 2, r.x1, (r.y0 + r.y1) / 2] if r.width >= r.height else [(r.x0 + r.x1) / 2, r.y0, (r.x0 + r.x1) / 2, r.y1]
                elif d.get("color") is not None:                                      # 테두리를 그린 사각형 = 네 변
                    for s in ([r.x0, r.y0, r.x1, r.y0], [r.x0, r.y1, r.x1, r.y1], [r.x0, r.y0, r.x0, r.y1], [r.x1, r.y0, r.x1, r.y1]):
                        rules.append(s)
                    continue
                else:
                    continue
            else:
                continue
            rules.append(seg)
    rules = [ROUND([v * scale for v in s]) for s in rules
             if (abs(s[1] - s[3]) < 1 and abs(s[0] - s[2]) >= 4) or (abs(s[0] - s[2]) < 1 and abs(s[1] - s[3]) >= 4)]   # 가로·세로 선만
    rules = [list(t) for t in dict.fromkeys(tuple(s) for s in rules)]
    assets = [{"kind": "image", "box": ROUND([v * scale for v in info["bbox"]])} for info in page.get_image_info()
              if (info["bbox"][2] - info["bbox"][0]) * scale > 8 and (info["bbox"][3] - info["bbox"][1]) * scale > 8]
    return {"texts": texts, "rules": rules, "assets": assets, "page_width_pt": page.rect.width, "page_height_pt": page.rect.height}


def widgets(pdf_path, page_no: int, scale: float) -> list[dict]:
    import pymupdf
    page = pymupdf.open(pdf_path)[page_no]
    kinds = {pymupdf.PDF_WIDGET_TYPE_CHECKBOX: "check", pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON: "check", pymupdf.PDF_WIDGET_TYPE_SIGNATURE: "sign"}
    out = []
    for w in page.widgets() or []:
        r = w.rect
        if r.width > 1 and r.height > 1:
            out.append({"box": ROUND([r.x0 * scale, r.y0 * scale, r.x1 * scale, r.y1 * scale]), "kind": kinds.get(w.field_type, "text"),
                        "label": (w.field_label or "").strip(), "key": w.field_name, "filled": False, "source": "pdf_widgets"})
    return out


def overlay_slots(fields: dict, page_no: int, scale: float) -> list[dict]:
    """서식 정의(engine=overlay, unit=pt)의 기재란. 체크 묶음은 보기마다 하나."""
    out = []
    for item in fields.get("items") or []:
        if item.get("t") == "skip" or item.get("page", 0) != page_no:
            continue
        if item.get("t") == "check":
            for o in item.get("options") or []:
                box = o.get("box") or o.get("rect")
                if box:
                    out.append({"box": ROUND([v * scale for v in box]), "kind": "check", "label": f"{item.get('label', '')}: {o.get('text', '').strip()}",
                                "key": item.get("key"), "filled": False, "source": "fields_json"})
        elif item.get("rect"):
            kind = {"seal": "seal", "sign": "sign", "signature": "sign"}.get(item.get("kind") or item.get("t"), "text")
            out.append({"box": ROUND([v * scale for v in item["rect"]]), "kind": kind, "label": item.get("label", ""), "key": item.get("key"),
                        "filled": False, "source": "fields_json"})
    return out


# ---------- 이미지에서 (PDF 가 없을 때) ----------

def image_lines(image, min_len_ratio: float = 0.06) -> list[list[float]]:
    """긴 가로·세로 잉크 줄을 선으로. 대략."""
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(image).convert("L")).astype(float)
    dark = a < min(150.0, np.percentile(a, 50) - 60)
    h, w = dark.shape
    out = []
    for axis, length in ((1, w), (0, h)):
        need = max(20, int(length * min_len_ratio))
        lines = dark if axis == 1 else dark.T
        for i, row in enumerate(lines):
            run = start = 0
            for j, v in enumerate(list(row) + [False]):
                if v:
                    if run == 0:
                        start = j
                    run += 1
                else:
                    if run >= need:
                        out.append([start, i, j, i] if axis == 1 else [i, start, i, j])
                    run = 0
    merged = []                                                              # 붙어 있는 줄(굵은 선)을 하나로
    for seg in sorted(out, key=lambda t: (t[1] == t[3], t[0], t[2], t[1], t[3])):
        last = merged[-1] if merged else None
        horizontal = seg[1] == seg[3]
        if last and horizontal and last[1] == last[3] and abs(seg[0] - last[0]) <= 3 and abs(seg[2] - last[2]) <= 3 and seg[1] - last[3] <= 1:
            last[3] = seg[3]
        elif last and not horizontal and last[0] == last[2] and abs(seg[1] - last[1]) <= 3 and abs(seg[3] - last[3]) <= 3 and seg[0] - last[2] <= 1:
            last[2] = seg[2]
        else:
            merged.append(list(seg))
    return [[float(v) for v in s] for s in merged]


def ocr(image) -> list[dict]:
    from rapidocr_onnxruntime import RapidOCR
    result, _ = RapidOCR()(str(image))
    out = []
    for quad, text, conf in result or []:
        xs, ys = [p[0] for p in quad], [p[1] for p in quad]
        out.append({"text": clean(text), "box": ROUND([min(xs), min(ys), max(xs), max(ys)]), "conf": round(float(conf), 3)})
    return sorted(out, key=lambda t: (round(t["box"][1] / 12), t["box"][0]))


# ---------- 좌표 변환 ----------

def rotate_box(box, angle_deg: float, size, new_size):
    """PIL Image.rotate(angle, expand=True) 와 같은 변환으로 상자를 옮긴다 (네 모서리를 감싸는 상자)."""
    (w, h), (nw, nh) = size, new_size
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    pts = []
    for x, y in ((box[0], box[1]), (box[2], box[1]), (box[0], box[3]), (box[2], box[3])):
        dx, dy = x - w / 2, y - h / 2
        pts.append((c * dx + s * dy + nw / 2, -s * dx + c * dy + nh / 2))
    return ROUND([min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)])


def rotate_labels(labels: dict, angle: float, new_size, image_name: str) -> dict:
    size = (labels["width"], labels["height"])
    out = json.loads(json.dumps(labels))
    for t in out["texts"] + out["slots"] + out["assets"]:
        t["box"] = rotate_box(t["box"], angle, size, new_size)
    out["rules"] = [r for r in (rotate_box(s, angle, size, new_size) for s in labels["rules"])]
    out.update(image=image_name, width=new_size[0], height=new_size[1])
    out["provenance"] = {k: "scan_transform(" + v + ")" for k, v in labels["provenance"].items()}
    out["note"] = f"깨끗한 원본의 라벨을 {angle}° 회전(expand)으로 옮김. 선은 기울어 있으므로 상자로 적었다 (회전 전에는 가로·세로 선)"
    return out


# ---------- 라벨 꾸러미 ----------

def labels(image, texts, rules, slots, assets, provenance, frame=None, note=None) -> dict:
    from PIL import Image
    w, h = Image.open(image).size
    return {"version": VERSION, "image": Path(image).name, "image_sha256": sha(image), "width": w, "height": h, "frame": frame,
            "texts": texts, "rules": rules, "slots": slots, "assets": assets, "provenance": provenance,
            "counts": {"texts": len(texts), "values": sum(t["role"] == "value" for t in texts), "rules": len(rules), "slots": len(slots), "assets": len(assets)},
            "reviewed_by_human": False, **({"note": note} if note else {})}


def write(folder, value) -> None:
    (Path(folder) / "labels.json").write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def ink_check(image, value, frame_image=None) -> float:
    """글자 상자 중 안에 잉크가 있는 비율 (라벨이 이미지와 어긋났는지 보는 검사). frame_image: 펴 놓은 종이 그림."""
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(frame_image or image).convert("L")).astype(float)
    dark = a < min(160.0, np.percentile(a, 50) - 50)
    hit = 0
    for t in value["texts"]:
        x0, y0, x1, y1 = [int(round(v)) for v in t["box"]]
        if dark[max(0, y0):max(y0 + 1, y1), max(0, x0):max(x0 + 1, x1)].mean() > 0.01:
            hit += 1
    return round(hit / max(1, len(value["texts"])), 3)


def candidates(set_dir, docgen):
    set_dir, docgen = Path(set_dir), Path(docgen)
    report = []
    for meta_path in sorted(set_dir.glob("*/meta.json")):
        folder, meta = meta_path.parent, json.loads(meta_path.read_text(encoding="utf-8"))
        image, pdf = folder / "image.png", docgen / meta["source_pdf"]
        if sha(pdf) != meta["source_pdf_sha256"] or sha(image) != meta["image_sha256"]:
            raise SystemExit(f"{folder.name}: 원본 PDF 또는 이미지 해시가 meta 와 다릅니다")
        page_no = meta["source_pages_zero_based"][0]
        scale = meta["raster_dpi"] / 72
        p = from_pdf(pdf, page_no, scale)
        fields = json.loads((folder / "source_fields.json").read_text(encoding="utf-8")) if (folder / "source_fields.json").is_file() else {}
        slots = overlay_slots(fields, meta.get("form_page_one_based", 1) - 1, scale) if fields.get("engine") == "overlay" else []
        slots += widgets(pdf, page_no, scale)
        prov = {"texts": "pdf_text_layer", "rules": "pdf_vector", "assets": "pdf_vector",
                "slots": "fields_json" if fields.get("engine") == "overlay" else ("pdf_widgets" if slots else "unavailable")}
        value = labels(image, p["texts"], p["rules"], slots, p["assets"], prov,
                       note=None if slots else "기재란 위치를 알 수 있는 서식 정의가 없다 (빈 칸 판정은 선·글자로 해야 한다)")
        value["source"] = {"pdf": meta["source_pdf"], "pdf_sha256": meta["source_pdf_sha256"], "page_zero_based": page_no, "dpi": meta["raster_dpi"],
                           "commit": meta["source_commit"]}
        write(folder, value)
        report.append((folder.name, value["counts"], ink_check(image, value), prov["slots"]))
    return report


def v1(set_dir, docgen, irs):
    set_dir, docgen = Path(set_dir), Path(docgen)
    report = []
    # 하나은행 서식: 원본 PDF 글자·선 + docgen 이 채운 값
    for form in ("hf138", "hf153"):
        folder = set_dir / form
        image = folder / "image.png"
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, "-m", "docgen.preview", form, "--seed", "0", "--out", tmp], cwd=docgen, check=True, capture_output=True)
            run = next(Path(tmp).glob(f"{form}/*/label.json")).parent
            lab = json.loads((run / "label.json").read_text(encoding="utf-8"))
            if sha(run / Path(lab["images"][0]).name) != sha(image):
                raise SystemExit(f"{form}: docgen 으로 다시 만든 그림이 평가 세트 그림과 다릅니다 (seed·커밋 확인)")
        from PIL import Image
        width = Image.open(image).width
        pdf = docgen / "docgen" / "forms" / form / "look" / "original.pdf"
        import pymupdf
        scale = width / pymupdf.open(pdf)[0].rect.width
        p = from_pdf(pdf, 0, scale)
        k = width / lab["pages"][0]["width"]
        values = [{"text": clean(str(f["value"])), "box": ROUND([v * k for v in f["bbox"]]), "role": "value", "key": f["key"]}
                  for f in lab["fields"] if f.get("page") == 0 and f.get("bbox") and f.get("value") not in (None, "", False) and clean(str(f["value"]))]
        fields = json.loads((docgen / "docgen" / "forms" / form / "fields.json").read_text(encoding="utf-8"))
        slots = overlay_slots(fields, 0, scale)
        filled = [v["box"] for v in values]
        for s in slots:
            s["filled"] = any(min(s["box"][2], b[2]) > max(s["box"][0], b[0]) and min(s["box"][3], b[3]) > max(s["box"][1], b[1]) for b in filled)
        checks = [f for f in lab["fields"] if f.get("page") == 0 and f.get("type") == "checkbox" and f.get("value")]
        value = labels(image, p["texts"] + values, p["rules"], slots, p["assets"],
                       {"texts": "pdf_text_layer + docgen_label(값)", "rules": "pdf_vector", "assets": "pdf_vector", "slots": "fields_json"},
                       note=f"체크 표시(값 {len(checks)}개)는 글자가 아니라 그림이라 texts 에 없다. 서명·도장도 같다")
        value["source"] = {"pdf": f"docgen/forms/{form}/look/original.pdf", "docgen": "python -m docgen.preview " + form + " --seed 0"}
        write(folder, value)
        report.append((form, value["counts"], ink_check(image, value), "fields_json"))
        if form == "hf153":   # 스캔본: 같은 라벨을 scanify 의 회전으로 옮긴다
            scan = set_dir / "hf153_scan" / "image.jpg"
            from PIL import Image
            moved = rotate_labels(value, 1.2, Image.open(scan).size, "image.jpg")
            moved["image_sha256"] = sha(scan)
            write(scan.parent, moved)
            report.append(("hf153_scan", moved["counts"], ink_check(scan, moved), "scan_transform"))
    # 미국 세금 서식: PDF 글자·선·입력 칸
    for item, pdf_name in (("irs_f8949", "f8949.pdf"), ("irs_fw9", "fw9.pdf")):
        folder = set_dir / item
        image = folder / "image.png"
        pdf = Path(irs) / pdf_name
        scale = 150 / 72
        p = from_pdf(pdf, 0, scale)
        slots = widgets(pdf, 0, scale)
        value = labels(image, p["texts"], p["rules"], slots, p["assets"], {"texts": "pdf_text_layer", "rules": "pdf_vector", "assets": "pdf_vector", "slots": "pdf_widgets"})
        value["source"] = {"pdf": "https://www.irs.gov/pub/irs-pdf/" + pdf_name, "pdf_sha256": sha(pdf), "page_zero_based": 0, "dpi": 150}
        write(folder, value)
        report.append((item, value["counts"], ink_check(image, value), "pdf_widgets"))
    return report


LINES_JS = r"""
() => {
  const page = document.querySelector('.page'), p = page.getBoundingClientRect(), out = [];
  const walker = document.createTreeWalker(page, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode, text = node.textContent.replace(/\s+/g, ' ');
    if (!text.trim() || node.parentElement.closest('style')) continue;
    const field = node.parentElement.closest('[data-field]');
    const range = document.createRange(); range.selectNodeContents(node);
    for (const r of range.getClientRects()) if (r.width > 0) out.push({text: text.trim(), key: field ? field.getAttribute('data-field') : null, y: (r.top + r.bottom) / 2 - p.top, x: r.left - p.left});
  }
  return out;
}
"""


def width(text: str) -> int:
    return sum(2 if "ᄀ" <= ch <= "ￜ" else 1 for ch in text)


def split_box(box, parts):
    """한 줄 상자를 글자 폭(한글 2, 나머지 1) 비율로 나눈다. parts = [(글자, role, key), …]. 대략."""
    total, x, out = max(1, sum(width(t) for t, _, _ in parts)), box[0], []
    for text, role, key in parts:
        w = (box[2] - box[0]) * width(text) / total
        if text.strip():
            out.append({"text": text.strip(), "box": ROUND([x, box[1], x + w, box[3]]), "role": role, "key": key, "box_estimated": True})
        x += w
    return out


def reference_lines(reference) -> list[list[tuple]]:
    """기준 꾸러미를 예시 값으로 그려, 화면의 한 줄마다 [(글자, role, key), …]."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tplgen import package as P
    from tplgen.render import Renderer
    pkg = P.load(reference)
    with Renderer() as r:
        r._page.set_content(P.html(pkg, pkg["sample"]))
        nodes = r._page.evaluate(LINES_JS)
    lines = []
    for n in sorted(nodes, key=lambda n: (n["y"], n["x"])):
        if lines and abs(lines[-1][0] - n["y"]) < 4:
            lines[-1][1].append(n)
        else:
            lines.append([n["y"], [n]])
    import re
    return [[(n["text"], "value" if n["key"] else "fixed", re.sub(r"^(\w+)\.(\d+)\.", r"\1.\2.", n["key"]) if n["key"] else None)
             for n in sorted(ns, key=lambda n: n["x"])] for _, ns in lines]


def snap(ocr_text: str, lines) -> list | None:
    """OCR 한 덩어리 → 기준 줄에서 가장 잘 맞는 부분 [(글자, role, key), …]. 공백·대소문자를 빼고 비교. 못 찾으면 None."""
    from rapidfuzz import fuzz
    target = "".join(ocr_text.split()).lower()
    if not target:
        return None
    best = None
    windows = [line[i:j] for line in lines for i in range(len(line)) for j in range(i + 1, min(len(line), i + 3) + 1)]   # 한 줄 안의 이어진 조각 1~3개
    for parts in windows:
        joined = " ".join(t for t, _, _ in parts)
        index = [i for i, ch in enumerate(joined) if not ch.isspace()]
        flat = "".join(joined[i] for i in index).lower()
        if not flat:
            continue
        a = fuzz.partial_ratio_alignment(target, flat) if len(target) <= len(flat) else None
        score = a.score if a else fuzz.ratio(target, flat)
        span = (a.dest_start, a.dest_end) if a else (0, len(flat))
        score -= 0.01 * len(parts)                                   # 같은 점수면 조각이 적은 쪽
        if a and (a.dest_start > 0 or a.dest_end < len(flat)):
            score -= 0.5                                             # 같은 점수면 조각을 통째로 덮는 쪽 ("Subtotal" 의 total 보다 "TOTAL")
        if best is None or score > best[0]:
            best = (score, parts, joined, index[span[0]], index[span[1] - 1] + 1)
    if best[0] < 75:
        return None
    _, parts, joined, start, stop = best
    out, pos = [], 0
    for text, role, key in parts:                     # 맞은 구간과 겹치는 조각만, 겹친 만큼 잘라서
        s0, s1 = pos, pos + len(text)
        lo, hi = max(s0, start), min(s1, stop)
        if lo < hi:
            piece = text if (lo, hi) == (s0, s1) else joined[lo:hi]
            out.append((piece, role, key))
        pos = s1 + 1
    return out


def from_ocr(folder, fixes=None, frame=False, reference=None, ocr_engine=None):
    """OCR 위치 + 맞는 글자. 글자는 reference(기준 꾸러미, 이미지와 대조해 확인한 것)의 같은 줄에서 가져오거나 fixes 로 직접 준다.
    fixes: {"items": [{"i": OCR 번호, "parts": [[글자, role, key], …]} | {"drop": 번호} | {"add": {"text","box","role","key"}}], "assets": [...]}"""
    from PIL import Image
    fixes, folder = fixes or {}, Path(folder)
    image = next(p for p in folder.glob("image.*"))
    target = image
    if frame:   # 사진: 종이를 펴서 그 위에서 읽는다 (좌표도 편 종이 기준)
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from tplgen import check
        target = Path(tempfile.mkdtemp()) / "paper.png"
        check.paper(Image.open(image).convert("L")).save(target)
    raw = ocr_engine(target) if ocr_engine else ocr(target)
    lines = reference_lines(reference) if reference else []
    manual = {f["i"]: f for f in fixes.get("items", []) if "i" in f}
    dropped = {f["drop"] for f in fixes.get("items", []) if "drop" in f}
    texts, unverified = [], []
    for i, t in enumerate(raw):
        if i in dropped:
            continue
        parts = manual[i]["parts"] if i in manual else snap(t["text"], lines) if lines else None
        if parts is None:
            texts.append({"text": t["text"], "box": t["box"], "role": "fixed", "key": None, "unverified": True})
            unverified.append(i)
        elif len(parts) == 1:
            texts.append({"text": parts[0][0].strip(), "box": t["box"], "role": parts[0][1], "key": parts[0][2]})
        else:
            texts += split_box(t["box"], parts)
    texts += [dict({"role": "fixed", "key": None}, **f["add"]) for f in fixes.get("items", []) if "add" in f]
    texts.sort(key=lambda t: (round(t["box"][1] / 12), t["box"][0]))
    slots = [{"box": t["box"], "kind": "text", "label": "", "key": t["key"], "filled": True, "source": "value_text"} for t in texts if t["role"] == "value"]
    w, h = Image.open(target).size
    value = labels(image, texts, image_lines(target), slots, fixes.get("assets", []),
                   {"texts": "ocr(위치)+기준 꾸러미·수기(글자·역할)", "rules": "image_lines", "assets": "manual", "slots": "값 글자 위치 (빈 기재란은 모름)"},
                   frame={"kind": "paper", "width": w, "height": h, "how": "tplgen.check.paper (네 모서리를 찾아 편 종이). 좌표는 이 종이 기준"} if frame else None)
    return value, raw, unverified


def manual_lines(folder, spec) -> dict:
    """OCR 인식을 못 쓰는 항목: 기록해 둔 상자 + 직접 적은 글자 (tools/labels_manual/<항목>.json 의 lines)."""
    from PIL import Image
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tplgen import check
    folder = Path(folder)
    image = next(folder.glob("image.*"))
    target = Path(tempfile.mkdtemp()) / "paper.png"
    check.paper(Image.open(image).convert("L")).save(target)
    texts = []
    for line in spec["lines"]:
        parts = [tuple(p) for p in line["parts"]]
        texts += [{"text": parts[0][0].strip(), "box": line["box"], "role": parts[0][1], "key": parts[0][2]}] if len(parts) == 1 else split_box(line["box"], parts)
    texts += spec.get("add", [])
    texts.sort(key=lambda t: (round(t["box"][1] / 12), t["box"][0]))
    slots = [{"box": t["box"], "kind": "text", "label": "", "key": t["key"], "filled": True, "source": "value_text"} for t in texts if t["role"] == "value"]
    w, h = Image.open(target).size
    return labels(image, texts, image_lines(target), slots, spec.get("assets", []),
                  {"texts": "ocr 검출 상자 + 수기 글자", "rules": "image_lines", "assets": "manual", "slots": "값 글자 위치 (빈 기재란은 모름)"},
                  frame={"kind": "paper", "width": w, "height": h, "how": "tplgen.check.paper (네 모서리를 찾아 편 종이). 좌표는 이 종이 기준"},
                  note=spec.get("note"))


def v1_ocr(set_dir, manual_dir):
    """PDF 가 없는 항목: OCR 위치 + 기준 꾸러미 글자 + tools/labels_manual 의 고침."""
    set_dir, manual_dir = Path(set_dir), Path(manual_dir)
    report = []
    for item, frame in (("statement", False), ("invoice_handwritten", False), ("invoice_photo_skewed", True)):
        fixes = json.loads((manual_dir / f"{item}.json").read_text(encoding="utf-8"))
        value, raw, unverified = from_ocr(set_dir / item, fixes, frame=frame, reference=set_dir / item / "reference")
        value["source"] = {"ocr": "rapidocr_onnxruntime 1.2.3 (기본 모델)", "text_from": "evalset 기준 꾸러미(reference/)의 같은 줄 + " + str(manual_dir / f"{item}.json"),
                           "unverified": unverified}
        write(set_dir / item, value)
        report.append((item, value["counts"], None, f"OCR {len(raw)}, 못 맞춤 {len(unverified)}"))
    spec = json.loads((manual_dir / "receipt_photo.json").read_text(encoding="utf-8"))
    value = manual_lines(set_dir / "receipt_photo", spec)
    value["source"] = {"boxes": spec["boxes_from"], "text_from": str(manual_dir / "receipt_photo.json")}
    write(set_dir / "receipt_photo", value)
    report.append(("receipt_photo", value["counts"], None, "수기"))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["candidates", "v1", "v1_ocr", "ocr_dump"])
    ap.add_argument("--set", required=True)
    ap.add_argument("--docgen")
    ap.add_argument("--irs")
    ap.add_argument("--item")
    ap.add_argument("--paper", action="store_true")
    a = ap.parse_args()
    if a.what == "ocr_dump":   # 고쳐 쓰기 전에 OCR 이 읽은 것을 번호와 함께 본다
        _, raw, _ = from_ocr(Path(a.set) / a.item, frame=a.paper)
        for i, t in enumerate(raw):
            print(i, t["box"], t["conf"], t["text"])
        return
    report = (candidates(a.set, a.docgen) if a.what == "candidates" else v1(a.set, a.docgen, a.irs) if a.what == "v1"
              else v1_ocr(a.set, Path(__file__).parent / "labels_manual"))
    for name, counts, ink, slots in report:
        print(f"{name:38s} 글자 {counts['texts']:4d} (값 {counts['values']:3d}) 선 {counts['rules']:4d} 기재란 {counts['slots']:4d} ({slots}) 그림 {counts['assets']:2d}" + (f"  잉크 일치 {ink}" if ink is not None else ""))


if __name__ == "__main__":
    main()
