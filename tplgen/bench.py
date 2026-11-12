"""여러 모델 × 여러 이미지: 꾸러미를 만들게 하고 check 점수로 비교한다. 정답 파일이 필요 없다.

평가 세트  evalset/v1/<id>/{image.*, meta.json(tier = 하·중·상), reference/}  — 설정의 "images" 로 준다. 이미지만 든 폴더도 된다 (난이도 없음)
결과  <out>/<모델 name>/<이미지 이름>/   make 의 출력 (round<k>/, final/)
      <out>/<모델 name>/results.jsonl    이미지·회차마다 한 줄 (있는 이미지는 다시 돌리지 않는다)
      <out>/compare.md                  모델 × (한 번만 생성 / 고른 것) × 난이도 표
길 검사  모델 항목에 "mock": "reference" 를 주면 항목마다 reference/ 꾸러미를 답으로 쓴다 (모두 통과해야 정상)
실행  python -m tplgen bench configs/local.json [--only A B]
"""
from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path

from . import check as C, config, make as M
from .render import Renderer


def rows_of(out: Path) -> list[dict]:
    p = out / "results.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.is_file() else []


TIERS = ("하", "중", "상")
EXTS = (".png", ".jpg", ".jpeg", ".webp")


def items(folder) -> list[dict]:
    """평가 항목: {"id", "image", "tier", "reference"}. 항목 폴더(evalset 꼴) 또는 이미지 파일."""
    out = []
    for p in sorted(Path(folder).iterdir()):
        if p.is_dir():
            image = next((q for q in sorted(p.iterdir()) if q.stem == "image" and q.suffix.lower() in EXTS), None)
            if image:
                meta = json.loads((p / "meta.json").read_text(encoding="utf-8")) if (p / "meta.json").is_file() else {}
                out.append({"id": p.name, "image": image, "tier": meta.get("tier"), "reference": p / "reference"})
        elif p.suffix.lower() in EXTS:
            out.append({"id": p.stem, "image": p, "tier": None, "reference": None})
    return out


def run_model(cfg: dict, m: dict, renderer: Renderer) -> Path:
    out = Path(cfg["out"]) / m["name"]
    out.mkdir(parents=True, exist_ok=True)
    todo = items(cfg["images"])
    if not todo:
        raise SystemExit(f"평가 항목이 없습니다: {cfg['images']}")
    done = {r["image"] for r in rows_of(out)}
    with (out / "results.jsonl").open("a", encoding="utf-8") as fh:
        for n, it in enumerate(todo):
            if it["id"] in done:
                continue
            mm = m
            if m.get("mock") == "reference":   # 항목의 기준 꾸러미를 답으로 (길 검사: 모두 통과해야 정상)
                answer = out / it["id"] / "reference_answer.txt"
                answer.parent.mkdir(parents=True, exist_ok=True)
                answer.write_text("".join(f"=== {f} ===\n" + (it["reference"] / f).read_text(encoding="utf-8")
                                          for f in ("template.html", "schema.json", "sample.json")), encoding="utf-8")
                mm = {**m, "mock": str(answer)}
            logs = M.make(it["image"], out / it["id"], mm, cfg["rounds"], renderer)
            picked = json.loads((out / it["id"] / "final" / "result.json").read_text(encoding="utf-8"))["round"]
            tokens = seconds = 0
            for g in logs:
                tokens += (g.get("usage") or {}).get("completion_tokens") or 0
                seconds += g.get("seconds") or 0
                res = g["result"]
                if it["reference"] and it["reference"].is_dir():   # 채점에만 기준 꾸러미를 쓴다 (루프가 회차를 고를 때는 쓰지 않는다 → 정답이 루프에 새지 않게)
                    res = C.check(out / it["id"] / f"round{g['round']}", it["image"], renderer=renderer, reference=it["reference"])
                row = {"image": it["id"], "tier": it["tier"], "round": g["round"], "picked": g["round"] == picked, "error": g.get("error"),
                       **{k: res.get(k) for k in ("pass", "valid", "layout", "missing", "coverage", "ref_leak", "robust", "leak", "fields", "tables", "columns", "assets", "issues")},
                       "broken_tests": [k for k, v in res["tests"].items() if v], "tokens_total": tokens, "seconds_total": round(seconds, 1)}
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"{m['name']} [{n + 1}/{len(todo)}] {it['id']} ({it['tier'] or '-'}) round{g['round']}{' *' if row['picked'] else ''} "
                      f"쓸만함={row['pass']} 닮음={row['layout']} 빠짐={row['missing']} 자리재현={row['coverage']} 견딤={row['robust']} 샘={row['leak']} {', '.join(row['issues'][:3])}", flush=True)
            fh.flush()
    return out


