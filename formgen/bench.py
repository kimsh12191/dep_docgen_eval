"""벤치마크: 평가 항목마다 이미지 → (make) → svg → 정답 svg 와 채점 → 난이도별 통과율 표.

평가 항목 폴더  <items>/<id>/{image.png, ref.svg, meta.json}     meta.json 의 "tier" = 하 · 중 · 상
결과 폴더       <out>/run.json         실행 설정·버전
                <out>/results.jsonl    항목·반복마다 한 줄 (이미 있는 줄은 다시 돌리지 않는다 → 끊겨도 이어서)
                <out>/summary.json     난이도별 집계
                <out>/report.md        사람이 읽는 표
                <out>/items/<id>/r<번호>/   out.svg · raw.txt · make.json

통과 기준은 **임시**다 (PASS_RULE). results.jsonl 에는 점수만 남기고 통과 여부는 집계할 때 계산하므로,
기준을 바꾸면 모델을 다시 부르지 않고 `python -m formgen report <out>` 으로 표만 다시 만든다.
  text_r(재현율)을 쓰는 까닭: 지금 정답 후보의 일부 글자가 글자 모양(path)으로만 남아 있어, 모델이 그 글자를
  옳게 적으면 text_f1 의 정밀도가 깎인다. 정답의 글자를 다 채운 뒤에는 text_f1 로 바꾼다.

같은 이미지를 여러 번 돌린 것은 서로 독립된 이미지가 아니다. 그래서 '시도' 기준과 '이미지' 기준을 따로 적는다.
  이미지 통과 = 그 이미지의 시도 중 절반을 넘게 통과.

실행: python -m formgen bench --items bench/official_pilot_v1 --endpoint http://host:8000/v1 --model NAME --out runs/NAME --allow-candidates
길 검사 (모델 없이): --mock ref (정답을 그대로 답으로) · --mock nofields (값 자리 표시를 지운 답) · --mock empty
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
SCORES = ("typed_field_f1", "located_field_f1", "field_iou_mean", "text_f1", "text_r")
PASS_RULE = {"version": "pass-provisional-0", "typed_field_f1": 0.8, "located_field_f1": 0.8, "text_r": 0.8}
FAIL_NAME = {"typed_field_f1": "low_fields", "located_field_f1": "low_position", "text_r": "low_text", "text_f1": "low_text"}
FIELD_RECT = re.compile(r"<rect\b[^>]*\bdata-field=[^>]*/>")


def failure(row: dict, rule: dict = PASS_RULE) -> str:
    """실패 유형 하나 (통과면 'ok'). 위에서부터 먼저 걸리는 것."""
    if row.get("error"):
        return "request_error"
    if row.get("truncated"):
        return "truncated"
    if not row.get("valid"):
        return "invalid:" + ",".join(row.get("issues") or [])
    for key, least in rule.items():
        if key != "version" and (row.get(key) is None or row[key] < least):
            return FAIL_NAME.get(key, "low_" + key)
    return "ok"


def wilson(k: int, n: int, z: float = 1.96) -> list | None:
    """비율 k/n 의 95% 구간 (윌슨). 항목이 적으면 넓게 나온다 — 그만큼 모른다는 뜻이다."""
    if not n:
        return None
    p, d = k / n, 1 + z * z / n
    mid, half = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, mid - half), 3), round(min(1.0, mid + half), 3)]


def summarize(rows: list[dict], rule: dict = PASS_RULE) -> dict:
    rows = [{**r, "failure": failure(r, rule)} for r in rows]

    def block(rs):
        if not rs:
            return None
        mean = lambda k: (lambda xs: round(st.fmean(xs), 4) if xs else None)([r[k] for r in rs if r.get(k) is not None])
        by_image = {}
        for r in rs:
            by_image.setdefault(r["id"], []).append(r["failure"] == "ok")
        image_pass = sum(sum(v) * 2 > len(v) for v in by_image.values())
        unstable = sum(0 < sum(v) < len(v) for v in by_image.values())
        attempts_pass = sum(r["failure"] == "ok" for r in rs)
        return {"images": len(by_image), "attempts": len(rs),
                "attempt_pass": attempts_pass, "attempt_pass_rate": round(attempts_pass / len(rs), 4),
                "image_pass": image_pass, "image_pass_rate": round(image_pass / len(by_image), 4),
                "image_pass_ci95": wilson(image_pass, len(by_image)), "images_unstable": unstable,
                "valid_rate": round(sum(bool(r.get("valid")) for r in rs) / len(rs), 4),
                **{k: mean(k) for k in SCORES}, "failures": dict(Counter(r["failure"] for r in rs)),
                "seconds_mean": mean("seconds"), "completion_tokens_mean": mean("completion_tokens")}

    known = [r for r in rows if r.get("tier") in TIERS]
    return {"pass_rule": rule, "all": block(rows), "by_tier": {t: block([r for r in rows if r.get("tier") == t]) for t in TIERS},
            "no_tier": block([r for r in rows if r.get("tier") not in TIERS]) if len(known) != len(rows) else None}


def report(run: dict, summary: dict) -> str:
    rule = summary["pass_rule"]
    fmt = lambda v: "-" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))
    lines = [f"# {run['model']} · {run['items_name']}", ""]
    if run.get("candidates"):
        lines += [f"> **진단용.** 승인되지 않은 정답 후보 {len(run['candidates'])}개가 들어 있습니다. 이 표를 모델 성능으로 보고하지 않습니다.", ""]
    lines += ["> **통과 기준은 임시입니다** (" + rule["version"] + "): 유효 ∧ "
              + " ∧ ".join(f"{k} ≥ {v}" for k, v in rule.items() if k != "version") + ". 사람 판정으로 맞추기 전의 가설입니다.", "",
              f"규격 {run['contract']} · 프롬프트 {run['prompt']} · {run['protocol']} · 온도 {run['temperature']} · 출력 한도 {run['max_tokens']} · 반복 {run['repeat']} · {run.get('finished', '')}", "",
              "| 난이도 | 이미지 | 시도 | 시도 통과 | 이미지 통과 (95% 구간) | 반복마다 갈린 이미지 | 유효 | 값 자리 | 값 자리+위치 | 겹침 | 문구 F1 | 문구 재현 | 평균 초 | 평균 출력 토큰 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    blocks = [(t, summary["by_tier"][t]) for t in TIERS] + [("난이도 없음", summary.get("no_tier")), ("전체", summary["all"])]
    for name, b in blocks:
        if b:
            ci = b["image_pass_ci95"]
            lines.append(f"| {name} | {b['images']} | {b['attempts']} | {b['attempt_pass']}/{b['attempts']} ({b['attempt_pass_rate']:.0%}) | "
                         f"{b['image_pass']}/{b['images']} ({ci[0]:.0%}~{ci[1]:.0%}) | {b['images_unstable']} | {b['valid_rate']:.0%} | "
                         + " | ".join(fmt(b[k]) for k in SCORES) + f" | {fmt(b['seconds_mean'])} | {fmt(b['completion_tokens_mean'])} |")
    for name, b in blocks:
        if b and name != "전체":
            lines += ["", f"실패 유형 ({name}): " + ", ".join(f"{k} {v}" for k, v in sorted(b["failures"].items(), key=lambda t: -t[1]))]
    lines += ["", "- 이미지 통과 = 그 이미지의 시도 중 절반을 넘게 통과. 같은 이미지의 반복은 독립된 이미지가 아닙니다.",
              "- 구간이 넓으면 이미지 수가 모자란 것입니다. 이 표는 평가 세트와 닮은 문서에 대한 것이고, 새 문서의 성공을 보장하지 않습니다."]
    return "\n".join(lines) + "\n"


def mock_answer(kind: str, ref: str) -> str:
    if kind == "ref":
        return ref
    if kind == "nofields":
        return FIELD_RECT.sub("", ref)
    if kind == "empty":
        return ""
    raise SystemExit(f"모르는 --mock: {kind}")


def load_rows(out: Path) -> list[dict]:
    path = out / "results.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.is_file() else []


def write_summary(out: Path, cfg: dict, rows: list[dict], rule: dict = PASS_RULE) -> dict:
    summary = summarize(rows, rule)
    M.dump(out / "summary.json", summary)
    (out / "report.md").write_text(report(cfg, summary), encoding="utf-8")
    return summary


def run(a) -> dict:
    items_dir, out = Path(a.items), Path(a.out)
    ids = sorted(p.name for p in items_dir.iterdir() if (p / "ref.svg").is_file() and (p / "image.png").is_file())
    read = lambda p: p.read_text(encoding="utf-8-sig")
    metas = {i: json.loads(read(items_dir / i / "meta.json")) if (items_dir / i / "meta.json").is_file() else {} for i in ids}
    if a.tiers:
        ids = [i for i in ids if metas[i].get("tier") in a.tiers]
    if a.limit:
        ids = ids[:a.limit]
    if not ids:
        raise SystemExit(f"평가 항목이 없습니다 (image.png + ref.svg 가 있는 폴더): {items_dir}")
    candidates = [i for i in ids if metas[i].get("gold_approved") is not True]
    if candidates and not a.allow_candidates:
        raise SystemExit("승인되지 않은 정답 후보가 있습니다 (meta.json 의 gold_approved 가 true 가 아님). "
                         "개발·진단용으로만 --allow-candidates 를 붙여 돌리세요: " + ", ".join(candidates))
    cfg = {"model": a.model or f"mock:{a.mock}", "endpoint": a.endpoint, "contract": svg.VERSION, "prompt": M.PROMPT_VERSION, "protocol": "P1",
           "temperature": 0.0, "max_tokens": a.max_tokens, "repeat": a.repeat, "items": str(items_dir), "items_name": items_dir.name,
           "n_items": len(ids), "candidates": candidates, "pass_rule": PASS_RULE, "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    out.mkdir(parents=True, exist_ok=True)
    if (out / "run.json").is_file():
        old = json.loads(read(out / "run.json"))
        changed = [k for k in ("model", "contract", "prompt", "protocol", "max_tokens", "items_name") if old.get(k) != cfg[k]]
        if changed:
            raise SystemExit(f"{out} 에 다른 설정으로 돌린 결과가 있습니다 ({', '.join(changed)}). 새 --out 폴더를 쓰세요.")
    rows = load_rows(out)
    done = {(r["id"], r["repeat"]) for r in rows}
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
                usage = log.get("usage") or {}
                row = {"id": i, "repeat": rep, "tier": metas[i].get("tier"), "gold_approved": metas[i].get("gold_approved") is True,
                       "valid": log["valid"], "issues": s["issues"], "truncated": log["truncated"], "error": log.get("error"),
                       **{k: s[k] for k in ("fields_gt", "fields_pred", *SCORES, "text_p")},
                       "seconds": log.get("seconds"), "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
                       "svg_bytes": log["svg_bytes"]}
                rows.append(row)
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                print(f"[{n + 1}/{len(ids)}] {i} r{rep} {row['tier']} {failure(row)} 값자리={row['typed_field_f1']} "
                      f"위치={row['located_field_f1']} 문구={row['text_f1']} {row['seconds']}s", flush=True)
    keep = set(ids)
    rows = [r for r in rows if r["id"] in keep and r["repeat"] < a.repeat]
    cfg["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    M.dump(out / "run.json", cfg)
    return {"run": cfg, "summary": write_summary(out, cfg, rows)}


def rereport(out, rule: dict | None = None) -> str:
    """모델을 다시 부르지 않고 results.jsonl 에서 표를 다시 만든다 (통과 기준을 바꿨을 때)."""
    out = Path(out)
    cfg = json.loads((out / "run.json").read_text(encoding="utf-8"))
    rows = [r for r in load_rows(out) if r["repeat"] < cfg["repeat"]]
    write_summary(out, cfg, rows, rule or PASS_RULE)
    return (out / "report.md").read_text(encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m formgen bench", description="모델 하나의 svg 서식 생성 수준을 난이도별로 잰다")
    ap.add_argument("--items", required=True, help="평가 항목 폴더 (예: bench/official_pilot_v1)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--endpoint", default="", help="OpenAI 호환 주소, /v1 까지")
    ap.add_argument("--model", default="")
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--repeat", type=int, default=1, help="항목마다 돌리는 횟수")
    ap.add_argument("--tiers", nargs="*", default=None, help="이 난이도만 (하 중 상)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--allow-candidates", action="store_true", help="승인되지 않은 정답 후보도 돌린다 (진단용, 성능 보고 아님)")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--mock", default=None, choices=["ref", "nofields", "empty"], help="모델 없이 길 검사")
    a = ap.parse_args(argv)
    if not a.mock and not (a.endpoint and a.model):
        ap.error("--endpoint 와 --model 이 필요합니다 (또는 --mock)")
    run(a)
    print()
    print((Path(a.out) / "report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
