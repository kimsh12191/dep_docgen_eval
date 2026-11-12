"""채점: 정답 html 과 만든 html 을 비교한다. 규칙 기반이고, 같은 입력이면 늘 같은 점수가 나온다.

L0 유효성   validate.py: 규격대로 읽히는가 (빈 문서·값 자리 없음·script·외부 주소·잘린 표)        → valid
L1 문구     인쇄 문구의 두 글자 묶음(띄어쓰기 무시)이 겹치는 정도                                → text_f1
L2 표       tables.py: 맞닿은 칸끼리의 관계가 겹치는 정도, 합친 칸을 살린 비율                    → table_f1, span_recall
L3 값 자리  정답 값 자리와 만든 값 자리를 1:1 로 짝짓는다.
            짝이 될 수 있는 조건: 항목명이 비슷하다(≥0.8) 또는 둘레가 비슷하다(≥0.8).
              둘레 = 같은 칸의 인쇄 문구 + 왼쪽 칸 + 위 칸 (표 밖이면 같은 문단의 앞 글자 + 뒤에 오는 문구)
            여러 짝이 가능하면 비용 = 1 − (0.5·항목명 + 0.4·둘레 + 0.1·문서 안 순서) 가 가장 작게.
            맞은 값 자리 = 짝 ∧ 갈래(값/체크/도장·서명)가 같음                                  → field_f1
            엄격하게   = 위 + 항목명도 비슷 + 둘레도 비슷                                       → field_f1_strict
            짝지은 것 중 항목명·둘레·종류·체크 보기가 맞은 비율은 따로 보고
숫자(0.8, 가중치)는 가설이다. 자체 검증으로 확인했고, 파일럿에서 사람 판정과 맞춰 고친다.
"""
from __future__ import annotations

from difflib import SequenceMatcher

from . import htmldoc
from ..match import BIG, _f1, hungarian, label_sim, norm_label, text_score
from .tables import tables_score
from .validate import validate

VERSION = "score-html-0.1"
SAME = 0.8
W_LABEL, W_PLACE, W_ORDER = 0.5, 0.4, 0.1


def _place(f: dict) -> str:
    """값 자리의 둘레. 표 안: 같은 칸 글자 | 왼쪽 칸 | 위 칸. 표 밖: 같은 문단의 앞 글자 | 뒤에 오는 문구.
    그것이 모두 비면 문서에서 바로 앞·뒤에 나온 문구를 쓴다."""
    parts = [f["own"], f["left"], f["up"]] if f["in_table"] else [f["before"], f["next"]]
    if not any(parts):
        parts = [f["prev"], f["next"]]
    return "|".join(norm_label(x) for x in parts)


def place_sim(a: dict, b: dict) -> float:
    x, y = _place(a), _place(b)
    if x == y:
        return 1.0
    if not x.strip("|") or not y.strip("|"):
        return 0.0
    return SequenceMatcher(None, x, y).ratio()


def field_score(gt: dict, pred: dict) -> dict:
    G, P = gt["fields"], pred["fields"]
    pairs = []
    if G and P:
        sims, cost = {}, []
        for i, g in enumerate(G):
            row = []
            for j, p in enumerate(P):
                lab, plc = label_sim(g["label"], p["label"]), place_sim(g, p)
                sims[(i, j)] = (lab, plc)
                ok = lab >= SAME or plc >= SAME
                row.append(1 - (W_LABEL * lab + W_PLACE * plc + W_ORDER * (1 - abs(g["rank"] - p["rank"]))) if ok else BIG)
            cost.append(row)
        pairs = [(i, j) + sims[(i, j)] for i, j in hungarian(cost) if cost[i][j] < BIG]
    n = len(pairs)
    good = [(i, j, lab, plc) for i, j, lab, plc in pairs if G[i]["kind"] == P[j]["kind"]]
    strict = [t for t in good if t[2] >= SAME and t[3] >= SAME]
    p, r, f = _f1(len(good), len(P), len(G))
    checks = [(i, j) for i, j, _, _ in pairs if G[i]["kind"] == "check" and P[j]["kind"] == "check"]
    opt = lambda i, j: {norm_label(o) for o in G[i]["options"]} == {norm_label(o) for o in P[j]["options"]}
    hit = {i for i, _, _, _ in pairs}
    return {
        "field_f1": round(f, 4), "field_p": round(p, 4), "field_r": round(r, 4),
        "field_f1_strict": round(_f1(len(strict), len(P), len(G))[2], 4),
        "label_acc": round(sum(lab >= SAME for _, _, lab, _ in pairs) / n, 4) if n else None,
        "place_acc": round(sum(plc >= SAME for _, _, _, plc in pairs) / n, 4) if n else None,
        "type_acc": round(sum(G[i]["type"] == P[j]["type"] for i, j, _, _ in pairs) / n, 4) if n else None,
        "option_acc": round(sum(opt(i, j) for i, j in checks) / len(checks), 4) if checks else None,
        "fields_gt": len(G), "fields_pred": len(P), "matched": n,
        "missed": [G[i]["label"] or G[i]["key"] for i in range(len(G)) if i not in hit][:40],
    }


def score_docs(gt: dict, pred: dict) -> dict:
    out = {"version": VERSION}
    out.update(validate(pred))
    out.update(field_score(gt, pred))
    out.update(tables_score(gt["tables"], pred["tables"]))
    out.update(text_score(gt, pred))
    return out


def score_html(ref_html: str, out_html: str) -> dict:
    return score_docs(htmldoc.parse(ref_html), htmldoc.parse(out_html))


# 통과 기준 (임시). 사람 판정으로 기준선을 맞추기 전까지의 가설 값이다.
PASS = {"field_f1": 0.8, "table_f1": 0.8, "span_recall": 0.8, "text_f1": 0.8}


def passed(s: dict, rule: dict = PASS) -> bool:
    if not s.get("valid"):
        return False
    return all(s.get(k) is None or s[k] >= v for k, v in rule.items())
