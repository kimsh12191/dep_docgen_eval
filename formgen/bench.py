"""벤치마크: golden set 의 이미지마다 모델로 svg 를 만들고 정답과 채점해 난이도별 통과율 표를 낸다.

평가 항목  <items>/<id>/{image.png, ref.svg, meta.json}      meta.json 의 "tier" = 하 · 중 · 상
결과       <out>/run.json        실행 설정
           <out>/results.jsonl   항목·반복마다 한 줄 (있는 줄은 다시 돌리지 않는다 → 끊겨도 같은 --out 으로 이어서)
           <out>/report.md       난이도별 표
           <out>/items/<id>/r<번호>/   out.svg · raw.txt · make.json

통과 기준(PASS_RULE)은 사람 판정으로 맞추기 전의 **임시값**이다. results.jsonl 에는 점수만 남기므로
기준을 고친 뒤 `python -m formgen report <out>` 을 돌리면 모델을 다시 부르지 않고 표가 바뀐다.
같은 이미지를 여러 번 돌린 것은 이미지 여러 장이 아니다. 이미지 통과 = 그 이미지의 시도 중 절반을 넘게 통과.

실행      python -m formgen bench --items bench/golden_v1 --endpoint http://host:8000/v1 --model NAME --out runs/NAME --repeat 3
모델 비교  python -m formgen compare runs/A runs/B …
길 검사    --mock ref (정답을 그대로 답으로) · --mock nofields (값 자리를 지운 답) · --mock empty
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics as st
import time
from collections import Counter
from pathlib import Path

from . import make as M, svg

TIERS = ("하", "중", "상")
PASS_RULE = {"field_recall": 0.8, "text_f1": 0.8}          # 유효 ∧ 아래 점수가 모두 이 값 이상 (임시)
FAIL_NAME = {"field_recall": "low_fields", "text_f1": "low_text"}
SCORES = ("field_recall", "field_precision", "label_acc", "type_acc", "iou_mean", "text_f1")
FIELD_RECT = re.compile(r"<rect\b[^>]*\bdata-field=[^>]*/>")


def failure(row: dict) -> str:
    """실패 유형 하나 (통과면 'ok'). 위에서부터 먼저 걸리는 것."""
    if row.get("error"):
        return "request_error"
    if row.get("truncated"):
        return "truncated"
    if not row.get("valid"):
        return "invalid:" + ",".join(row.get("issues") or [])
    for key, least in PASS_RULE.items():
        if row.get(key) is None or row[key] < least:
            return FAIL_NAME[key]
    return "ok"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """비율 k/n 의 95% 구간. 이미지가 적으면 넓게 나온다 — 그만큼 모른다는 뜻이다."""
    p, d = k / n, 1 + z * z / n
    mid, half = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, mid - half), min(1.0, mid + half)


def summarize(rows: list[dict]) -> dict:
    """{"하": 집계, "중": …, "상": …, "전체": …}. 줄이 없는 난이도는 None."""
    def block(rs):
        if not rs:
            return None
        mean = lambda k: (lambda xs: round(st.fmean(xs), 3) if xs else None)([r[k] for r in rs if r.get(k) is not None])
        by_image = {}
        for r in rs:
            by_image.setdefault(r["id"], []).append(failure(r) == "ok")
        return {"images": len(by_image), "attempts": len(rs),
                "image_pass": sum(sum(v) * 2 > len(v) for v in by_image.values()),
                "attempt_pass": sum(sum(v) for v in by_image.values()),
                "unstable": sum(0 < sum(v) < len(v) for v in by_image.values()),
                **{k: mean(k) for k in SCORES}, "failures": dict(Counter(failure(r) for r in rs)),
                "seconds": mean("seconds"), "completion_tokens": mean("completion_tokens")}
    return {**{t: block([r for r in rows if r.get("tier") == t]) for t in TIERS}, "전체": block(rows)}


def report(run: dict, summary: dict) -> str:
    fmt = lambda v: "-" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))
    lines = [f"# {run['model']} · {run['items_name']}", "",
             "통과(임시 기준) = 유효 ∧ " + " ∧ ".join(f"{k} ≥ {v}" for k, v in PASS_RULE.items())
             + f" · 프롬프트 {run['prompt']} · 채점 {run['scorer']} · 출력 한도 {run['max_tokens']} · 반복 {run['repeat']}", "",
             "| 난이도 | 이미지 통과 | 95% 구간 | 시도 통과 | 반복마다 갈림 | 값 자리 재현 | 값 자리 정밀 | 항목명 | 종류 | 겹침 | 문구 | 평균 초 | 평균 출력 토큰 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, b in summary.items():
        if b:
            lo, hi = wilson(b["image_pass"], b["images"])
            lines.append(f"| {name} | {b['image_pass']}/{b['images']} | {lo:.0%}~{hi:.0%} | {b['attempt_pass']}/{b['attempts']} | {b['unstable']} | "
                         + " | ".join(fmt(b[k]) for k in SCORES) + f" | {fmt(b['seconds'])} | {fmt(b['completion_tokens'])} |")
    lines += ["", "실패 유형: " + " / ".join(f"{name} " + ", ".join(f"{k} {v}" for k, v in sorted(b["failures"].items(), key=lambda t: -t[1]))
                                         for name, b in summary.items() if b and name != "전체")]
    return "\n".join(lines) + "\n"


def mock_answer(kind: str, ref: str) -> str:
    return {"ref": ref, "nofields": FIELD_RECT.sub("", ref), "empty": ""}[kind]


def load(out) -> tuple[dict, list[dict]]:
    """결과 폴더 → (실행 설정, 줄 목록)."""
    out = Path(out)
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    rows = [json.loads(x) for x in (out / "results.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    return run, [r for r in rows if r["repeat"] < run["repeat"]]


def rereport(out) -> str:
    """모델을 다시 부르지 않고 표를 다시 만든다 (통과 기준을 바꿨을 때)."""
    run, rows = load(out)
    text = report(run, summarize(rows))
    (Path(out) / "report.md").write_text(text, encoding="utf-8")
    return text


def compare(outs: list) -> str:
    """여러 모델의 결과 폴더 → 모델 × 난이도 표. 칸 = 이미지 통과 수/이미지 수 (값 자리 재현 평균)."""
    lines = ["| 모델 | " + " | ".join(TIERS) + " | 전체 | 유효하지 않거나 잘린 시도 | 평균 출력 토큰 |", "|---|---|---|---|---|---|---|"]
    for out in outs:
        run, rows = load(out)
        s = summarize(rows)
        cell = lambda b: "-" if not b else f"{b['image_pass']}/{b['images']} ({b['field_recall'] if b['field_recall'] is not None else 0:.2f})"
        broken = sum(v for k, v in s["전체"]["failures"].items() if k not in ("ok", "low_fields", "low_text"))
        lines.append(f"| {run['model']} | " + " | ".join(cell(s[t]) for t in TIERS) + f" | {cell(s['전체'])} | {broken}/{s['전체']['attempts']} | {s['전체']['completion_tokens'] or '-'} |")
    return "\n".join(lines) + "\n\n칸 = 통과한 이미지 수/이미지 수 (값 자리 재현 평균). 통과 기준은 임시값이다: 유효 ∧ " \
        + " ∧ ".join(f"{k} ≥ {v}" for k, v in PASS_RULE.items()) + "\n"


def run(a) -> dict:
    items_dir, out = Path(a.items), Path(a.out)
    read = lambda p: p.read_text(encoding="utf-8-sig")
    ids = sorted(p.name for p in items_dir.iterdir() if (p / "ref.svg").is_file() and (p / "image.png").is_file())
    if not ids:
        raise SystemExit(f"평가 항목이 없습니다 (image.png + ref.svg 가 있는 폴더): {items_dir}")
    tiers = {i: json.loads(read(items_dir / i / "meta.json")).get("tier") if (items_dir / i / "meta.json").is_file() else None for i in ids}
    cfg = {"model": a.model or f"mock:{a.mock}", "endpoint": a.endpoint, "items_name": items_dir.name, "n_items": len(ids),
           "prompt": M.PROMPT_VERSION, "scorer": svg.SCORER, "max_tokens": a.max_tokens, "repeat": a.repeat}
    out.mkdir(parents=True, exist_ok=True)
    if (out / "run.json").is_file():
        old = json.loads(read(out / "run.json"))
        changed = [k for k in ("model", "items_name", "prompt", "scorer", "max_tokens") if old.get(k) != cfg[k]]
        if changed:
            raise SystemExit(f"{out} 에 다른 설정으로 돌린 결과가 있습니다 ({', '.join(changed)}). 새 --out 폴더를 쓰세요.")
    (out / "run.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    done = {(r["id"], r["repeat"]) for r in load(out)[1]} if (out / "results.jsonl").is_file() else set()
    with (out / "results.jsonl").open("a", encoding="utf-8") as fh:
        for n, i in enumerate(ids):
            ref = read(items_dir / i / "ref.svg")
            for rep in range(a.repeat):
                if (i, rep) in done:
                    continue
                d = out / "items" / i / f"r{rep}"
                log = M.make(items_dir / i / "image.png", d, a.endpoint, a.model, a.max_tokens, a.api_key,
                             mock=mock_answer(a.mock, ref) if a.mock else None)
                s = svg.score(ref, read(d / "out.svg"))
                row = {"id": i, "repeat": rep, "tier": tiers[i], **{k: v for k, v in s.items() if k != "scorer"},
                       "valid": log["valid"], "truncated": log["truncated"], "error": log.get("error"), "seconds": log.get("seconds"),
                       "completion_tokens": (log.get("usage") or {}).get("completion_tokens"), "svg_bytes": log["svg_bytes"]}
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                print(f"[{n + 1}/{len(ids)}] {i} r{rep} {row['tier']} {failure(row)} 값자리={row['field_recall']} 문구={row['text_f1']} {row['seconds']}s", flush=True)
    return {"run": cfg, "report": rereport(out)}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m formgen bench", description="모델 하나의 svg 서식 생성 수준을 난이도별로 잰다")
    ap.add_argument("--items", default="bench/golden_v1", help="평가 항목 폴더")
    ap.add_argument("--out", required=True, help="결과 폴더 (모델마다 하나)")
    ap.add_argument("--endpoint", default="", help="OpenAI 호환 주소, /v1 까지")
    ap.add_argument("--model", default="")
    ap.add_argument("--max-tokens", type=int, default=32000)
    ap.add_argument("--repeat", type=int, default=1, help="항목마다 돌리는 횟수")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--mock", default=None, choices=["ref", "nofields", "empty"], help="모델 없이 길 검사")
    a = ap.parse_args(argv)
    if not a.mock and not (a.endpoint and a.model):
        ap.error("--endpoint 와 --model 이 필요합니다 (또는 --mock)")
    print("\n" + run(a)["report"])


if __name__ == "__main__":
    main()
