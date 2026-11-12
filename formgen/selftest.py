"""채점기 자체 검증 (가설 H1: 채점기가 맞다). 모델 없이 돌린다.

정답을 아는 입력을 넣어 점수가 기대대로 나오는지 본다.
  T1 같은 것        정답 = 만든 것                         → 1.0
  T2 다시 그리기    같은 서식을 다른 seed 로 (값·글꼴·여백이 바뀜)  → 1.0 에 가까워야 (채점기의 잡음 바닥)
  T3 칸 절반        칸을 하나 걸러 지움                     → 재현율 ≈ 0.5, 정밀도 1.0
  T4 빈 것          칸·글자 없음                           → 0
  T5 다른 서식      다른 서식을 만든 것으로 넣음             → 0 에 가까워야 (변별력)
  T6 밀림·흔들림    전체를 밀기 / 칸마다 조금·많이 흔들기      → 밀림·작은 흔들림은 유지, 큰 흔들림은 하락
  T7 갈래 바꿈      체크 칸을 값 칸으로                     → 체크 칸 비율만큼 하락
  T8 초안 폴더      초안 폴더(template.html.j2 + form.json) 를 그려 채점하는 길이 도는가
허용 거리(tol)는 T2 는 높고 T5 는 낮은 값으로 고른다.
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import statistics as st
import time
from pathlib import Path

from .bridge import Renderer
from .score import TOL, field_score, score
from .sheet import first_page, from_label

TOLS = (0.01, 0.02, 0.03, 0.05, 0.08)


def _shift(sheet, dx, dy):
    s = copy.deepcopy(sheet)
    for f in s["fields"]:
        b = f["box"]
        f["box"] = [b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy]
    return s


def _jitter(sheet, sigma, rng):
    s = copy.deepcopy(sheet)
    for f in s["fields"]:
        dx, dy = rng.gauss(0, sigma), rng.gauss(0, sigma)
        b = f["box"]
        f["box"] = [b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy]
    return s


def _stats(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    xs = sorted(xs)
    return {"n": len(xs), "mean": round(st.fmean(xs), 4), "median": round(xs[len(xs) // 2], 4), "min": round(xs[0], 4),
            "p10": round(xs[int(0.1 * (len(xs) - 1))], 4), "max": round(xs[-1], 4)}


def run(ids: list[str], out: Path, seeds=(1, 2, 3, 4, 5, 6), example: Path | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(0)
    rows, skipped = [], []
    t0 = time.time()
    with Renderer(out / "cache") as R:
        base = {}
        for doc_id in ids:
            try:
                label = R.form(doc_id, 0)
            except Exception as e:
                skipped.append((doc_id, f"render: {type(e).__name__}"))
                continue
            if len(label["images"]) != 1:
                skipped.append((doc_id, f"{len(label['images'])}쪽"))
                continue
            sheet = first_page(from_label(label))
            if not sheet["fields"]:
                skipped.append((doc_id, "칸 없음"))
                continue
            base[doc_id] = (sheet, (label.get("template_variant") or {}).get("id"))
        order = list(base)
        for n, doc_id in enumerate(order):
            gt, variant = base[doc_id]
            rec = {"id": doc_id, "fields": len(gt["fields"]), "texts": len(gt["texts"]),
                   "checks": sum(f["kind"] == "check" for f in gt["fields"])}
            s = score(gt, gt)
            rec["t1"] = [s["field_f1"], s["text_f1"]]
            half = copy.deepcopy(gt)
            half["fields"] = half["fields"][::2]
            s = field_score(gt, half)
            rec["t3"] = {"p": s["field_p"], "r": s["field_r"], "expect_r": round(len(half["fields"]) / len(gt["fields"]), 4)}
            empty = dict(gt, fields=[], texts=[])
            s = score(gt, empty)
            rec["t4"] = [s["field_f1"], s["text_f1"]]
            s = field_score(gt, _shift(gt, 0.03, 0.02))
            rec["t6_shift"] = {"f1": s["field_f1"], "pos_err": s["pos_err"], "no_align": field_score(gt, _shift(gt, 0.03, 0.02), align=False)["field_f1"]}
            rec["t6_small"] = field_score(gt, _jitter(gt, 0.004, rng))["field_f1"]
            rec["t6_large"] = field_score(gt, _jitter(gt, 0.06, rng))["field_f1"]
            swapped = copy.deepcopy(gt)
            for f in swapped["fields"]:
                if f["kind"] == "check":
                    f["kind"], f["type"] = "value", "text"
            rec["t7"] = {"f1": field_score(gt, swapped)["field_f1"], "expect": round(1 - rec["checks"] / len(gt["fields"]), 4)}
            # T2 다시 그리기: 같은 레이아웃 변형, 한 쪽인 seed 만
            rec["t2"] = {str(t): [] for t in TOLS}
            rec["t2_text"], rec["t2_label"], rec["t2_type"], rec["t2_pos"] = [], [], [], []
            for seed in seeds:
                try:
                    lab = R.form(doc_id, seed)
                except Exception:
                    continue
                if len(lab["images"]) != 1 or (lab.get("template_variant") or {}).get("id") != variant:
                    continue
                other = first_page(from_label(lab))
                for t in TOLS:
                    rec["t2"][str(t)].append(field_score(gt, other, tol=t)["field_f1"])
                full = score(gt, other)
                rec["t2_text"].append(full["text_f1"])
                rec["t2_label"].append(full["label_acc"])
                rec["t2_type"].append(full["type_acc"])
                rec["t2_pos"].append(full["pos_err"])
            # T5 다른 서식 (목록의 다음 서식)
            wrong = base[order[(n + 1) % len(order)]][0]
            rec["t5"] = {str(t): field_score(gt, wrong, tol=t)["field_f1"] for t in TOLS}
            rec["t5_text"] = score(gt, wrong)["text_f1"]
            rows.append(rec)
            print(f"[{n + 1}/{len(order)}] {doc_id} reseed@{TOL}={_stats(rec['t2'][str(TOL)]) and _stats(rec['t2'][str(TOL)])['mean']} wrong@{TOL}={rec['t5'][str(TOL)]}", flush=True)
        t8 = None
        if example and example.is_dir():
            try:
                a = first_page(from_label(R.draft(example, 0)))
                b = first_page(from_label(R.draft(example, 1)))
                s = score(a, b)
                t8 = {"valid": s["valid"], "invalid_why": s["invalid_why"], "field_f1": s["field_f1"], "text_f1": s["text_f1"],
                      "fields": len(a["fields"]), "rows": a["rows"]}
            except Exception as e:
                t8 = {"error": f"{type(e).__name__}: {e}"[:300]}
    flat = lambda key: [x for r in rows for x in r[key]]
    summary = {
        "forms": len(rows), "skipped": skipped, "seconds": round(time.time() - t0),
        "T1_identity_all_1": all(r["t1"] == [1.0, 1.0] for r in rows),
        "T3_half": {"precision": _stats([r["t3"]["p"] for r in rows]), "recall_minus_expect": _stats([round(r["t3"]["r"] - r["t3"]["expect_r"], 4) for r in rows])},
        "T4_empty_all_0": all(r["t4"] == [0.0, 0.0] for r in rows),
        "T6_shift_f1": _stats([r["t6_shift"]["f1"] for r in rows]), "T6_shift_f1_without_align": _stats([r["t6_shift"]["no_align"] for r in rows]),
        "T6_small_jitter_f1": _stats([r["t6_small"] for r in rows]), "T6_large_jitter_f1": _stats([r["t6_large"] for r in rows]),
        "T7_kind_swap_f1_minus_expect": _stats([round(r["t7"]["f1"] - r["t7"]["expect"], 4) for r in rows]),
        "T2_reseed_field_f1": {str(t): _stats([x for r in rows for x in r["t2"][str(t)]]) for t in TOLS},
        "T5_wrong_field_f1": {str(t): _stats([r["t5"][str(t)] for r in rows]) for t in TOLS},
        "T2_reseed_text_f1": _stats(flat("t2_text")), "T5_wrong_text_f1": _stats([r["t5_text"] for r in rows]),
        "T2_reseed_label_acc": _stats(flat("t2_label")), "T2_reseed_type_acc": _stats(flat("t2_type")), "T2_reseed_pos_err": _stats(flat("t2_pos")),
        "T8_draft_folder": t8,
    }
    (out / "selftest.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(prog="formgen selftest", description="채점기 자체 검증 (모델 없이)")
    ap.add_argument("--pool", required=True, help="서식 ID 목록 JSON (문자열 목록, 또는 [{id: …}] )")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--example", default=str(Path(__file__).resolve().parents[1] / "examples" / "spec_example"))
    a = ap.parse_args(argv)
    ids = [x["id"] if isinstance(x, dict) else x for x in json.loads(Path(a.pool).read_text(encoding="utf-8"))]
    if a.limit:
        ids = ids[:a.limit]
    summary = run(ids, Path(a.out), example=Path(a.example))
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
