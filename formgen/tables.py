"""표 구조 채점 (브라우저 없이, html 만으로).

규칙
1) html 의 <table> 을 격자로 편다: rowspan·colspan 을 풀어 칸마다 (시작 행, 끝 행, 시작 열, 끝 열) 을 준다.
   아무 칸도 쓰지 않는 격자선은 없앤다 (같은 모양을 더 촘촘한 격자로 적어도 같은 표로 본다).
2) 칸의 글자 = 인쇄 문구. 값 자리(data-field 가 붙은 요소) 안의 글자는 빼고 '⟨칸⟩' 표시 하나로 바꾼다 (값은 서류마다 다르므로).
3) 이웃 관계: 격자에서 맞닿은 두 칸마다 (왼쪽 글자, 오른쪽 글자, '→') 또는 (위 글자, 아래 글자, '↓') 를 하나씩 만든다.
   합친 칸은 맞닿은 칸 모두와 관계를 갖는다. 그래서 합치기를 틀리면 관계가 달라진다.
4) 표 구조 점수 = 정답과 만든 것의 이웃 관계 묶음(중복 허용)의 F1.
   만든 칸의 글자는 정답 글자와 0.8 이상 비슷하면 같은 글자로 본다 (띄어쓰기·오타 한두 자).
5) 합친 칸 재현율 = 정답의 합친 칸 (글자, 세로 합침 수, 가로 합침 수) 중 만든 것에도 있는 비율.
"""
from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser

from .match import label_sim, norm_label

FIELD = "⟨칸⟩"
SAME = 0.8
VOID = {"br", "hr", "img", "input", "col", "meta", "link", "wbr"}


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.stack = [], []      # stack: 열려 있는 표 [{rows, row, cell}]
        self.field_depth, self.skip = [], 0   # 값 자리 안인가 (안의 글자는 버린다), script·style 안인가

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        if tag == "table":
            self.stack.append({"rows": [], "row": None, "cell": None})
        elif self.stack:
            t = self.stack[-1]
            if tag == "tr":
                t["row"], t["cell"] = [], None
                t["rows"].append(t["row"])
            elif tag in ("td", "th"):
                if t["row"] is None:
                    t["row"] = []
                    t["rows"].append(t["row"])
                t["cell"] = {"text": [], "fields": 0, "rowspan": _int(a.get("rowspan")), "colspan": _int(a.get("colspan")), "th": tag == "th"}
                t["row"].append(t["cell"])
        if "data-field" in a:
            cell = self.stack[-1]["cell"] if self.stack else None
            if cell is not None and not self.field_depth:
                cell["fields"] += 1
                cell["text"].append(FIELD)
            if tag not in VOID:
                self.field_depth.append(tag)
        elif self.field_depth and tag not in VOID:
            self.field_depth.append(tag)

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if self.field_depth and tag == self.field_depth[-1]:
            self.field_depth.pop()
        if not self.stack:
            return
        t = self.stack[-1]
        if tag in ("td", "th"):
            t["cell"] = None
        elif tag == "tr":
            t["row"], t["cell"] = None, None
        elif tag == "table":
            self.tables.append(_grid(self.stack.pop()["rows"]))

    def handle_data(self, data):
        if self.skip or self.field_depth or not self.stack:
            return
        cell = self.stack[-1]["cell"]
        if cell is not None and data.strip():
            cell["text"].append(data.strip())


def _int(v, default=1):
    try:
        return max(1, int(v))
    except (TypeError, ValueError):
        return default


def _grid(rows):
    """[{text, fields, r0, r1, c0, c1}] : rowspan·colspan 을 풀어 자리를 준다."""
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
            cells.append({"text": " ".join(cell["text"]), "fields": cell["fields"], "r0": r, "r1": r + rs - 1, "c0": c, "c1": c + cs - 1})
            c += cs
    return _minimal(cells)


def _minimal(cells):
    """아무 칸도 쓰지 않는 격자선을 없앤다. 같은 모양을 촘촘한 격자(예: 10열에 colspan 4·6)로 적어도 같은 표가 된다."""
    for lo, hi in (("r0", "r1"), ("c0", "c1")):
        cuts = sorted({c[lo] for c in cells} | {c[hi] + 1 for c in cells})
        index = {v: i for i, v in enumerate(cuts)}
        for c in cells:
            c[lo], c[hi] = index[c[lo]], index[c[hi] + 1] - 1
    return cells


def parse_tables(html: str) -> list[list[dict]]:
    p = _Tables()
    p.feed(html)
    p.close()
    return [t for t in p.tables if t]


def _key(text: str) -> str:
    return norm_label(text.replace(FIELD, " 칸표시 ")) if text else ""


def relations(cells: list[dict], canon=None) -> Counter:
    """맞닿은 칸끼리의 관계 묶음."""
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
    """만든 칸의 글자를, 충분히 비슷한 정답 글자로 바꿔 부른다."""
    names = sorted({_key(c["text"]) for c in gt_cells})
    out = []
    for c in pred_cells:
        k = _key(c["text"])
        if k in names or not k:
            out.append(k)
            continue
        best = max(names, key=lambda n: label_sim(n, k), default=None)
        out.append(best if best and label_sim(best, k) >= SAME else k)
    return out


def _f1(tp, n_pred, n_gt):
    p = tp / n_pred if n_pred else (1.0 if not n_gt else 0.0)
    r = tp / n_gt if n_gt else (1.0 if not n_pred else 0.0)
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def table_score(gt_cells: list[dict], pred_cells: list[dict]) -> dict:
    canon = _canon(gt_cells, pred_cells)
    a, b = relations(gt_cells), relations(pred_cells, canon)
    p, r, f = _f1(sum((a & b).values()), sum(b.values()), sum(a.values()))
    span = lambda cells, names: Counter((n, c["r1"] - c["r0"] + 1, c["c1"] - c["c0"] + 1) for c, n in zip(cells, names)
                                        if c["r1"] > c["r0"] or c["c1"] > c["c0"])
    sg, sp = span(gt_cells, [_key(c["text"]) for c in gt_cells]), span(pred_cells, canon)
    n_span = sum(sg.values())
    return {"table_f1": round(f, 4), "table_p": round(p, 4), "table_r": round(r, 4),
            "span_recall": round(sum((sg & sp).values()) / n_span, 4) if n_span else None,
            "cells_gt": len(gt_cells), "cells_pred": len(pred_cells), "spans_gt": n_span, "spans_pred": sum(sp.values()),
            "fields_gt": sum(c["fields"] for c in gt_cells), "fields_pred": sum(c["fields"] for c in pred_cells)}


def shape(cells: list[dict]) -> dict:
    """표의 복잡도: 행·격자 열 수, 칸 수, 합친 칸 수와 비율."""
    if not cells:
        return {"rows": 0, "grid_cols": 0, "cells": 0, "spans": 0, "span_share": 0.0}
    spans = sum(1 for c in cells if c["r1"] > c["r0"] or c["c1"] > c["c0"])
    return {"rows": max(c["r1"] for c in cells) + 1, "grid_cols": max(c["c1"] for c in cells) + 1, "cells": len(cells),
            "spans": spans, "span_share": round(spans / len(cells), 3)}
