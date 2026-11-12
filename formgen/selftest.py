"""채점기 자체 검증 (가설 H1: 채점기가 맞다). 모델도 브라우저도 없이 돌린다.

평가 항목의 정답 html 을 일부러 망가뜨려 넣고, 점수가 기대대로 나오는지 본다.
  T1 그대로               → 모든 점수 1.0
  T2 값을 채움            값 자리 안에 값 글자를 넣음           → 그대로 1.0 (값은 채점하지 않는다)
  T3 값 자리 절반         표시를 하나 걸러 지움                 → 값 자리 재현율 ≈ 0.5, 정밀도 1.0
  T4 빈 문서              → 유효하지 않음, 0
  T5 다른 서식            다른 항목의 정답을 넣음               → 0 에 가까워야 (변별력)
  T6 글자 오타            인쇄 글자 50자에 1자꼴로 바꿈          → 조금만 하락
  T7 갈래 바꿈            체크 칸을 값 칸으로                   → 체크 칸 비율만큼 하락
  T8 합치기 버림          rowspan·colspan 을 모두 지움          → 합친 칸 재현율 0, 표 점수 하락 (합친 칸이 있는 항목만)
  T9 표시 없음            data-field 를 모두 지움               → 유효하지 않음 (no_fields)
  T10 잘린 출력           뒤 40% 를 자름                        → 점수 하락 (닫히지 않은 표면 유효하지 않음)

실행: python -m formgen selftest --items bench/roundtrip_v0 --out results/selftest_html
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics as st
from pathlib import Path

from . import htmldoc
from .score import score_docs

MARK = re.compile(r'(<span\b[^>]*\bdata-field="[^"]*"[^>]*>)(</span>)')
ATTR_FIELD = re.compile(r'\sdata-field="[^"]*"')
SPAN_ATTR = re.compile(r'\s(?:rowspan|colspan)="\d+"')
TEXT_NODE = re.compile(r">([^<>]+)<")
KEYS = ("field_f1", "field_f1_strict", "table_f1", "span_recall", "text_f1")


def fill_values(html):
    return MARK.sub(lambda m: m.group(1) + "홍길동 1,234,000" + m.group(2), html)


def drop_half(html):
    n = [0]

    def rep(m):
        n[0] += 1
        return ATTR_FIELD.sub("", m.group(0), count=1) if n[0] % 2 == 0 else m.group(0)
    return re.sub(r'<span\b[^>]*\bdata-field="[^"]*"[^>]*>', rep, html)


def typos(html, rng, rate=0.02):
    head, body = html[:html.find("<body")], html[html.find("<body"):]

    def rep(m):
        s = list(m.group(1))
        for i, ch in enumerate(s):
            if not ch.isspace() and rng.random() < rate:
                s[i] = "가"
        return ">" + "".join(s) + "<"
    return head + TEXT_NODE.sub(rep, body)


def _stats(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return {"n": len(xs), "mean": round(st.fmean(xs), 4), "median": xs[len(xs) // 2], "min": xs[0], "max": xs[-1]}


def run(items_dir: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(0)
    ids = sorted(p.name for p in items_dir.iterdir() if (p / "ref.html").is_file())
    refs = {i: (items_dir / i / "ref.html").read_text(encoding="utf-8") for i in ids}
    docs = {i: htmldoc.parse(h) for i, h in refs.items()}
    pick = lambda s: {k: s.get(k) for k in KEYS} | {"valid": s["valid"], "why": s["invalid_why"]}
    rows = []
    for n, i in enumerate(ids):
        ref, gt = refs[i], docs[i]
        sc = lambda html: score_docs(gt, htmldoc.parse(html))
        nf, nchk = len(gt["fields"]), sum(f["kind"] == "check" for f in gt["fields"])
        half_html = drop_half(ref)
        half = sc(half_html)
        swap = sc(ref.replace('data-type="checkbox"', 'data-type="text"'))
        rec = {"id": i, "fields": nf, "checks": nchk, "spans": sum(1 for t in gt["tables"] for c in t if c["r1"] > c["r0"] or c["c1"] > c["c0"]),
               "t1": pick(sc(ref)), "t2": pick(sc(fill_values(ref))),
               "t3": {"p": half["field_p"], "r": half["field_r"], "expect_r": round(len(htmldoc.parse(half_html)["fields"]) / nf, 4)},
               "t4": pick(sc("")), "t5": pick(score_docs(gt, docs[ids[(n + 1) % len(ids)]])),
               "t6": pick(sc(typos(ref, rng))),
               "t7": {"f1": swap["field_f1"], "expect": round(1 - nchk / nf, 4)},
               "t8": pick(sc(SPAN_ATTR.sub("", ref))), "t9": pick(sc(ATTR_FIELD.sub("", ref))),
               "t10": pick(sc(ref[:int(len(ref) * 0.6)]))}
        rows.append(rec)
    col = lambda t, k: [r[t][k] for r in rows]
    all1 = lambda t: all(all(r[t][k] in (1.0, None) for k in KEYS) and r[t]["valid"] for r in rows)
    spans = [r for r in rows if r["spans"]]
    summary = {
        "items": len(rows),
        "T1_same_all_1": all1("t1"), "T2_values_filled_all_1": all1("t2"),
        "T3_half": {"precision": _stats(col("t3", "p")), "recall_minus_expect": _stats([round(r["t3"]["r"] - r["t3"]["expect_r"], 4) for r in rows])},
        "T4_empty_all_invalid": all(not r["t4"]["valid"] and not r["t4"]["field_f1"] for r in rows),
        "T5_wrong": {k: _stats(col("t5", k)) for k in KEYS},
        "T6_typos": {k: _stats(col("t6", k)) for k in KEYS},
        "T7_kind_swap_f1_minus_expect": _stats([round(r["t7"]["f1"] - r["t7"]["expect"], 4) for r in rows]),
        "T8_no_spans (합친 칸이 있는 항목)": {"n": len(spans), **{k: _stats([r["t8"][k] for r in spans]) for k in ("span_recall", "table_f1", "field_f1", "field_f1_strict")}},
        "T9_no_markers_all_invalid": all(not r["t9"]["valid"] and "no_fields" in r["t9"]["why"] for r in rows),
        "T10_truncated": {"invalid_share": round(sum(not r["t10"]["valid"] for r in rows) / len(rows), 3), **{k: _stats(col("t10", k)) for k in ("field_f1", "text_f1")}},
    }
    (out / "selftest.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(prog="formgen selftest", description="채점기 자체 검증 (모델·브라우저 없이)")
    ap.add_argument("--items", default="bench/roundtrip_v0")
    ap.add_argument("--out", default="results/selftest_html")
    a = ap.parse_args(argv)
    print(json.dumps(run(Path(a.items), Path(a.out)), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
