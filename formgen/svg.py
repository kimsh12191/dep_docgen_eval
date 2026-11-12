"""SVG 서식 규격(svg-v1): 읽기·검사(parse), 채점(score), 그림으로 그리기(render).

읽기와 채점은 파이썬 표준 라이브러리만 쓴다. 그리기만 resvg_py 를 그때 불러온다 (브라우저 불필요).
규격 설명은 SVG_SPEC.md.

채점 규칙 (같은 입력이면 늘 같은 점수)
  값 자리 짝짓기   항목명이 비슷한(≥ LABEL_SAME) 것끼리만 짝이 될 수 있다.
                   여러 짝이 가능하면 (1 − 항목명 비슷함) + (1 − 겹침 IoU) 가 가장 작게 1:1 로 짝짓는다.
  typed_field_f1   짝 ∧ 종류(data-type)가 같음 ∧ 체크 보기(data-options)가 같음
  located_field_f1 위 + 자리 겹침 IoU ≥ IOU_SAME   (좌표는 쪽 크기로 나눠 비교하므로 쪽 크기가 달라도 된다)
  field_iou_mean   맞은 값 자리의 IoU 합 ÷ 정답 값 자리 수 (빠뜨린 것은 0)
  text_f1 · text_p · text_r   <text> 글자의 두 글자 묶음이 겹치는 정도 (그림을 OCR 하지 않는다)
  valid            규격 검사 통과 여부. 보기에 쓸 만한지는 재지 않는다.
숫자 0.8, 0.5 는 가설이다. final_pass 는 사람 판정으로 기준을 맞추기 전까지 늘 None 이다.
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

VERSION = "svg-v1"
TYPES = {"text", "number", "amount", "date", "checkbox", "seal", "signature"}
ALLOWED = {"svg", "g", "rect", "line", "polyline", "polygon", "path", "circle", "ellipse", "text", "tspan", "title", "desc"}
KEY = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$")
MAX_SIDE = 5000
LABEL_SAME = 0.8   # 항목명이 이만큼 비슷해야 짝이 될 수 있다 (가설)
IOU_SAME = 0.5     # 자리가 이만큼 겹쳐야 맞은 자리로 본다 (가설)
NO_MATCH = 1000

LIMITATIONS = [
    "Declared field rectangles are checked; actual text/line geometry is not fully checked",
    "No browser layout, table topology or downstream OCR/KIE score",
    "Field aliases and alternative date splitting are not implemented",
]


def tag(e) -> str:
    """요소의 이름 (네임스페이스 뗀 것). svg_eval_v2 도 쓴다."""
    return _name(e.tag)


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


def _iou(f: dict, doc: dict, g: dict, other: dict) -> float:
    """쪽 크기로 나눈 두 상자의 겹침 비율."""
    x, y, w, h = (f["bbox"][0] / doc["width"], f["bbox"][1] / doc["height"], f["bbox"][2] / doc["width"], f["bbox"][3] / doc["height"])
    u, v, s, t = (g["bbox"][0] / other["width"], g["bbox"][1] / other["height"], g["bbox"][2] / other["width"], g["bbox"][3] / other["height"])
    overlap = max(0, min(x + w, u + s) - max(x, u)) * max(0, min(y + h, v + t) - max(y, v))
    return overlap / (w * h + s * t - overlap)


def score(reference: str, prediction: str) -> dict:
    """정답 svg 와 만든 svg 를 비교한다. 정답이 규격에 안 맞으면 ValueError."""
    ref, pred = parse(reference), parse(prediction)
    if not ref["valid"]:
        raise ValueError("Invalid reference: " + ",".join(ref["issues"]))
    G, P = ref["fields"], pred["fields"]
    iou = lambda i, j: _iou(G[i], ref, P[j], pred)
    pairs = []
    if G and P and pred["width"] and pred["height"]:
        def cost(i, j):
            sim = label_sim(G[i]["label"], P[j]["label"])
            return 1 - sim + 1 - iou(i, j) if sim >= LABEL_SAME else NO_MATCH
        costs = [[cost(i, j) for j in range(len(P))] for i in range(len(G))]
        pairs = [(i, j) for i, j in hungarian(costs) if costs[i][j] < NO_MATCH]
    typed = [(i, j) for i, j in pairs if G[i]["type"] == P[j]["type"] and set(G[i]["options"]) == set(P[j]["options"])]
    located = [(i, j) for i, j in typed if iou(i, j) >= IOU_SAME]
    total = len(G) + len(P)
    return {"version": VERSION, "valid": pred["valid"], "issues": pred["issues"],
            "fields_gt": len(G), "fields_pred": len(P),
            "typed_field_f1": round(2 * len(typed) / total, 4),
            "located_field_f1": round(2 * len(located) / total, 4),
            "field_iou_mean": round(sum(iou(i, j) for i, j in typed) / len(G), 4),
            **text_score(ref, pred), "final_pass": None,
            "status": "diagnostic_uncalibrated", "geometry_threshold": IOU_SAME, "limitations": LIMITATIONS}


def stats(value: str) -> dict:
    """svg 에서 셀 수 있는 난이도 특징 (docs/DIFFICULTY_GUIDE.md 의 수동 분류를 돕는 숫자).
    합친 칸 수는 svg 에서 알 수 없어 사람이 원본을 보고 센다. 주석이 빠진 정답이면 값 자리 수는 실제보다 작다."""
    doc = parse(value)
    return {"valid": doc["valid"], "issues": doc["issues"], "fields": len(doc["fields"]),
            "checkbox_groups": sum(f["type"] == "checkbox" for f in doc["fields"]),
            "text_chars": sum(len("".join(t.split())) for t in doc["texts"]),
            "types": {t: n for t in sorted(TYPES) if (n := sum(f["type"] == t for f in doc["fields"]))},
            "merged_cells": None}


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
