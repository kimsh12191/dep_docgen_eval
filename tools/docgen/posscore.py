"""채점: 정답 쪽 요약(gt sheet) 과 만든 쪽 요약(pred sheet) 을 비교한다.

L0 유효성   그려졌나, 검사 오류·넘침이 없나, 쪽 수가 같나            → valid (False 면 이 항목은 불통과)
L1 문구     인쇄된 고정 문구의 낱말 일치 (순서 무관)                   → text_f1
L3 칸       정답 칸과 1:1 로 짝짓고 (자리), 큰 갈래(값/체크/도장·서명)까지 맞은 것  → field_f1
            거기에 항목명까지 맞은 것                                   → field_f1_label
            (둘 중 무엇을 주 지표로 할지는 파일럿에서 사람 판정과 맞춰 정한다. 자체 검증에서
             다른 서식을 넣었을 때 field_f1 은 0.26, field_f1_label 은 0.07 이 나왔다.)
            짝지은 칸의 항목명·종류 일치율, 자리 오차는 따로 보고
L2 표 구조, L4 모양은 아직 없다 (README 의 '아직 없는 것').
"""
from __future__ import annotations

from collections import Counter

from formgen.match import dist, label_sim, match_fields

TOL = 0.03          # 칸 짝짓기 허용 거리 (쪽 너비 = 1). 자체 검증(selftest)으로 정한 값
LABEL_OK = 0.8      # 항목명이 같다고 보는 비슷한 정도
VERSION = "score-0.2"


def _f1(tp: float, n_pred: int, n_gt: int):
    p = tp / n_pred if n_pred else (1.0 if not n_gt else 0.0)
    r = tp / n_gt if n_gt else (1.0 if not n_pred else 0.0)
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def text_score(gt: dict, pred: dict) -> dict:
    a, b = Counter(t["text"] for t in gt["texts"]), Counter(t["text"] for t in pred["texts"])
    tp = sum((a & b).values())
    p, r, f = _f1(tp, sum(b.values()), sum(a.values()))
    return {"text_p": round(p, 4), "text_r": round(r, 4), "text_f1": round(f, 4), "text_gt": sum(a.values()), "text_pred": sum(b.values())}


def field_score(gt: dict, pred: dict, tol: float = TOL, align: bool = True) -> dict:
    G, P = gt["fields"], pred["fields"]
    pairs, tf = match_fields(G, P, tol=tol, align=align)
    kind_ok = [(i, j) for i, j, _ in pairs if G[i]["kind"] == P[j]["kind"]]
    p, r, f = _f1(len(kind_ok), len(P), len(G))
    label_ok = [(i, j) for i, j in kind_ok if label_sim(G[i]["label"], P[j]["label"]) >= LABEL_OK]
    lf = _f1(len(label_ok), len(P), len(G))[2]
    mp, mr, mf = _f1(len(pairs), len(P), len(G))
    n = len(pairs)
    raw = sorted(dist(G[i]["box"], P[j]["box"]) for i, j, _ in pairs)
    rows_ok = None
    if gt.get("rows"):
        want, got = sorted(gt["rows"].values()), sorted(pred.get("rows", {}).values())
        rows_ok = want == got
    return {
        "field_p": round(p, 4), "field_r": round(r, 4), "field_f1": round(f, 4),
        "field_f1_label": round(lf, 4),                             # 자리 + 갈래 + 항목명
        "match_f1": round(mf, 4),                                   # 자리만 본 짝 (갈래 무시)
        "label_acc": round(sum(label_sim(G[i]["label"], P[j]["label"]) >= LABEL_OK for i, j, _ in pairs) / n, 4) if n else None,
        "type_acc": round(sum(G[i]["type"] == P[j]["type"] for i, j, _ in pairs) / n, 4) if n else None,
        "pos_err": round(raw[len(raw) // 2], 4) if raw else None,   # 정렬 전 자리 오차 가운데값
        "shift": [round(tf[0][1], 4), round(tf[1][1], 4)], "scale": [round(tf[0][0], 4), round(tf[1][0], 4)],
        "fields_gt": len(G), "fields_pred": len(P), "matched": n, "rows_ok": rows_ok,
        "missed": [G[i]["key"] for i in range(len(G)) if i not in {a for a, _, _ in pairs}][:50],
    }


def validity(gt: dict, pred: dict | None, error: str | None = None) -> dict:
    """L0. pred 가 None 이면 그리기 실패."""
    why = []
    if pred is None:
        why.append("render_error")
    else:
        if pred.get("checks"):
            why.append("checks")
        if pred.get("overflow"):
            why.append("overflow")
        if pred.get("pages") != gt.get("pages"):
            why.append("pages")
    return {"valid": not why, "invalid_why": why, "error": (error or "")[:300] or None}


def score(gt: dict, pred: dict | None, error: str | None = None, tol: float = TOL) -> dict:
    out = {"version": VERSION, "tol": tol, **validity(gt, pred, error)}
    if pred is None:
        out.update(field_f1=0.0, field_f1_label=0.0, text_f1=0.0)
        return out
    out.update(field_score(gt, pred, tol=tol))
    out.update(text_score(gt, pred))
    return out
