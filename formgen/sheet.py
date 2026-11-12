"""라벨(docgen 이 그리며 잰 것) → 채점용 '쪽 요약(sheet)'.

sheet = {"pages": n, "fields": [...], "texts": [...], "rows": {목록: 행 수}}
- 좌표는 쪽 너비를 1 로 한 단위 (x/W, y/W). 가로·세로 거리를 같은 자로 잰다.
- 반복 표는 열마다 한 번만 남긴다 (첫 행 자리). 행 수는 rows 에 따로.
- 체크 칸의 자리는 보기 전체를 감싼 상자 (고른 보기는 서류마다 달라지므로).
- texts 는 인쇄된 고정 문구만 (값 칸 안의 글자, 도장 글자는 뺀다).
"""
from __future__ import annotations

import re

LIST_KEY = re.compile(r"^(.*?)\.(\d+)\.(.+)$")

# 종류(type7): 분석기 서식이 쓰는 7종으로 모은다. 큰 갈래(kind): 값 / 체크 / 도장·서명.
TYPE7 = {"text": "text", "rrn": "text", "phone": "text", "account_no": "text", "biz_no": "text", "corp_reg_no": "text",
         "number": "number", "percent": "number", "amount": "amount", "amount_korean": "amount",
         "date": "date", "datetime": "date", "month": "date",
         "checkbox": "checkbox", "checkbox_multi": "checkbox", "seal": "seal", "signature": "signature"}
KIND = {"checkbox": "check", "seal": "mark", "signature": "mark"}


def type7(t: str | None) -> str:
    return TYPE7.get(t or "text", "text")


def kind(t: str | None) -> str:
    return KIND.get(type7(t), "value")


def _union(boxes):
    boxes = [b for b in boxes if b]
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)] if boxes else None


def _field_box(f: dict):
    if f.get("options"):
        return _union([o.get("bbox") for o in f["options"]] + [o.get("box_bbox") for o in f["options"]]) or f.get("bbox")
    return f.get("bbox")


def from_label(label: dict) -> dict:
    sizes = label["pages"]
    fields, rows, firsts = [], {}, {}
    for f in label["fields"]:
        box, page = _field_box(f), f.get("page") or 0
        if not box or page >= len(sizes):
            continue
        w = float(sizes[page]["width"])
        rec = {"key": f["key"], "label": f.get("label") or "", "type": type7(f.get("type")), "kind": kind(f.get("type")),
               "page": page, "box": [round(v / w, 5) for v in box], "list": None}
        m = LIST_KEY.match(f["key"])
        if m:
            name, idx, col = m.group(1), int(m.group(2)), m.group(3)
            rows[name] = max(rows.get(name, 0), idx + 1)
            rec.update(list=name, key=f"{name}.*.{col}", _idx=idx)
            firsts.setdefault(name, {})
            top = firsts[name].setdefault("_top", (idx, rec["box"][1], rec["box"][3], page))
            if idx < top[0]:
                firsts[name]["_top"] = (idx, rec["box"][1], rec["box"][3], page)
            old = firsts[name].get(col)
            if old is None or idx < old["_idx"]:
                firsts[name][col] = rec
            continue
        fields.append(rec)
    for name, cols in firsts.items():   # 열마다 하나: 가로 자리는 그 열, 세로 자리는 첫 행
        _, y0, y1, page = cols.pop("_top")
        for rec in cols.values():
            rec = dict(rec)
            rec.pop("_idx")
            h = rec["box"][3] - rec["box"][1]
            rec["box"] = [rec["box"][0], y0, rec["box"][2], y0 + h]
            rec["page"] = page
            fields.append(rec)
    texts = []
    raw_boxes = [(f.get("page") or 0, _field_box(f)) for f in label["fields"] if _field_box(f)]
    for t in label.get("texts") or []:
        if t.get("kind") != "text" or not t.get("bbox") or not (t.get("text") or "").strip():
            continue
        p, b = t.get("page") or 0, t["bbox"]
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        if any(p == fp and fb[0] - 1 <= cx <= fb[2] + 1 and fb[1] - 1 <= cy <= fb[3] + 1 for fp, fb in raw_boxes):
            continue   # 값 칸 안의 글자 = 값
        w = float(sizes[p]["width"]) if p < len(sizes) else 1.0
        texts.append({"text": t["text"].strip(), "page": p, "box": [round(v / w, 5) for v in b]})
    return {"pages": len(sizes), "aspect": round(sizes[0]["height"] / sizes[0]["width"], 4) if sizes else None,
            "fields": fields, "texts": texts, "rows": rows,
            "overflow": bool(label.get("overflow")), "checks": label.get("checks") or []}


def first_page(sheet: dict) -> dict:
    """평가 항목은 한 쪽 이미지 하나: 1쪽의 칸·글자만 남긴다."""
    out = dict(sheet)
    out["fields"] = [f for f in sheet["fields"] if f["page"] == 0]
    out["texts"] = [t for t in sheet["texts"] if t["page"] == 0]
    return out
