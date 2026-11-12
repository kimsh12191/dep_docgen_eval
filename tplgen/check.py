"""꾸러미가 쓸 만한가. 정답 파일 없이, 꾸러미를 실제로 돌려 보고 잰다.

  valid    규칙대로이고 예시 값으로 그려지는가
  layout   예시 값으로 그린 그림과 원본 이미지의 배치가 닮은 정도 (0~1). 글꼴이 달라도 되게 거칠게 본다
  robust   값을 바꾸고 표 행을 바꿔 그려도 깨지지 않는 시험의 비율 (data.stress 의 시험들)
  leak     예시 값이 틀에 고정 글자로 박혀 있는 수 (값을 비워 그렸는데도 예시 값이 보이면 샌 것)
  fields · tables · columns · assets   개수 (참고)

쓸 만함(PASS_RULE)은 사람 눈으로 맞추기 전의 임시 기준이다.
실행: python -m tplgen check <꾸러미> [--image 원본.png] [--out 폴더(시험마다 그린 그림을 남김)]
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from . import data as D, package as P
from .render import Renderer

PASS_RULE = {"robust": 1.0, "layout": 0.5}     # 유효 ∧ 샘 0 ∧ 아래 점수 이상 (임시)
CELL = 12          # layout: 이 크기(px, 폭 794 기준)의 칸마다 잉크가 있는지만 본다


def ink_grid(path, width: int = 794):
    """그림 → 칸마다 잉크가 있는가 (2차원 bool). 종이색보다 뚜렷이 어두운 것을 잉크로 본다."""
    import numpy as np
    from PIL import Image
    im = Image.open(path).convert("L")
    im = im.resize((width, max(1, round(im.height * width / im.width))))
    a = np.asarray(im).astype(float)
    dark = a < min(160.0, np.percentile(a, 50) - 60)
    h, w = (dark.shape[0] // CELL) * CELL, (dark.shape[1] // CELL) * CELL
    cells = dark[:h, :w].reshape(h // CELL, CELL, w // CELL, CELL).mean(axis=(1, 3))
    return cells > 0.02


def layout_score(original, rendered) -> float:
    """두 그림의 잉크 칸이 겹치는 정도 (F1). 이웃 칸까지는 같은 자리로 본다. 높이가 다르면 긴 쪽에 맞춘다."""
    import numpy as np
    a, b = ink_grid(original), ink_grid(rendered)
    rows = max(a.shape[0], b.shape[0])
    pad = lambda m: np.pad(m, ((0, rows - m.shape[0]), (0, 0)))
    a, b = pad(a), pad(b)

    def near(m):
        out = m.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                out |= np.roll(np.roll(m, dy, 0), dx, 1)
        return out
    if not a.any() or not b.any():
        return 0.0
    p, r = (b & near(a)).sum() / b.sum(), (a & near(b)).sum() / a.sum()
    return round(float(2 * p * r / (p + r)) if p + r else 0.0, 3)


def leak_candidates(pkg: dict) -> set[str]:
    """틀에 박혀 있으면 안 되는 예시 값들. 보기(choice)·체크는 인쇄 문구와 같을 수 있어 빼고, 3글자 이상만 본다."""
    skip = {"choice", "bool"}
    out = {pkg["sample"].get(f["name"]) for f in pkg["schema"].get("fields") or [] if f.get("type") not in skip}
    for tb in pkg["schema"].get("tables") or []:
        for row in pkg["sample"].get(tb["name"]) or []:
            out |= {row.get(c["name"]) for c in P.columns(tb) if c.get("type") not in skip}
    return {v.strip() for v in out if isinstance(v, str) and len(v.strip()) >= 3}


def check(folder, image=None, out=None, renderer: Renderer | None = None) -> dict:
    pkg = P.load(folder)
    result = {"valid": False, "issues": list(pkg["issues"]), "layout": None, "robust": 0.0, "leak": 0, "tests": {},
              "fields": len(pkg["schema"].get("fields") or []), "tables": len(pkg["schema"].get("tables") or []),
              "columns": sum(len(P.columns(t)) for t in pkg["schema"].get("tables") or [] if isinstance(t, dict)), "assets": 0}
    if pkg["issues"]:
        return {**result, "pass": False}
    keep = Path(out) if out else None
    with tempfile.TemporaryDirectory() as tmp:
        own = renderer is None
        r = renderer or Renderer().__enter__()
        try:
            for name, values in D.stress(pkg["schema"], pkg["sample"]):
                png = (keep or Path(tmp)) / f"{name}.png"
                try:
                    shot = r.render(P.html(pkg, values), png)
                except Exception as e:   # 템플릿이 이 값에서 터짐
                    result["tests"][name] = [f"render_error:{type(e).__name__}:{str(e)[:80]}"]
                    continue
                got = {l["field"] for l in shot["labels"]}
                problems = list(shot["problems"]) + [f"missing:{p}" for p in P.paths(pkg["schema"], values) if p not in got]
                result["tests"][name] = problems
                if keep:
                    (keep / f"{name}.json").write_text(json.dumps({"data": values, **shot}, ensure_ascii=False, indent=1), encoding="utf-8")
                if name == "sample":
                    result["assets"] = len(shot["assets"])
                    if image and shot["width"]:
                        result["layout"] = layout_score(image, png)
                if name == "empty":   # 값을 비웠는데도 예시 값이 보이면 틀에 박힌 것
                    text = r._page.inner_text("body")
                    result["leak"] = sum(1 for v in leak_candidates(pkg) if v in text)
        finally:
            if own:
                r.__exit__()
    tests = result["tests"]
    result["valid"] = not tests.get("sample") or all(not p.startswith(("render_error", "no_page")) for p in tests["sample"])
    result["robust"] = round(sum(not p for p in tests.values()) / len(tests), 3) if tests else 0.0
    result["pass"] = bool(result["valid"] and result["leak"] == 0 and result["robust"] >= PASS_RULE["robust"]
                          and (result["layout"] is None or result["layout"] >= PASS_RULE["layout"]))
    return result


def brief(result: dict) -> str:
    bad = {k: v for k, v in result["tests"].items() if v}
    return (f"쓸 만함={result['pass']} 유효={result['valid']} 닮음={result['layout']} 견딤={result['robust']} 샘={result['leak']} "
            f"항목={result['fields']} 표={result['tables']}(열 {result['columns']}) 그림자리={result['assets']}"
            + ("\n규칙 위반: " + ", ".join(result["issues"]) if result["issues"] else "")
            + "".join(f"\n깨짐[{k}]: " + ", ".join(v[:8]) + (" …" if len(v) > 8 else "") for k, v in bad.items()))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="python -m tplgen check", description="꾸러미가 쓸 만한지 돌려 보고 잰다")
    ap.add_argument("package")
    ap.add_argument("--image", help="원본 이미지 (주면 닮음 점수도 낸다)")
    ap.add_argument("--out", help="시험마다 그린 그림을 남길 폴더")
    a = ap.parse_args(argv)
    print(brief(check(a.package, a.image, a.out)))


if __name__ == "__main__":
    main()
