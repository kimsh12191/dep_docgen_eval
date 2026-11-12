"""SVG 서식 규격(svg-v1): 읽기·검사(parse), 채점(score), 난이도 특징 세기(stats), 그림으로 그리기(render).

읽기와 채점은 파이썬 표준 라이브러리만 쓴다. 그리기만 resvg_py 를 그때 불러온다 (브라우저 불필요). 규격은 SVG_SPEC.md.

채점 규칙 (같은 입력이면 늘 같은 점수)
  짝짓기         정답 값 자리와 만든 값 자리를 **자리로** 1:1 짝짓는다 (겹침 IoU ≥ 0.1 이거나 한쪽 가운데가 다른 쪽 안).
                 여럿이 가능하면 겹침이 큰 쪽으로. 좌표는 쪽 크기로 나눠 비교하므로 쪽 크기가 달라도 된다.
  field_recall   짝이 있고 갈래(값 / 체크 / 도장·서명)가 같은 정답 값 자리의 비율          ← 통과 기준에 쓴다
  field_precision 만든 값 자리 중 위와 같이 맞은 비율. 정답에 빠진 칸이 있을 수 있어 참고로만 본다.
  label_acc      짝 중 항목명이 비슷한(≥ 0.8) 비율        type_acc  짝 중 종류(data-type)가 똑같은 비율
  iou_mean       짝의 겹침 평균
  text_f1 · text_p · text_r   <text> 글자의 두 글자 묶음이 겹치는 정도 (그림을 OCR 하지 않는다)
  valid          규격 검사 통과 여부. 보기에 쓸 만한지는 재지 않는다.
자리를 먼저 보는 까닭: 항목명은 모델마다 다르게 적어도 틀린 것이 아니고, 정답의 항목명도 자동으로 뽑은 것이라 완전하지 않다.
"""
from __future__ import annotations

import hashlib
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .match import hungarian, label_sim, text_score

NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)

VERSION = "svg-v1"          # 규격 버전
SCORER = "score-1"         # 채점 규칙 버전
TYPES = {"text", "number", "amount", "date", "checkbox", "seal", "signature"}
ALLOWED = {"svg", "g", "rect", "line", "polyline", "polygon", "path", "circle", "ellipse", "text", "tspan", "title", "desc"}
KEY = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$")
MAX_SIDE = 5000
LABEL_SAME = 0.8   # 항목명이 이만큼 비슷하면 같은 이름으로 본다
MATCH_IOU = 0.1    # 이만큼 겹치면 같은 자리 후보로 본다
NO_MATCH = 1000

def _name(qualified: str) -> str:
    return qualified.split("}")[-1]


def _viewbox(root) -> tuple[float, float]:
    box = [float(x) for x in root.get("viewBox", "").replace(",", " ").split()]
    if len(box) != 4 or not all(math.isfinite(x) for x in box) or box[:2] != [0, 0] or min(box[2:]) <= 0 or max(box[2:]) > MAX_SIDE:
        raise ValueError
    return box[2], box[3]


def parse(value: str) -> dict:
    """{"valid", "issues": [코드…], "fields": [{key, label, type, options, bbox:[x,y,w,h]}], "texts": [글자…], "width", "height"}"""
    result = {"valid": False, "issues": [], "fields": [], "texts": [], "width": 0, "height": 0}
    issues = result["issues"]
    if re.search(r"<!DOCTYPE|<!ENTITY", value, re.I):
        issues.append("doctype_or_entity")
        return result
    try:
        root = ET.fromstring(value)
    except ET.ParseError:
        issues.append("invalid_xml")
        return result
    if root.tag != "{" + NS + "}svg":
        issues.append("root_namespace")
    if "transform" in root.attrib:
        issues.append("root_transform")
    try:
        result["width"], result["height"] = _viewbox(root)
    except ValueError:
        issues.append("viewbox")

    root_children = set(root)
    seen_keys = set()

    def field(e, name):
        key, typ, label = e.get("data-field", ""), e.get("data-type", ""), e.get("data-label", "")
        if e not in root_children or name != "rect" or "transform" in e.attrib:
            issues.append("field_must_be_root_rect")
        if not KEY.fullmatch(key) or key in seen_keys:
            issues.append("field_key")
        seen_keys.add(key)
        if typ not in TYPES:
            issues.append("field_type")
        if not label.strip():
            issues.append("field_label")
        options = e.get("data-options", "").split("|") if e.get("data-options") else []
        if typ == "checkbox" and (not options or len(set(options)) != len(options)):
            issues.append("field_options")
        try:
            x, y, w, h = [float(e.get(k, "")) for k in ("x", "y", "width", "height")]
            if not all(math.isfinite(v) for v in (x, y, w, h)) or min(w, h) <= 0:
                raise ValueError
        except ValueError:
            issues.append("field_bbox")
            return
        if x < 0 or y < 0 or x + w > result["width"] + 0.01 or y + h > result["height"] + 0.01:
            issues.append("field_outside_page")
        result["fields"].append({"key": key, "label": label, "type": typ, "options": options, "bbox": [x, y, w, h]})

    def walk(e, in_field=False):
        name = _name(e.tag)
        # 숨긴 문서는 유효하지 않다. 값 자리 rect 는 원래 보이지 않는 것이라 검사하지 않는다.
        if name in {"svg", "g", "text"}:
            try:
                invisible = float(e.get("opacity", "1").strip().rstrip("%")) <= 0
            except ValueError:
                invisible = False
            if e.get("display") == "none" or e.get("visibility") in {"hidden", "collapse"} or invisible:
                issues.append("hidden_content")
        if name not in ALLOWED:
            issues.append("unsupported_element:" + name)
        for k, v in e.attrib.items():
            attr = _name(k)
            if attr.lower().startswith("on") or attr in {"href", "style", "class"} or re.search(r"url\s*\(", v, re.I):
                issues.append("forbidden_attribute:" + attr)
        is_field = "data-field" in e.attrib
        if is_field:
            field(e, name)
        if name == "text" and not in_field:
            result["texts"].append("".join(e.itertext()))
        for child in e:
            walk(child, in_field or is_field)

    walk(root)
    if not result["fields"]:
        issues.append("no_fields")
    if not result["texts"]:
        issues.append("no_editable_text")
    result["issues"] = sorted(set(issues))
    result["valid"] = not issues
    return result


