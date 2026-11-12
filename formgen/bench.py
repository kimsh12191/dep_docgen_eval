"""벤치마크: 설정 파일의 모델마다 golden set 의 이미지로 svg 를 만들고 정답과 채점해, 단일 생성과 셀프 고치기 회차별로 난이도별 표를 낸다.

평가 항목  <items>/<id>/{image.png, ref.svg, meta.json}      meta.json 의 "tier" = 하 · 중 · 상
결과       <out>/<name>/run.json       그 모델의 실행 설정
           <out>/<name>/results.jsonl  항목·반복·회차마다 한 줄 (있는 시도는 다시 돌리지 않는다 → 끊겨도 같은 설정으로 이어서)
           <out>/<name>/report.md      회차별·난이도별 표
           <out>/<name>/items/<id>/r<반복>/round<회차>/   out.svg · raw.txt · make.json · view.png
           <out>/compare.md            모델 × (단일 / 고친 뒤) × 난이도

통과 기준(PASS_RULE)은 사람 판정으로 맞추기 전의 **임시값**이다. results.jsonl 에는 점수만 남기므로
기준을 고친 뒤 `python -m formgen report <out>/<name>` 을 돌리면 모델을 다시 부르지 않고 표가 바뀐다.
같은 이미지를 여러 번 돌린 것은 이미지 여러 장이 아니다. 이미지 통과 = 그 이미지의 시도 중 절반을 넘게 통과.

실행      python -m formgen bench configs/example.json [--only A B]
모델 비교  python -m formgen compare runs/exp1/A runs/exp1/B …
길 검사    configs/mock.json (모델 대신 정답·값 자리를 지운 답 등을 쓴다)
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics as st
from collections import Counter
from pathlib import Path

from . import config, make as M, svg

TIERS = ("하", "중", "상")
PASS_RULE = {"field_recall": 0.8, "text_f1": 0.8}          # 유효 ∧ 아래 점수가 모두 이 값 이상 (임시)
FAIL_NAME = {"field_recall": "low_fields", "text_f1": "low_text"}
SCORES = ("field_recall", "field_precision", "label_acc", "type_acc", "iou_mean", "text_f1")
FIELD_RECT = re.compile(r"<rect\b[^>]*\bdata-field=[^>]*/>")
SAME_SETTING = ("model", "items_name", "prompt", "fix_prompt", "scorer", "max_tokens", "temperature", "extra", "rounds", "mock")


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
    """한 회차의 줄들 → {"하": 집계, "중": …, "상": …, "전체": …}. 줄이 없는 난이도는 None."""
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
                "broken": sum(failure(r) not in ("ok", "low_fields", "low_text") for r in rs),
                "seconds_total": mean("seconds_total"), "tokens_total": mean("tokens_total")}
    return {**{t: block([r for r in rows if r.get("tier") == t]) for t in TIERS}, "전체": block(rows)}


def at(rows: list[dict], k: int) -> list[dict]:
    return [r for r in rows if r.get("round", 0) == k]


def change(rows: list[dict], last: int, key: str = "field_recall") -> dict:
    """0회차 → 마지막 회차, 시도마다 점수가 오른·내린·같은 수. 셀프 고치기가 도움이 됐는지 보는 첫 숫자."""
    first = {(r["id"], r["repeat"]): r.get(key) or 0 for r in at(rows, 0)}
    end = {(r["id"], r["repeat"]): r.get(key) or 0 for r in at(rows, last)}
    d = [end[k] - first[k] for k in first if k in end]
    return {"up": sum(x > 0.001 for x in d), "down": sum(x < -0.001 for x in d), "same": sum(abs(x) <= 0.001 for x in d)}


def report(run: dict, rows: list[dict]) -> str:
    fmt = lambda v: "-" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))
    last = run["rounds"]
    lines = [f"# {run['name']} ({run['model']}) · {run['items_name']}", "",
             "통과(임시 기준) = 유효 ∧ " + " ∧ ".join(f"{k} ≥ {v}" for k, v in PASS_RULE.items())
             + f" · 프롬프트 {run['prompt']}" + (f" + {run['fix_prompt']}" if last else "") + f" · 채점 {run['scorer']}"
             + f" · 출력 한도 {run['max_tokens']} · 온도 {run['temperature']} · 반복 {run['repeat']} · 고치기 {last}회", ""]
    if last:
        lines += ["## 회차별 (0회차 = 한 번만 생성)", "",
                  "| 회차 | 이미지 통과 | 값 자리 재현 | 값 자리 정밀 | 문구 | 유효하지 않거나 잘림 | 누적 평균 출력 토큰 | 누적 평균 초 |", "|---|---|---|---|---|---|---|---|"]
        for k in range(last + 1):
            b = summarize(at(rows, k))["전체"]
            if b:
                lines.append(f"| {k} | {b['image_pass']}/{b['images']} | {fmt(b['field_recall'])} | {fmt(b['field_precision'])} | {fmt(b['text_f1'])} "
                             f"| {b['broken']}/{b['attempts']} | {fmt(b['tokens_total'])} | {fmt(b['seconds_total'])} |")
        c, ct = change(rows, last), change(rows, last, "text_f1")
        lines += ["", f"0회차 → {last}회차, 시도마다: 값 자리 재현 오름 {c['up']} · 내림 {c['down']} · 같음 {c['same']} / "
                      f"문구 오름 {ct['up']} · 내림 {ct['down']} · 같음 {ct['same']}", ""]
    for k in sorted({0, last}):
        s = summarize(at(rows, k))
        lines += [f"## 난이도별 · {'한 번만 생성 (0회차)' if k == 0 else f'고친 뒤 ({k}회차)'}", "",
                  "| 난이도 | 이미지 통과 | 95% 구간 | 시도 통과 | 반복마다 갈림 | 값 자리 재현 | 값 자리 정밀 | 항목명 | 종류 | 겹침 | 문구 | 누적 평균 초 | 누적 평균 출력 토큰 |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for name, b in s.items():
            if b:
                lo, hi = wilson(b["image_pass"], b["images"])
                lines.append(f"| {name} | {b['image_pass']}/{b['images']} | {lo:.0%}~{hi:.0%} | {b['attempt_pass']}/{b['attempts']} | {b['unstable']} | "
                             + " | ".join(fmt(b[x]) for x in SCORES) + f" | {fmt(b['seconds_total'])} | {fmt(b['tokens_total'])} |")
        lines += ["", "실패 유형: " + " / ".join(f"{name} " + ", ".join(f"{x} {v}" for x, v in sorted(b["failures"].items(), key=lambda t: -t[1]))
                                             for name, b in s.items() if b and name != "전체"), ""]
    return "\n".join(lines)


def mock_answers(spec: str, ref: str) -> list[str]:
    kinds = {"ref": ref, "nofields": FIELD_RECT.sub("", ref), "empty": ""}
    return [kinds[k] for k in spec.split(",")]


def load(out) -> tuple[dict, list[dict]]:
    """결과 폴더 → (실행 설정, 줄 목록)."""
    out = Path(out)
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    path = out / "results.jsonl"
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.is_file() else []
    return run, [r for r in rows if r["repeat"] < run["repeat"] and r.get("round", 0) <= run["rounds"]]


def rereport(out) -> str:
    """모델을 다시 부르지 않고 표를 다시 만든다 (통과 기준을 바꿨을 때)."""
    run, rows = load(out)
    text = report(run, rows)
    (Path(out) / "report.md").write_text(text, encoding="utf-8")
    return text


def compare(outs: list) -> str:
    """여러 모델의 결과 폴더 → 모델 × (한 번만 / 고친 뒤) × 난이도 표. 칸 = 이미지 통과 수/이미지 수 (값 자리 재현 평균)."""
    lines = ["| 모델 | 회차 | " + " | ".join(TIERS) + " | 전체 | 유효하지 않거나 잘린 시도 | 누적 평균 출력 토큰 | 누적 평균 초 |", "|---|---|---|---|---|---|---|---|---|"]
    cell = lambda b: "-" if not b else f"{b['image_pass']}/{b['images']} ({b['field_recall'] or 0:.2f})"
    for out in outs:
        run, rows = load(out)
        for k in sorted({0, run["rounds"]}):
            s = summarize(at(rows, k))
            if not s["전체"]:
                continue
            lines.append(f"| {run['name']} | {k} | " + " | ".join(cell(s[t]) for t in TIERS) + f" | {cell(s['전체'])} | {s['전체']['broken']}/{s['전체']['attempts']} "
                         f"| {s['전체']['tokens_total'] or '-'} | {s['전체']['seconds_total'] if s['전체']['seconds_total'] is not None else '-'} |")
    return "\n".join(lines) + "\n\n회차 0 = 한 번만 생성, 그 밖 = 셀프 고치기 뒤. 칸 = 통과한 이미지 수/이미지 수 (값 자리 재현 평균). " \
        + "토큰·초는 그 회차까지 누적. 통과 기준은 임시값이다: 유효 ∧ " + " ∧ ".join(f"{k} ≥ {v}" for k, v in PASS_RULE.items()) + "\n"


def run_model(cfg: dict, m: dict) -> Path:
    items_dir, out = Path(cfg["items"]), Path(cfg["out"]) / m["name"]
    read = lambda p: p.read_text(encoding="utf-8-sig")
    ids = sorted(p.name for p in items_dir.iterdir() if (p / "ref.svg").is_file() and (p / "image.png").is_file())
    if not ids:
        raise SystemExit(f"평가 항목이 없습니다 (image.png + ref.svg 가 있는 폴더): {items_dir}")
    tiers = {i: json.loads(read(items_dir / i / "meta.json")).get("tier") if (items_dir / i / "meta.json").is_file() else None for i in ids}
    rounds = cfg["rounds"]
    run = {"name": m["name"], "model": m.get("model") or f"mock:{m['mock']}", "endpoint": m.get("endpoint"), "items_name": items_dir.name,
           "n_items": len(ids), "prompt": M.PROMPT_VERSION, "fix_prompt": M.FIX_VERSION if rounds else None, "scorer": svg.SCORER,
           "max_tokens": m["max_tokens"], "temperature": m["temperature"], "extra": m["extra"], "rounds": rounds, "repeat": cfg["repeat"],
           "mock": m["mock"], "font_files": cfg["font_files"]}
    out.mkdir(parents=True, exist_ok=True)
    if (out / "run.json").is_file():
        old = json.loads(read(out / "run.json"))
        changed = [k for k in SAME_SETTING if k in run and old.get(k) != run[k]]
        if changed:
            raise SystemExit(f"{out} 에 다른 설정으로 돌린 결과가 있습니다 ({', '.join(changed)}). 설정의 out 이나 name 을 바꾸세요.")
    (out / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    done = {(r["id"], r["repeat"]) for r in load(out)[1]}
    with (out / "results.jsonl").open("a", encoding="utf-8") as fh:
        for n, i in enumerate(ids):
            ref = read(items_dir / i / "ref.svg")
            for rep in range(cfg["repeat"]):
                if (i, rep) in done:
                    continue
                d = out / "items" / i / f"r{rep}"
                logs = M.make(items_dir / i / "image.png", d, m, rounds, cfg["font_files"],
                              answers=mock_answers(m["mock"], ref) if m["mock"] else None)
                tokens = seconds = 0
                for k in range(rounds + 1):
                    log = logs[min(k, len(logs) - 1)]   # 요청이 실패해 멈췄으면 남은 회차도 그 실패로 센다
                    if k < len(logs):
                        tokens += (log.get("usage") or {}).get("completion_tokens") or 0
                        seconds += log.get("seconds") or 0
                    s = svg.score(ref, read(d / f"round{log['round']}" / "out.svg"))
                    row = {"id": i, "repeat": rep, "round": k, "tier": tiers[i], **{x: v for x, v in s.items() if x != "scorer"},
                           "valid": log["valid"], "truncated": log["truncated"], "error": log.get("error"), "seconds": log.get("seconds"),
                           "completion_tokens": (log.get("usage") or {}).get("completion_tokens"), "svg_bytes": log["svg_bytes"],
                           "tokens_total": tokens, "seconds_total": round(seconds, 2), "picture": (log.get("feedback") or {}).get("picture")}
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    print(f"{m['name']} [{n + 1}/{len(ids)}] {i} r{rep} round{k} {row['tier']} {failure(row)} "
                          f"값자리={row['field_recall']} 문구={row['text_f1']} {row['seconds']}s", flush=True)
                fh.flush()
    rereport(out)
    return out


def run(cfg, only: list[str] | None = None) -> str:
    """설정의 모델을 차례로 돌리고 비교표를 돌려준다."""
    cfg = config.load(cfg)
    models = [m for m in cfg["models"] if not only or m["name"] in only]
    outs = [run_model(cfg, m) for m in models]
    table = compare(outs)
    (Path(cfg["out"]) / "compare.md").write_text(table, encoding="utf-8")
    return table


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m formgen bench", description="설정 파일의 모델들의 svg 서식 생성 수준을 단일·셀프 고치기, 난이도별로 잰다")
    ap.add_argument("config", help="설정 파일 (configs/example.json 꼴)")
    ap.add_argument("--only", nargs="*", help="이 name 의 모델만")
    a = ap.parse_args(argv)
    print("\n" + run(a.config, a.only))


if __name__ == "__main__":
    main()
