"""채점에 쓰는 작은 도구: 1:1 짝짓기(헝가리안), 항목명 비슷함, 인쇄 문구 겹침."""
from __future__ import annotations

import math
import re
from collections import Counter
from difflib import SequenceMatcher

_NORM = re.compile(r"[\s\W_]+", re.UNICODE)


def label_sim(a: str, b: str) -> float:
    """띄어쓰기·기호를 뺀 두 항목명이 비슷한 정도 0~1."""
    a, b = _NORM.sub("", a or "").lower(), _NORM.sub("", b or "").lower()
    if not a or not b:
        return 0.0
    return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()


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


def _grams(texts) -> Counter:
    out = Counter()
    for t in texts:
        s = "".join(t.split())
        if len(s) == 1:
            out[s] += 1
        for i in range(len(s) - 1):
            out[s[i:i + 2]] += 1
    return out


def text_score(gt_texts, pred_texts) -> dict:
    """인쇄 문구의 두 글자 묶음(띄어쓰기 무시)이 겹치는 정도."""
    a, b = _grams(gt_texts), _grams(pred_texts)
    hit, n_pred, n_gt = sum((a & b).values()), sum(b.values()), sum(a.values())
    p = hit / n_pred if n_pred else (1.0 if not n_gt else 0.0)
    r = hit / n_gt if n_gt else (1.0 if not n_pred else 0.0)
    return {"text_f1": round(2 * p * r / (p + r) if p + r else 0.0, 4), "text_p": round(p, 4), "text_r": round(r, 4)}
