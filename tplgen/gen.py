"""꾸러미 + 값 → 문서 이미지 + 라벨. 외주·다른 사람이 쓰는 쪽.

한 장:    python -m tplgen render <꾸러미> --data my.json --out gen/0001      → gen/0001.png, gen/0001.json
여러 장:  python -m tplgen vary <꾸러미> --n 20 --out gen/ [--seed 0]        → gen/0000.png, gen/0000.json, …
라벨(json): {"data": 넣은 값, "width", "height", "labels": [{"field": 경로, "text": 그려진 글자, "box": [x, y, w, h]}], "assets": [...], "problems": [...]}
  box 는 CSS px (이미지 픽셀은 2배). problems 가 비어 있지 않은 장은 깨진 것이니 학습에 쓰기 전에 걸러 낸다.
값을 직접 만들 때는 schema.json 을 보고 같은 이름으로 json 을 쓰면 된다 (LLM 에 schema.json 을 주고 만들게 해도 된다).
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from . import data as D, package as P
from .render import Renderer


def one(pkg: dict, values: dict, prefix, renderer: Renderer) -> dict:
    prefix = Path(prefix)
    shot = renderer.render(P.html(pkg, values), prefix.with_suffix(".png"))
    got = {l["field"] for l in shot["labels"]}
    shot["problems"] += [f"missing:{p}" for p in P.paths(pkg["schema"], values) if p not in got]
    prefix.with_suffix(".json").write_text(json.dumps({"data": values, **shot}, ensure_ascii=False, indent=1), encoding="utf-8")
    return shot


def _load(folder) -> dict:
    pkg = P.load(folder)
    if pkg["issues"]:
        raise SystemExit("꾸러미가 규칙에 안 맞습니다: " + ", ".join(pkg["issues"]))
    return pkg


def render_main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m tplgen render", description="꾸러미 + 값 → 이미지 + 라벨")
    ap.add_argument("package")
    ap.add_argument("--data", help="값 json (없으면 꾸러미의 sample.json)")
    ap.add_argument("--out", required=True, help="출력 이름 (확장자 없이)")
    a = ap.parse_args(argv)
    pkg = _load(a.package)
    values = json.loads(Path(a.data).read_text(encoding="utf-8")) if a.data else pkg["sample"]
    with Renderer() as r:
        shot = one(pkg, values, a.out, r)
    print(a.out + ".png", f"값 {len(shot['labels'])}개", "깨짐: " + ", ".join(shot["problems"]) if shot["problems"] else "이상 없음")


def vary_main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m tplgen vary", description="꾸러미에 임의 값을 넣어 여러 장")
    ap.add_argument("package")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--out", required=True, help="출력 폴더")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    pkg, rng, bad = _load(a.package), random.Random(a.seed), 0
    with Renderer() as r:
        for i in range(a.n):
            bad += bool(one(pkg, D.make(pkg["schema"], rng), Path(a.out) / f"{i:04d}", r)["problems"])
    print(f"{a.n}장 → {a.out} (깨진 장 {bad})")
