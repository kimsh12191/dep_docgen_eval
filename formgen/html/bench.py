"""벤치마크 실행: 평가 항목마다 이미지 → (make) → html → 정답 html 과 채점 → 난이도별 통과율.

평가 항목 폴더  <items>/<id>/{image.png, ref.html, meta.json}
결과 폴더       <out>/run.json            실행 설정·버전
                <out>/results.jsonl       항목·반복마다 한 줄 (이미 있는 줄은 다시 돌리지 않는다)
                <out>/summary.json        난이도별 통과율·평균 점수·실패 유형·시간·토큰
                <out>/report.md           사람이 읽는 표
                <out>/items/<id>/r<번호>/  out.html · raw_*.txt · make.json

실행: python -m formgen html bench --items bench/roundtrip_v0 --endpoint http://host:8000/v1 --model NAME --out runs/NAME
길 검사 (모델 없이): --mock ref (정답을 그대로 답으로) · --mock nospan (합치기를 지운 답) · --mock empty
"""
from __future__ import annotations

import argparse
import json
import re
import statistics as st
import time
from collections import Counter
from pathlib import Path

from . import difficulty, htmldoc, make as M
from .score import PASS, VERSION as SCORE_VERSION, passed, score_docs

SCORES = ("field_f1", "field_f1_strict", "table_f1", "span_recall", "text_f1")
TIERS = ("하", "중", "상")


def failure(row: dict) -> str:
    """실패 유형 하나 (통과면 'ok'). 위에서부터 먼저 걸리는 것."""
    if row.get("error"):
        return "request_error"
    if row.get("truncated"):
        return "truncated"
    if not row.get("valid"):
        return "invalid:" + ",".join(row.get("invalid_why") or [])
    for key, name in (("field_f1", "fields"), ("span_recall", "merged_cells"), ("table_f1", "table"), ("text_f1", "text")):
        if row.get(key) is not None and row[key] < PASS[key]:
            return "low_" + name
    return "ok"


def mock_answer(kind: str, ref: str) -> str:
    if kind == "ref":
        return ref
    if kind == "nospan":
        return re.sub(r'\s(?:rowspan|colspan)="\d+"', "", ref)
    if kind == "empty":
        return ""
    raise SystemExit(f"모르는 --mock: {kind}")


def summarize(rows: list[dict]) -> dict:
    def block(rs):
        if not rs:
            return None
        mean = lambda k: (lambda xs: round(st.fmean(xs), 4) if xs else None)([r[k] for r in rs if r.get(k) is not None])
        return {"n": len(rs), "pass_rate": round(sum(r["pass"] for r in rs) / len(rs), 4), "valid_rate": round(sum(bool(r["valid"]) for r in rs) / len(rs), 4),
                **{k: mean(k) for k in SCORES}, "failures": dict(Counter(r["failure"] for r in rs)),
                "seconds_mean": mean("seconds"), "completion_tokens_mean": mean("completion_tokens")}
    return {"all": block(rows), "by_tier": {t: block([r for r in rows if r["tier"] == t]) for t in TIERS}}


