"""표 구조 채점 (브라우저 없이, html 만으로).

규칙
1) html 의 <table> 을 격자로 편다: rowspan·colspan 을 풀어 칸마다 (시작 행, 끝 행, 시작 열, 끝 열) 을 준다.
   아무 칸도 쓰지 않는 격자선은 없앤다 (같은 모양을 더 촘촘한 격자로 적어도 같은 표로 본다).
2) 칸의 글자 = 인쇄 문구. 값 자리(data-field 가 붙은 요소) 안의 글자는 빼고 '⟨칸⟩' 표시 하나로 바꾼다 (값은 서류마다 다르므로).
3) 연속으로 같은 꼴인 행 (합친 칸이 없고, 칸 나눔과 인쇄 문구가 바로 윗행과 같은 행: 빈 반복 행) 은 한 번만 남긴다.
4) 이웃 관계: 격자에서 맞닿은 두 칸마다 (왼쪽 글자, 오른쪽 글자, '→') 또는 (위 글자, 아래 글자, '↓') 를 하나씩 만든다.
   합친 칸은 맞닿은 칸 모두와 관계를 갖는다. 그래서 합치기를 틀리면 관계가 달라진다.
5) 표 구조 점수 = 정답과 만든 것의 이웃 관계 묶음(중복 허용)의 F1.
   만든 칸의 글자는 정답 글자와 0.8 이상 비슷하면 같은 글자로 본다 (띄어쓰기·오타 한두 자).
6) 합친 칸 재현율 = 정답의 합친 칸 (글자, 세로 합침 수, 가로 합침 수) 중 만든 것에도 있는 비율.
7) 표가 여럿이면 정답 표와 만든 표를 점수가 가장 높게 1:1 로 짝짓고, 관계 수를 모두 더해 한 점수로 낸다.
   짝이 없는 정답 표는 모두 놓친 것, 짝이 없는 만든 표는 모두 틀린 것으로 센다.
"""
from __future__ import annotations

from collections import Counter

from .match import hungarian, label_sim, norm_label

FIELD = "⟨칸⟩"
SAME = 0.8


def to_int(v, default=1):
    try:
        return max(1, min(int(v), 200))
    except (TypeError, ValueError):
        return default


def grid(rows) -> list[dict]:
    """파서가 모은 행 [[{text:[…], frefs:[…], rowspan, colspan}]] → 칸 [{text, nfields, frefs, r0, r1, c0, c1}]."""
    taken, cells = set(), []
    for r, row in enumerate(rows):
        c = 0
        for cell in row:
            while (r, c) in taken:
                c += 1
            rs, cs = cell["rowspan"], cell["colspan"]
            for i in range(r, r + rs):
                for j in range(c, c + cs):
                    taken.add((i, j))
            frefs = list(cell.get("frefs") or [])
            cells.append({"text": " ".join(cell["text"]), "nfields": len(frefs), "frefs": frefs,
                          "r0": r, "r1": r + rs - 1, "c0": c, "c1": c + cs - 1})
            c += cs
    return _minimal(cells)


def _minimal(cells):
    for lo, hi in (("r0", "r1"), ("c0", "c1")):
        cuts = sorted({c[lo] for c in cells} | {c[hi] + 1 for c in cells})
        index = {v: i for i, v in enumerate(cuts)}
        for c in cells:
            c[lo], c[hi] = index[c[lo]], index[c[hi] + 1] - 1
    return cells


def _static_key(text: str) -> str:
    return norm_label(text.replace(FIELD, " "))


def collapse_rows(cells):
    """연속으로 같은 꼴인 행을 한 번만 남긴다. (남은 칸, 지워진 행에 있던 값 자리) 를 돌려준다.
    지워진 행의 값 자리가 남긴 행의 같은 자리에 없으면 그 자리로 옮긴다 (빈 값이라 표시가 빠진 칸)."""
    if not cells:
        return cells, []
    n_rows = max(c["r1"] for c in cells) + 1
    by_row = {r: sorted((c for c in cells if c["r0"] == r), key=lambda c: c["c0"]) for r in range(n_rows)}
    crossing = {r for c in cells if c["r1"] > c["r0"] for r in range(c["r0"], c["r1"] + 1)}
    sig = lambda r: None if r in crossing or not by_row[r] else tuple((c["c0"], c["c1"], _static_key(c["text"])) for c in by_row[r])
    keep, gone, kept_row = [], [], None
    for r in range(n_rows):
        s = sig(r)
        if s is not None and kept_row is not None and s == sig(kept_row):
            for kc, c in zip(by_row[kept_row], by_row[r]):
                if c["frefs"] and not kc["frefs"]:
                    kc["frefs"], kc["nfields"], kc["text"] = c["frefs"], c["nfields"], c["text"]
                else:
                    gone += c["frefs"]
            continue
        kept_row = r if s is not None else None
        keep.append(r)
    if len(keep) == n_rows:
        return cells, []
    alive = set(keep)
    out = [c for c in cells if c["r0"] in alive]
    return _minimal(out), gone


def parse_tables(html: str) -> list[list[dict]]:
    from .htmldoc import parse

    return parse(html)["tables"]


