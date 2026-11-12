"""난이도: 정답 html 에서 세는 것과 상·중·하 기준 (v1 초안, 가설).

하나라도 윗단계에 걸리면 윗단계다. 경계 숫자는 파일럿에서 다시 잡는다.
새 이미지(정답 html 이 없는 것)의 난이도를 그림만으로 재는 측정기는 아직 없다.
"""
from __future__ import annotations

from . import htmldoc

# (중 시작, 상 시작)
RULE_V1 = {"fields": (11, 31), "spans": (3, 11), "checks": (3, 11), "chars": (600, 1700)}
VERSION = "difficulty-v1"


def features(doc: dict) -> dict:
    cells = [c for t in doc["tables"] for c in t]
    spans = sum(1 for c in cells if c["r1"] > c["r0"] or c["c1"] > c["c0"])
    return {"fields": len(doc["fields"]), "checks": sum(f["kind"] == "check" for f in doc["fields"]),
            "marks": sum(f["kind"] == "mark" for f in doc["fields"]), "tables": len(doc["tables"]), "cells": len(cells),
            "spans": spans, "span_share": round(spans / len(cells), 3) if cells else 0.0,
            "chars": sum(len("".join(t.split())) for t in doc["texts"])}


def tier(feat: dict, rule: dict = RULE_V1):
    level = {k: (2 if feat[k] >= hi else 1 if feat[k] >= mid else 0) for k, (mid, hi) in rule.items()}
    top = max(level.values())
    return "하중상"[top], [k for k, v in level.items() if v == top and top > 0]


def of_html(html: str) -> dict:
    feat = features(htmldoc.parse(html))
    t, why = tier(feat)
    return {"tier": t, "why": why, "features": feat, "rule": VERSION}