def report(run: dict, summary: dict) -> str:
    lines = [f"# {run['model']} · {run['protocol']} · {run['items_name']}", "",
             f"채점 {run['score_version']} · 프롬프트 {run['prompt']} · 난이도 {run['difficulty_rule']} · 반복 {run['repeat']} · {run['finished']}", "",
             "통과 기준(임시): 유효 ∧ " + " ∧ ".join(f"{k} ≥ {v}" for k, v in PASS.items()) + " (해당 없는 점수는 빼고)", "",
             "| 난이도 | 항목 | 통과율 | 유효 | 값 자리 | 값 자리(엄격) | 표 | 합친 칸 | 문구 | 평균 초 | 평균 출력 토큰 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    fmt = lambda v: "-" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))
    for name, b in [(t, summary["by_tier"][t]) for t in TIERS] + [("전체", summary["all"])]:
        if b:
            lines.append(f"| {name} | {b['n']} | {b['pass_rate']:.0%} | {b['valid_rate']:.0%} | " + " | ".join(fmt(b[k]) for k in SCORES)
                         + f" | {fmt(b['seconds_mean'])} | {fmt(b['completion_tokens_mean'])} |")
    lines += ["", "실패 유형: " + ", ".join(f"{k} {v}" for k, v in sorted((summary["all"] or {}).get("failures", {}).items(), key=lambda t: -t[1]))]
    return "\n".join(lines) + "\n"


def run(a) -> dict:
    items_dir, out = Path(a.items), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ids = sorted(p.name for p in items_dir.iterdir() if (p / "ref.html").is_file() and (p / "image.png").is_file())
    metas = {i: json.loads((items_dir / i / "meta.json").read_text(encoding="utf-8")) if (items_dir / i / "meta.json").is_file() else {} for i in ids}
    if a.tiers:
        ids = [i for i in ids if metas[i].get("tier") in a.tiers]
    if a.limit:
        ids = ids[:a.limit]
    candidates = [i for i in ids if metas[i].get("gold_approved") is False]
    if candidates and not getattr(a, "allow_candidates", False):
        raise SystemExit("Unreviewed gold candidates: use --allow-candidates only for development diagnostics: " + ", ".join(candidates))
    cfg = {"model": a.model or f"mock:{a.mock}", "endpoint": a.endpoint, "protocol": a.protocol, "rounds": a.rounds, "max_tokens": a.max_tokens,
           "repeat": a.repeat, "items": str(items_dir), "items_name": items_dir.name, "n_items": len(ids), "prompt": M.PROMPT_VERSION,
           "score_version": SCORE_VERSION, "difficulty_rule": difficulty.VERSION, "pass_rule": PASS, "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    res_path = out / "results.jsonl"
    rows = [json.loads(x) for x in res_path.read_text(encoding="utf-8").splitlines() if x.strip()] if res_path.is_file() else []
    done = {(r["id"], r["repeat"]) for r in rows}
    with res_path.open("a", encoding="utf-8") as fh:
        for n, i in enumerate(ids):
            ref = (items_dir / i / "ref.html").read_text(encoding="utf-8")
            gt = htmldoc.parse(ref)
            for rep in range(a.repeat):
                if (i, rep) in done:
                    continue
                d = out / "items" / i / f"r{rep}"
                log = M.make(items_dir / i / "image.png", d, a.endpoint, a.model, a.protocol, a.rounds, a.max_tokens,
                             api_key=a.api_key, mock=mock_answer(a.mock, ref) if a.mock else None)
                s = score_docs(gt, htmldoc.parse((d / "out.html").read_text(encoding="utf-8")))
                s.update(valid=log["valid"], invalid_why=log["invalid_why"])   # 잘림 등 원문에서 본 것까지
                row = {"id": i, "repeat": rep, "tier": metas[i].get("tier") or difficulty.of_html(ref)["tier"],
                       **{k: s.get(k) for k in ("valid", "invalid_why", "bad_fields", *SCORES, "label_acc", "place_acc", "type_acc", "option_acc",
                                                "fields_gt", "fields_pred", "matched", "tables_gt", "tables_pred", "spans_gt", "spans_pred")},
                       **{k: log.get(k) for k in ("error", "truncated", "seconds", "prompt_tokens", "completion_tokens", "rounds_used", "html_bytes")}}
                row["pass"] = bool(passed(s)) and not row["error"]
                row["failure"] = failure(row) if not row["pass"] else "ok"
                rows.append(row)
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                print(f"[{n + 1}/{len(ids)}] {i} r{rep} {row['tier']} {'통과' if row['pass'] else row['failure']} "
                      f"값자리={row['field_f1']} 표={row['table_f1']} 합친칸={row['span_recall']} 문구={row['text_f1']} {row['seconds']}s", flush=True)
    keep = set(ids)
    rows = [r for r in rows if r["id"] in keep and r["repeat"] < a.repeat]
    summary = summarize(rows)
    cfg["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    (out / "run.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "report.md").write_text(report(cfg, summary), encoding="utf-8")
    return {"run": cfg, "summary": summary}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m formgen html bench", description="모델 하나의 서식 생성 수준을 난이도별로 잰다")
    ap.add_argument("--items", default="bench/roundtrip_v0")
    ap.add_argument("--out", required=True)
    ap.add_argument("--endpoint", default="", help="OpenAI 호환 주소, /v1 까지")
    ap.add_argument("--model", default="")
    ap.add_argument("--protocol", default="P1", choices=["P1", "P2"])
    ap.add_argument("--rounds", type=int, default=2, help="P2 에서 고쳐 쓰기 횟수")
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--tiers", nargs="*", default=None, help="이 난이도만 (하 중 상)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--allow-candidates", action="store_true", help="Allow unreviewed official pilot items; results are not validated gold scores")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--mock", default=None, choices=["ref", "nospan", "empty"], help="모델 없이 길 검사")
    a = ap.parse_args(argv)
    if not a.mock and not (a.endpoint and a.model):
        ap.error("--endpoint 와 --model 이 필요합니다 (또는 --mock)")
    res = run(a)
    print()
    print((Path(a.out) / "report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
