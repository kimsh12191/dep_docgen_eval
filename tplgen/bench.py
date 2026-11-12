"""여러 모델 × 여러 이미지: 꾸러미를 만들게 하고 check 점수로 비교한다. 정답 파일이 필요 없다.

결과  <out>/<모델 name>/<이미지 이름>/   make 의 출력 (round<k>/, final/)
      <out>/<모델 name>/results.jsonl    이미지·회차마다 한 줄 (있는 이미지는 다시 돌리지 않는다)
      <out>/compare.md                  모델 × (한 번만 생성 / 고른 것) 표
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


def run_model(cfg: dict, m: dict, renderer: Renderer) -> Path:
    out = Path(cfg["out"]) / m["name"]
    out.mkdir(parents=True, exist_ok=True)
    images = sorted(p for p in Path(cfg["images"]).iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
    if not images:
        raise SystemExit(f"이미지가 없습니다: {cfg['images']}")
    done = {r["image"] for r in rows_of(out)}
    with (out / "results.jsonl").open("a", encoding="utf-8") as fh:
        for n, image in enumerate(images):
            if image.stem in done:
                continue
            logs = M.make(image, out / image.stem, m, cfg["rounds"], renderer)
            picked = json.loads((out / image.stem / "final" / "result.json").read_text(encoding="utf-8"))["round"]
            tokens = seconds = 0
            for g in logs:
                tokens += (g.get("usage") or {}).get("completion_tokens") or 0
                seconds += g.get("seconds") or 0
                res = g["result"]
                row = {"image": image.stem, "round": g["round"], "picked": g["round"] == picked, "error": g.get("error"),
                       **{k: res.get(k) for k in ("pass", "valid", "layout", "missing", "robust", "leak", "fields", "tables", "columns", "assets", "issues")},
                       "broken_tests": [k for k, v in res["tests"].items() if v], "tokens_total": tokens, "seconds_total": round(seconds, 1)}
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"{m['name']} [{n + 1}/{len(images)}] {image.stem} round{g['round']}{' *' if row['picked'] else ''} "
                      f"쓸만함={row['pass']} 닮음={row['layout']} 견딤={row['robust']} 샘={row['leak']} {', '.join(row['issues'][:3])}", flush=True)
            fh.flush()
    return out


def line(name: str, what: str, rows: list[dict]) -> str:
    if not rows:
        return f"| {name} | {what} | - | - | - | - | - | - | - |"
    mean = lambda k: (lambda xs: f"{st.fmean(xs):.2f}" if xs else "-")([r[k] for r in rows if r.get(k) is not None])
    return (f"| {name} | {what} | {sum(r['pass'] for r in rows)}/{len(rows)} | {sum(r['valid'] for r in rows)}/{len(rows)} | {mean('layout')} | {mean('robust')} "
            f"| {sum(r['leak'] > 0 for r in rows)} | {mean('tokens_total')} | {mean('seconds_total')} |")


def compare(outs: list) -> str:
    lines = ["| 모델 | 무엇 | 쓸 만함 | 유효 | 닮음 평균 | 견딤 평균 | 값이 샌 이미지 | 누적 평균 출력 토큰 | 누적 평균 초 |", "|---|---|---|---|---|---|---|---|---|"]
    for out in outs:
        rows, name = rows_of(Path(out)), Path(out).name
        last = max((r["round"] for r in rows), default=0)
        lines.append(line(name, "한 번만 생성", [r for r in rows if r["round"] == 0]))
        if last:
            final = [r for r in rows if r["picked"]]
            lines.append(line(name, f"고치기 {last}회 중 고른 것", final))
            first = {r["image"]: r for r in rows if r["round"] == 0}
            up = sum(M.rank(r) > M.rank(first[r["image"]]) for r in final)
            lines.append(f"| | 고치기로 나아진 이미지 | {up}/{len(final)} | | | | | | |")
    rule = " ∧ ".join(f"{k} ≥ {v}" for k, v in C.PASS_RULE.items())
    return "\n".join(lines) + f"\n\n쓸 만함(임시 기준) = 유효 ∧ 샘 0 ∧ {rule}. 정답 없이 꾸러미를 돌려 보고 잰 점수다.\n"


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