def _key(text: str) -> str:
    return norm_label(text.replace(FIELD, " 칸표시 ")) if text else ""


def relations(cells: list[dict], canon=None) -> Counter:
    name = [(_key(c["text"]) if canon is None else canon[i]) for i, c in enumerate(cells)]
    out = Counter()
    for i, a in enumerate(cells):
        for j, b in enumerate(cells):
            if i == j:
                continue
            if b["c0"] == a["c1"] + 1 and a["r0"] <= b["r1"] and b["r0"] <= a["r1"]:
                out[(name[i], name[j], "→")] += 1
            if b["r0"] == a["r1"] + 1 and a["c0"] <= b["c1"] and b["c0"] <= a["c1"]:
                out[(name[i], name[j], "↓")] += 1
    return out


def _canon(gt_cells, pred_cells):
    names = sorted({_key(c["text"]) for c in gt_cells})
    cache, out = {}, []
    for c in pred_cells:
        k = _key(c["text"])
        if k not in cache:
            if k in names or not k:
                cache[k] = k
            else:
                best = max(names, key=lambda n: label_sim(n, k), default=None)
                cache[k] = best if best and label_sim(best, k) >= SAME else k
        out.append(cache[k])
    return out


def _spans(cells, names) -> Counter:
    return Counter((n, c["r1"] - c["r0"] + 1, c["c1"] - c["c0"] + 1) for c, n in zip(cells, names) if c["r1"] > c["r0"] or c["c1"] > c["c0"])


def _counts(gt_cells, pred_cells):
    """(겹친 관계 수, 만든 관계 수, 정답 관계 수, 겹친 합친 칸 수, 정답 합친 칸 수)"""
    canon = _canon(gt_cells, pred_cells)
    a, b = relations(gt_cells), relations(pred_cells, canon)
    sg, sp = _spans(gt_cells, [_key(c["text"]) for c in gt_cells]), _spans(pred_cells, canon)
    return sum((a & b).values()), sum(b.values()), sum(a.values()), sum((sg & sp).values()), sum(sg.values())


def _f1(tp, n_pred, n_gt):
    p = tp / n_pred if n_pred else (1.0 if not n_gt else 0.0)
    r = tp / n_gt if n_gt else (1.0 if not n_pred else 0.0)
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def table_score(gt_cells: list[dict], pred_cells: list[dict]) -> dict:
    """표 하나끼리."""
    tp, n_pred, n_gt, stp, sn = _counts(gt_cells, pred_cells)
    p, r, f = _f1(tp, n_pred, n_gt)
    return {"table_f1": round(f, 4), "table_p": round(p, 4), "table_r": round(r, 4),
            "span_recall": round(stp / sn, 4) if sn else None,
            "cells_gt": len(gt_cells), "cells_pred": len(pred_cells), "spans_gt": sn,
            "spans_pred": sum(1 for c in pred_cells if c["r1"] > c["r0"] or c["c1"] > c["c0"]),
            "fields_gt": sum(c["nfields"] for c in gt_cells), "fields_pred": sum(c["nfields"] for c in pred_cells)}


def tables_score(gt_tables: list[list[dict]], pred_tables: list[list[dict]]) -> dict:
    """문서 전체: 표를 1:1 로 짝짓고 관계 수를 더한다. 정답에 관계가 하나도 없으면 table_f1 은 None (해당 없음)."""
    rel = lambda cells: sum(relations(cells).values())
    n_gt, n_pred = sum(rel(t) for t in gt_tables), sum(rel(t) for t in pred_tables)
    sn = sum(sum(_spans(t, [_key(c["text"]) for c in t]).values()) for t in gt_tables)
    out = {"tables_gt": len(gt_tables), "tables_pred": len(pred_tables), "spans_gt": sn,
           "spans_pred": sum(1 for t in pred_tables for c in t if c["r1"] > c["r0"] or c["c1"] > c["c0"])}
    if not n_gt:
        out.update(table_f1=None, table_p=None, table_r=None, span_recall=None)
        return out
    tp = stp = 0
    if gt_tables and pred_tables:
        counts = [[_counts(g, p) for p in pred_tables] for g in gt_tables]
        cost = [[1 - _f1(c[0], c[1], c[2])[2] for c in row] for row in counts]
        for i, j in hungarian(cost):
            tp += counts[i][j][0]
            stp += counts[i][j][3]
    p, r, f = _f1(tp, n_pred, n_gt)
    out.update(table_f1=round(f, 4), table_p=round(p, 4), table_r=round(r, 4), span_recall=round(stp / sn, 4) if sn else None)
    return out


def shape(cells: list[dict]) -> dict:
    """표의 복잡도: 행·격자 열 수, 칸 수, 합친 칸 수와 비율."""
    if not cells:
        return {"rows": 0, "grid_cols": 0, "cells": 0, "spans": 0, "span_share": 0.0}
    spans = sum(1 for c in cells if c["r1"] > c["r0"] or c["c1"] > c["c0"])
    return {"rows": max(c["r1"] for c in cells) + 1, "grid_cols": max(c["c1"] for c in cells) + 1, "cells": len(cells),
            "spans": spans, "span_share": round(spans / len(cells), 3)}
