"""golden set 만들기 (평가 세트를 만들 때만 쓴다. 벤치마크를 돌릴 때는 필요 없다).

재료: document_gen 저장소(docgen_share 브랜치)의 원본 서식 docgen/forms/hf### — 하나은행 공개 서식 PDF + 칸 위치(fields.json).
항목 하나를 이렇게 만든다.
  image.png   docgen 이 가짜 고객 값을 채워 그린 1쪽 그림 (모델 입력)
  ref.svg     정답: 인쇄 문구(원본 PDF 의 글자와 위치) + 선(원본 PDF 의 선) + 값 자리(fields.json 의 칸, 없으면 그릴 때 잰 위치)
  meta.json   출처·난이도·센 숫자·검수 상태

필요한 것: document_gen 체크아웃과 그 실행 환경(playwright), pymupdf.
실행: python tools/build_golden.py --docgen /path/to/document_gen --out bench/golden_v1
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from formgen import svg  # noqa: E402

# 난이도마다 4종, 서식 분류가 겹치지 않게 골랐다. 상은 값 자리 31~40 으로 묶어 모델 출력이 토큰 한도 안에 들 만한 것만.
GOLDEN = ["hf138", "hf284", "hf350", "hf399",      # 하
          "hf004", "hf109", "hf254", "hf420",      # 중
          "hf011", "hf153", "hf191", "hf225"]      # 상
WIDTH = 794
VALUE_TYPES = {"date": "date", "amount": "amount", "number": "number", "seal": "seal", "signature": "signature", "checkbox": "checkbox"}


def tier_of(stats: dict) -> tuple[str, str]:
    """docs 의 난이도 기준. 셋 중 하나라도 윗단계면 윗단계."""
    levels = {"값 자리": (stats["fields"], 10, 30), "체크 묶음": (stats["checkbox_groups"], 2, 10), "인쇄 문자": (stats["text_chars"], 599, 1699)}
    rank = {k: (0 if n <= lo else 1 if n <= hi else 2) for k, (n, lo, hi) in levels.items()}
    top = max(rank.values())
    return "하중상"[top], ", ".join(f"{k} {levels[k][0]}" for k, r in rank.items() if r == top)


def overlap_small(a, b) -> float:
    """겹친 넓이 ÷ 작은 쪽 넓이. 상자 = [x0, y0, x1, y1]."""
    w, h = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    return w * h / min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))


def gold_fields(form: dict, label: dict, k_pt: float, k_px: float) -> list[dict]:
    by_key = {f["key"]: f for f in label["fields"]}
    out, used = [], set()
    scale = lambda box, k: [round(v * k, 1) for v in box]
    for item in form["items"]:
        if item.get("t") == "skip" or item.get("page", 0) != 0:
            continue
        key = item.get("key")
        if item.get("t") == "check":
            rects = [o["rect"] for o in item.get("options", []) if o.get("rect")]
            options = list(dict.fromkeys(o["text"].strip() for o in item.get("options", []) if o.get("text", "").strip()))
            if not rects or not options:
                continue
            box = [min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)]
            out.append({"label": item.get("label", ""), "type": "checkbox", "options": options, "box": scale(box, k_pt)})
        elif item.get("rect"):
            typ = VALUE_TYPES.get((by_key.get(key) or {}).get("type"), "text")
            out.append({"label": item.get("label", ""), "type": typ if typ != "checkbox" else "text", "options": [], "box": scale(item["rect"], k_pt)})
        else:
            continue
        used.add(key)
    for f in label["fields"]:   # 칸 위치가 파일에 없는 것 (서명·도장·작성일·은행 확인란): 그릴 때 잰 위치
        if f.get("page") != 0 or not f.get("bbox") or f["key"] in used or f["type"] == "checkbox":
            continue
        box = scale(f["bbox"], k_px)
        if any(overlap_small(box, g["box"]) > 0.5 for g in out):
            continue
        out.append({"label": f.get("label", ""), "type": VALUE_TYPES.get(f["type"], "text"), "options": [], "box": box})
    return [g for g in out if g["label"].strip() and g["box"][2] - g["box"][0] > 1 and g["box"][3] - g["box"][1] > 1]


def build_svg(pdf_page, fields: list[dict], k: float, height: int) -> str:
    n = lambda v: f"{v * k:.1f}"
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}">',
             f'<rect x="0" y="0" width="{WIDTH}" height="{height}" fill="white"/>']
    for d in pdf_page.get_drawings():
        for it in d["items"]:
            if it[0] == "re":
                r = it[1]
                fill = "#e6e6e6" if d.get("fill") and sum(d["fill"]) < 2.9 and r.width > 3 and r.height > 3 else "none"
                parts.append(f'<rect x="{n(r.x0)}" y="{n(r.y0)}" width="{n(r.width)}" height="{n(r.height)}" fill="{fill}" stroke="{"black" if d.get("color") else "none"}" stroke-width="0.5"/>')
            elif it[0] == "l":
                parts.append(f'<line x1="{n(it[1].x)}" y1="{n(it[1].y)}" x2="{n(it[2].x)}" y2="{n(it[2].y)}" stroke="black" stroke-width="0.5"/>')
    for block in pdf_page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(ch for s in line["spans"] for ch in s["text"] if ch >= " " and ch not in "\ufffe\uffff").strip()
            if text:
                s = line["spans"][0]
                parts.append(f'<text x="{n(line["bbox"][0])}" y="{n(s["origin"][1])}" font-size="{n(s["size"])}" font-family="Malgun Gothic">{escape(text)}</text>')
    for i, f in enumerate(fields, 1):
        x0, y0, x1, y1 = f["box"]
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(WIDTH, x1), min(height, y1)
        options = f' data-options={quoteattr("|".join(f["options"]))}' if f["type"] == "checkbox" else ""
        parts.append(f'<rect data-field="f{i:03d}" data-label={quoteattr(f["label"])} data-type="{f["type"]}"{options} '
                     f'x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" fill="none" stroke="none"/>')
    return "\n".join(parts) + "\n</svg>\n"


def build(docgen: Path, form_id: str, out: Path, seed: int = 0) -> dict:
    import pymupdf
    form_dir = docgen / "docgen" / "forms" / form_id
    form = json.loads((form_dir / "fields.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, "-m", "docgen.preview", form_id, "--seed", str(seed), "--out", tmp], cwd=docgen, check=True, capture_output=True)
        run = next(Path(tmp).glob(f"{form_id}/*/label.json")).parent
        label = json.loads((run / "label.json").read_text(encoding="utf-8"))
        item = out / form_id
        item.mkdir(parents=True, exist_ok=True)
        shutil.copy(run / Path(label["images"][0]).name, item / "image.png")
    page = pymupdf.open(form_dir / "look" / "original.pdf")[0]
    k = WIDTH / page.rect.width
    height = round(page.rect.height * k)
    fields = gold_fields(form, label, k, WIDTH / label["pages"][0]["width"])
    value = build_svg(page, fields, k, height)
    checked = svg.parse(value)
    if not checked["valid"]:
        raise SystemExit(f"{form_id}: 정답이 규격에 안 맞음 {checked['issues']}")
    (item / "ref.svg").write_text(value, encoding="utf-8")
    stats = svg.stats(value)
    tier, why = tier_of(stats)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=docgen, capture_output=True, text=True).stdout.strip()
    meta = {"id": form_id, "name": form["name"], "class": form.get("class"), "tier": tier, "tier_reason": why,
            "fields": stats["fields"], "checkbox_groups": stats["checkbox_groups"], "text_chars": stats["text_chars"],
            "source": f"document_gen@{commit} docgen/forms/{form_id} (하나은행 공개 서식 No.{form.get('no')})", "seed": seed,
            "image": "docgen 이 가짜 값을 채워 그린 1쪽", "reviewed_by_human": False}
    (item / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docgen", required=True, help="document_gen 저장소 경로")
    ap.add_argument("--out", default="bench/golden_v1")
    ap.add_argument("--ids", nargs="*", default=GOLDEN)
    a = ap.parse_args()
    for form_id in a.ids:
        m = build(Path(a.docgen).resolve(), form_id, Path(a.out))
        print(m["id"], m["tier"], m["tier_reason"], "|", m["class"], m["name"])


if __name__ == "__main__":
    main()
