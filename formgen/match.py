"""정답 칸과 만든 칸을 짝짓는다.

1) 거리: 두 상자의 왼쪽·오른쪽·가운데 중 가장 가까운 것끼리 잰다 (값 길이·정렬이 달라도 자리는 같게 보이도록).
2) 정렬: 전체가 조금 밀리거나 늘어난 것(여백·글자 크기 차이)은 짝지은 칸들로 축마다 '늘림 + 밀림'을 맞춘 뒤 다시 잰다.
3) 짝: 비용(거리 + 항목명이 다르면 조금 더)이 가장 작게 1:1 로 (헝가리안). 허용 거리 밖은 짝이 아니다.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from difflib import SequenceMatcher

BIG = 1e6
_NORM = re.compile(r"[\s\W_]+", re.UNICODE)


def norm_label(s: str) -> str:
    return _NORM.sub("", s or "").lower()


def label_sim(a: str, b: str) -> float:
    a, b = norm_label(a), norm_label(b)
    if not a or not b:
        return 0.0
    return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()


def _delta(a, b, lo, hi):
    """한 축에서 가장 가까운 기준점(시작·끝·가운데)의 차이 (부호 있음)."""
    cands = (a[lo] - b[lo], a[hi] - b[hi], (a[lo] + a[hi]) / 2 - (b[lo] + b[hi]) / 2)
    return min(cands, key=abs)


def dist(a, b) -> float:
    return math.hypot(_delta(a, b, 0, 2), _delta(a, b, 1, 3))


def apply(box, tf):
    (ax, bx), (ay, by) = tf
    return [ax * box[0] + bx, ay * box[1] + by, ax * box[2] + bx, ay * box[3] + by]


def hungarian(cost):
    """최소 비용 1:1 짝 (행 수 ≤ 열 수 가 아니어도 됨). [(행, 열)] 을 돌려준다."""
    n, m = len(cost), len(cost[0]) if cost else 0
    if not n or not m:
        return []
    if n > m:
        return [(r, c) for c, r in hungarian([list(col) for col in zip(*cost)])]
    u, v, p, way = [0.0] * (n + 1), [0.0] * (m + 1), [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv, used = [math.inf] * (m + 1), [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], math.inf, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    return [(p[j] - 1, j - 1) for j in range(1, m + 1) if p[j]]


def _fit_axis(src, dst, scale_range=(0.8, 1.25)):
    """dst ≈ a*src + b. 점이 적으면 밀림만 (가운데값)."""
    n = len(src)
    if n == 0:
        return 1.0, 0.0
    shift = sorted(d - s for s, d in zip(src, dst))[n // 2]
    if n < 4 or max(src) - min(src) < 0.1:
        return 1.0, shift
    ms, md = sum(src) / n, sum(dst) / n
    var = sum((s - ms) ** 2 for s in src)
    a = sum((s - ms) * (d - md) for s, d in zip(src, dst)) / var if var else 1.0
    if not scale_range[0] <= a <= scale_range[1]:
        return 1.0, shift
    return a, md - a * ms


def _assign(gt, pred, tf, gate, label_w):
    cost = []
    for g in gt:
        row = []
        for p in pred:
            if g["page"] != p["page"]:
                row.append(BIG)
                continue
            d = dist(g["box"], apply(p["box"], tf))
            row.append(d + label_w * (1 - label_sim(g["label"], p["label"])) if d <= gate else BIG)
        cost.append(row)
    out = []
    for i, j in hungarian(cost):
        if cost[i][j] < BIG:
            out.append((i, j, dist(gt[i]["box"], apply(pred[j]["box"], tf))))
    return out


def match_fields(gt: list[dict], pred: list[dict], tol: float = 0.03, align: bool = True, label_w: float = 0.02, rounds: int = 3):
    """[(정답 번호, 만든 것 번호, 정렬 뒤 거리)] 와 정렬 변환을 돌려준다. tol = 허용 거리 (쪽 너비 = 1)."""
    tf = ((1.0, 0.0), (1.0, 0.0))
    if not gt or not pred:
        return [], tf
    if align:
        gate = 0.15
        for _ in range(rounds):
            pairs = _assign(gt, pred, tf, gate, label_w)
            if len(pairs) < 2:
                break
            pairs.sort(key=lambda t: t[2])
            keep = pairs[:max(2, int(len(pairs) * 0.8))]   # 먼 짝 20% 는 맞추는 데 쓰지 않는다
            new = []
            for lo, hi in ((0, 2), (1, 3)):
                src, dst = [], []
                for i, j, _ in keep:
                    g, p = gt[i]["box"], pred[j]["box"]
                    d = _delta(g, p, lo, hi)   # 기준점 하나를 골라 그 점끼리 맞춘다
                    cands = {g[lo] - p[lo]: (p[lo], g[lo]), g[hi] - p[hi]: (p[hi], g[hi]),
                             (g[lo] + g[hi]) / 2 - (p[lo] + p[hi]) / 2: ((p[lo] + p[hi]) / 2, (g[lo] + g[hi]) / 2)}
                    s, t = cands[d]
                    src.append(s)
                    dst.append(t)
                new.append(_fit_axis(src, dst))
            tf = (new[0], new[1])
            gate = max(tol * 2, 0.05)
    pairs = [t for t in _assign(gt, pred, tf, tol, label_w) if t[2] <= tol]
    return pairs, tf


# ── 인쇄 문구 비교 (html·svg 채점이 함께 쓴다) ──

def _f1(tp, n_pred, n_gt):
    p = tp / n_pred if n_pred else (1.0 if not n_gt else 0.0)
    r = tp / n_gt if n_gt else (1.0 if not n_pred else 0.0)
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def _grams(texts) -> Counter:
    out = Counter()
    for t in texts:
        s = "".join(t.split())
        if len(s) == 1:
            out[s] += 1
        for i in range(len(s) - 1):
            out[s[i:i + 2]] += 1
    return out


def text_score(gt: dict, pred: dict) -> dict:
    """인쇄 문구의 두 글자 묶음(띄어쓰기 무시)이 겹치는 정도. gt·pred 는 {"texts": [글자, …]}."""
    a, b = _grams(gt["texts"]), _grams(pred["texts"])
    p, r, f = _f1(sum((a & b).values()), sum(b.values()), sum(a.values()))
    return {"text_f1": round(f, 4), "text_p": round(p, 4), "text_r": round(r, 4)}