def line(name: str, what: str, rows: list[dict]) -> str:
    if not rows:
        return f"| {name} | {what} |" + " - |" * (len(TIERS) + 7)
    mean = lambda k, rs=rows: (lambda xs: f"{st.fmean(xs):.2f}" if xs else "-")([r[k] for r in rs if r.get(k) is not None])
    tier = lambda t: (lambda rs: f"{sum(r['pass'] for r in rs)}/{len(rs)}" if rs else "-")([r for r in rows if r.get("tier") == t])
    return (f"| {name} | {what} | " + " | ".join(tier(t) for t in TIERS) + f" | **{sum(r['pass'] for r in rows)}/{len(rows)}** | {mean('layout')} | {mean('missing')} | {mean('coverage')} | {mean('robust')} "
            f"| {sum((r['leak'] or 0) > 0 or (r.get('ref_leak') or 0) > 0 for r in rows)} | {mean('tokens_total')} | {mean('seconds_total')} |")


def compare(outs: list) -> str:
    lines = ["| 모델 | 무엇 | " + " | ".join(TIERS) + " | 전체 쓸 만함 | 닮음 평균 | 빠짐 평균 | 자리 재현 평균 | 견딤 평균 | 값이 샌 이미지 | 누적 평균 출력 토큰 | 누적 평균 초 |",
             "|---|---|" + "---|" * (len(TIERS) + 8)]
    for out in outs:
        rows, name = rows_of(Path(out)), Path(out).name
        last = max((r["round"] for r in rows), default=0)
        lines.append(line(name, "한 번만 생성", [r for r in rows if r["round"] == 0]))
        if last:
            final = [r for r in rows if r["picked"]]
            lines.append(line(name, f"고치기 {last}회 중 고른 것", final))
            first = {r["image"]: r for r in rows if r["round"] == 0}
            up = sum(M.rank(r) > M.rank(first[r["image"]]) for r in final)
            lines.append(f"| | 고치기로 나아진 이미지 {up}/{len(final)} |" + " |" * (len(TIERS) + 8))
    rule = " ∧ ".join(f"{k} ≥ {v}" for k, v in C.PASS_RULE.items())
    return "\n".join(lines) + f"\n\n칸(하·중·상·전체) = 쓸 만한 이미지 수/이미지 수. 쓸 만함(임시 기준) = 유효 ∧ 샘 0 ∧ {rule} ∧ missing ≤ {C.MAX_MISSING} ∧ (기준 꾸러미가 있으면) 자리 재현 ≥ {C.MIN_COVERAGE} ∧ 기준 샘 0. 루프가 회차를 고를 때는 기준 꾸러미를 쓰지 않는다.\n"


def run(cfg, only: list[str] | None = None) -> str:
    cfg = config.load(cfg)
    with Renderer() as r:
        outs = [run_model(cfg, m, r) for m in cfg["models"] if not only or m["name"] in only]
    table = compare(outs)
    (Path(cfg["out"]) / "compare.md").write_text(table, encoding="utf-8")
    return table


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m tplgen bench", description="설정의 모델들이 만든 꾸러미를 비교한다")
    ap.add_argument("config")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args(argv)
    print("\n" + run(a.config, a.only))


if __name__ == "__main__":
    main()