KIND = {"checkbox": "check", "seal": "mark", "signature": "mark"}   # 그 밖은 "value"


def _box(f: dict, doc: dict) -> tuple:
    x, y, w, h = f["bbox"]
    return x / doc["width"], y / doc["height"], w / doc["width"], h / doc["height"]


def _iou(a: tuple, b: tuple) -> float:
    overlap = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])) * max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return overlap / (a[2] * a[3] + b[2] * b[3] - overlap)


def _inside(a: tuple, b: tuple) -> bool:
    """a 의 가운데가 b 안에 있나."""
    cx, cy = a[0] + a[2] / 2, a[1] + a[3] / 2
    return b[0] <= cx <= b[0] + b[2] and b[1] <= cy <= b[1] + b[3]


def score(reference: str, prediction: str) -> dict:
    """정답 svg 와 만든 svg 를 비교한다. 정답이 규격에 안 맞으면 ValueError."""
    ref, pred = parse(reference), parse(prediction)
    if not ref["valid"]:
        raise ValueError("Invalid reference: " + ",".join(ref["issues"]))
    G, P = ref["fields"], pred["fields"]
    pairs = []
    if G and P and pred["width"] and pred["height"]:
        gb, pb = [_box(f, ref) for f in G], [_box(f, pred) for f in P]
        iou = [[_iou(a, b) for b in pb] for a in gb]
        near = lambda i, j: iou[i][j] >= MATCH_IOU or _inside(gb[i], pb[j]) or _inside(pb[j], gb[i])
        costs = [[1 - iou[i][j] - 0.01 * label_sim(G[i]["label"], P[j]["label"]) if near(i, j) else NO_MATCH for j in range(len(P))] for i in range(len(G))]
        pairs = [(i, j) for i, j in hungarian(costs) if costs[i][j] < NO_MATCH]
    kind = lambda f: KIND.get(f["type"], "value")
    right = [(i, j) for i, j in pairs if kind(G[i]) == kind(P[j])]
    share = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
    recall = len(right) / len(G)
    precision = len(right) / len(P) if P else 0.0
    return {"scorer": SCORER, "valid": pred["valid"], "issues": pred["issues"],
            "fields_gt": len(G), "fields_pred": len(P), "fields_matched": len(right),
            "field_recall": round(recall, 4), "field_precision": round(precision, 4),
            "field_f1": round(2 * recall * precision / (recall + precision), 4) if recall + precision else 0.0,
            "label_acc": share([label_sim(G[i]["label"], P[j]["label"]) >= LABEL_SAME for i, j in right]),
            "type_acc": share([G[i]["type"] == P[j]["type"] for i, j in right]),
            "iou_mean": share([iou[i][j] for i, j in right]),
            **text_score(ref["texts"], pred["texts"])}


def stats(value: str) -> dict:
    """svg 에서 세는 난이도 특징: 값 자리 수, 체크 묶음 수, 인쇄 문자 수 (기준은 README 의 난이도 표)."""
    doc = parse(value)
    return {"valid": doc["valid"], "issues": doc["issues"], "fields": len(doc["fields"]),
            "checkbox_groups": sum(f["type"] == "checkbox" for f in doc["fields"]),
            "text_chars": sum(len("".join(t.split())) for t in doc["texts"]),
            "types": {t: n for t in sorted(TYPES) if (n := sum(f["type"] == t for f in doc["fields"]))}}


def render(value: str, output, font_files=None) -> dict:
    """svg → png. resvg_py 가 필요하다 (requirements-svg.txt). 쓴 그리기 도구 버전과 글꼴 해시를 돌려준다."""
    parsed = parse(value)
    if not parsed["valid"]:
        raise ValueError("Invalid SVG: " + ",".join(parsed["issues"]))
    import resvg_py
    fonts = [str(Path(p).resolve()) for p in (font_files or [])]
    for p in fonts:
        if not Path(p).is_file():
            raise ValueError("Font missing: " + p)
    png = resvg_py.svg_to_bytes(svg_string=value, background="white", width=round(parsed["width"]), height=round(parsed["height"]),
                                font_files=fonts or None, skip_system_fonts=bool(fonts))
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_bytes(png)
    return {"renderer": "resvg_py", "version": resvg_py.__version__,
            "font_mode": "explicit" if fonts else "system_unpinned",
            "fonts": [{"file": Path(p).name, "sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest()} for p in fonts]}
