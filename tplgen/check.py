"""꾸러미가 쓸 만한가. 정답 파일 없이, 꾸러미를 실제로 돌려 보고 잰다.

  valid    규칙대로이고 예시 값으로 그려지는가
  layout   예시 값으로 그린 그림과 원본 이미지가 위에서 아래로 같은 모양의 줄을 같은 순서로 갖는 정도 (0~1). 글꼴·간격 차이는 봐준다
  missing  원본에서 통째로 빠진 가장 큰 덩어리 (0~1). 닮음은 평균이라 표 하나가 빠져도 통과할 수 있어 따로 본다
  coverage 기준 꾸러미(평가 세트의 reference/)가 있을 때만: 기준의 값 자리 중 이 꾸러미에도 같은 자리에 값 자리가 있는 비율.
           원본 값을 고정 글자로 박고 값 자리를 거의 안 만든 '게으른' 꾸러미는 닮음·견딤이 높게 나오므로 이것으로 잡는다
  ref_leak 기준 꾸러미가 있을 때만: 값을 비워 그렸는데 원본에 적힌 값(기준 sample.json)이 보이는 수
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

PASS_RULE = {"robust": 1.0, "layout": 0.6}
MAX_MISSING = 0.12                            # 빠짐이 이보다 크면 탈락 (임시)
MIN_COVERAGE = 0.7                            # 기준 꾸러미가 있을 때: 자리 재현이 이보다 작으면 탈락 (임시)     # 유효 ∧ 샘 0 ∧ 아래 점수 이상 (임시)
# Reviewed-reference gates, provisional until calibrated against human judgments.
REVIEW_RULE = {"field_recall": 1.0, "field_f1": 0.95, "sample_accuracy": 1.0,
               "fixed_text": 0.98, "change_pass_rate": 1.0, "layout": PASS_RULE["layout"]}
CELL = 8           # layout: 이 크기(px, 폭 794 기준)의 칸마다 잉크가 있는지만 본다


def paper(im):
    """사진이면 종이 부분만 펴서 꺼낸다: 밝은(종이색) 영역의 네 모서리를 찾아 직사각형으로 편다 (원근 보정).
    종이가 그림 전체인 스캔·렌더링은 그대로 나온다."""
    import numpy as np
    from PIL import Image, ImageFilter
    small = im.copy()
    small.thumbnail((600, 600))
    k = im.width / small.width
    a = np.asarray(small).astype(float)
    mask = np.asarray(Image.fromarray(((a > np.percentile(a, 95) - 45) * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(5))) > 0
    ys, xs = np.nonzero(mask)
    if len(xs) < 100:
        return im
    s, d = xs + ys, xs - ys
    quad = [(xs[s.argmin()], ys[s.argmin()]), (xs[d.argmax()], ys[d.argmax()]), (xs[s.argmax()], ys[s.argmax()]), (xs[d.argmin()], ys[d.argmin()])]
    quad = [(x * k, y * k) for x, y in quad]                                  # 왼위, 오른위, 오른아래, 왼아래
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = quad
    w = round((np.hypot(x1 - x0, y1 - y0) + np.hypot(x2 - x3, y2 - y3)) / 2)
    h = round((np.hypot(x3 - x0, y3 - y0) + np.hypot(x2 - x1, y2 - y1)) / 2)
    if w < 50 or h < 50:
        return im
    if w * h > 0.97 * im.width * im.height:                                   # 종이가 그림 전체 → 손대지 않는다
        return im
    dst = [(0, 0), (w, 0), (w, h), (0, h)]
    rows, rhs = [], []
    for (X, Y), (u, v) in zip(dst, quad):                                     # 출력 (X, Y) → 입력 (u, v) 의 투영 변환 계수
        rows += [[X, Y, 1, 0, 0, 0, -u * X, -u * Y], [0, 0, 0, X, Y, 1, -v * X, -v * Y]]
        rhs += [u, v]
    coeffs = np.linalg.solve(np.array(rows, float), np.array(rhs, float))
    return im.transform((w, h), Image.PERSPECTIVE, tuple(coeffs), Image.BICUBIC, fillcolor=255)


def bands(path, width: int = 794):
    """그림 → 위에서 아래로, 잉크가 있는 줄들 (줄마다 칸별 잉크 유무). 빈 줄은 뺀다 → 세로 간격 차이는 보지 않는다."""
    import numpy as np
    from PIL import Image
    im = paper(Image.open(path).convert("L"))
    im = im.resize((width, max(1, round(im.height * width / im.width))))
    a = np.asarray(im).astype(float)
    dark = a < min(160.0, np.percentile(a, 50) - 60)          # 종이색보다 뚜렷이 어두운 것이 잉크
    h, w = (dark.shape[0] // CELL) * CELL, (dark.shape[1] // CELL) * CELL
    grid = dark[:h, :w].reshape(h // CELL, CELL, w // CELL, CELL).mean(axis=(1, 3)) > 0.02
    return grid[grid.any(axis=1)]


def layout(original, rendered) -> tuple[float, float]:
    """(닮음, 빠짐). 두 그림의 잉크 줄을 위에서 아래로 순서를 지키며 짝짓는다 (줄끼리의 닮음은 가로로 이웃 칸까지 같은 자리로 봄).
      닮음  짝지은 닮음의 합 (0~1). 글꼴·행 높이·여백이 달라도 되고, 빠지거나 순서가 바뀌면 내려간다.
      빠짐  원본에서 짝을 못 찾은(닮음 < 0.5) 줄이 연달아 이어진 가장 긴 구간이 원본 잉크의 몇 할인가 (0~1).
            닮음은 평균이라 큰 덩어리(표 하나)가 빠져도 0.7 이 나올 수 있다 → 따로 잰다.
    기준점: 같은 문서 닮음 0.7~0.86 · 빠짐 0.07 이하 / 표가 빠짐 빠짐 0.16~0.35 / 다른 문서 닮음 0.3~0.4 (README 의 '점수와 눈' 실험)."""
    import numpy as np
    a, b = bands(original), bands(rendered)
    if not len(a) or not len(b):
        return 0.0, 1.0
    wide = lambda m: (m | np.roll(m, 1, 1) | np.roll(m, -1, 1)).astype(float)
    p = (b.astype(float) @ wide(a).T).T / np.maximum(b.sum(1), 1)[None, :]     # [i, j] = 그림 줄 j 의 잉크 중 원본 줄 i 근처인 비율
    q = (a.astype(float) @ wide(b).T) / np.maximum(a.sum(1), 1)[:, None]       # [i, j] = 원본 줄 i 의 잉크 중 그림 줄 j 근처인 비율
    sim = np.where(p + q > 0, 2 * p * q / np.maximum(p + q, 1e-9), 0)
    n, m = sim.shape
    best, move = np.zeros((n + 1, m + 1)), np.zeros((n + 1, m + 1), int)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            options = (best[i - 1, j], best[i, j - 1], best[i - 1, j - 1] + sim[i - 1, j - 1])
            move[i, j] = int(np.argmax(options))
            best[i, j] = options[move[i, j]]
    found, i, j = np.zeros(n, bool), n, m
    while i > 0 and j > 0:
        if move[i, j] == 2:
            found[i - 1] = sim[i - 1, j - 1] >= 0.5
            i, j = i - 1, j - 1
        elif move[i, j] == 0:
            i -= 1
        else:
            j -= 1
    ink, run, longest = a.sum(1).astype(float), 0.0, 0.0
    for k in range(n):
        run = 0.0 if found[k] else run + ink[k]
        longest = max(longest, run)
    return round(float(2 * best[-1, -1] / (n + m)), 3), round(float(longest / ink.sum()), 3)


def layout_score(original, rendered) -> float:
    return layout(original, rendered)[0]


def fill_assets(png, shot: dict):
    """그림 자리(로고·바코드·QR…)를 채운 사본을 만든다. 원본의 그 자리는 잉크로 차 있으므로, 비워 둔 것이 감점이 되지 않게."""
    from PIL import Image, ImageDraw
    if not shot["assets"]:
        return png
    im = Image.open(png).convert("L")
    k, d = im.width / shot["width"], ImageDraw.Draw(im)
    for a in shot["assets"]:
        x, y, w, h = [v * k for v in a["box"]]
        d.rectangle([x, y, x + w, y + h], fill=0)
    out = str(png)[:-4] + "_filled.png"
    im.save(out)
    return out


def leak_candidates(pkg: dict) -> set[str]:
    """틀에 박혀 있으면 안 되는 예시 값들. 보기(choice)·체크는 인쇄 문구와 같을 수 있어 빼고, 3글자 이상만 본다."""
    skip = {"choice", "bool"}
    out = {pkg["sample"].get(f["name"]) for f in pkg["schema"].get("fields") or [] if f.get("type") not in skip}
    for tb in pkg["schema"].get("tables") or []:
        for row in pkg["sample"].get(tb["name"]) or []:
            out |= {row.get(c["name"]) for c in P.columns(tb) if c.get("type") not in skip}
    return {v.strip() for v in out if isinstance(v, str) and len(v.strip()) >= 3}


def field_boxes(pkg: dict, renderer: Renderer, rows: int = 2) -> list[tuple]:
    """임의 값(표는 rows 행)으로 그린 값 자리들: (이름, 쪽 폭·높이로 나눈 [x0, y0, x1, y1]). 표의 칸은 이름의 행 번호를 지운다."""
    import random, re
    shot = renderer.render(P.html(pkg, D.make(pkg["schema"], random.Random(1), rows=rows)))
    W, H = max(shot["width"], 1), max(shot["height"], 1)
    return [(re.sub(r"\.\d+\.", ".#.", l["field"]), [l["box"][0] / W, l["box"][1] / H, (l["box"][0] + l["box"][2]) / W, (l["box"][1] + l["box"][3]) / H])
            for l in shot["labels"] if l["box"][2] > 0 and l["box"][3] > 0]


def coverage(pkg: dict, ref: dict, renderer: Renderer) -> float:
    """기준의 값 자리 중, 이 꾸러미의 값 자리와 겹치거나 가까운(쪽 폭의 3% · 높이의 2% 안) 것의 비율. 이름은 보지 않는다."""
    mine, theirs = field_boxes(pkg, renderer), field_boxes(ref, renderer)
    if not theirs:
        return 1.0
    near = lambda a, b: a[0] - 0.03 < b[2] and b[0] - 0.03 < a[2] and a[1] - 0.02 < b[3] and b[1] - 0.02 < a[3]
    return round(sum(any(near(t, m) for _, m in mine) for _, t in theirs) / len(theirs), 3)


def check(folder, image=None, out=None, renderer: Renderer | None = None, reference=None) -> dict:
    pkg = P.load(folder)
    result = {"valid": False, "issues": list(pkg["issues"]), "layout": None, "missing": None, "coverage": None, "ref_leak": None, "robust": 0.0, "leak": 0, "tests": {},
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
                        result["layout"], result["missing"] = layout(image, fill_assets(png, shot))
                if name == "empty":   # 값을 비웠는데도 예시 값이 보이면 틀에 박힌 것
                    text = r._page.inner_text("body")
                    if reference:
                        ref = P.load(reference)
                        result["ref_leak"] = sum(1 for v in leak_candidates(ref) if v in text)
                    result["leak"] = sum(1 for v in leak_candidates(pkg) if v in text)
            if reference and "sample" in result["tests"]:
                result["coverage"] = coverage(pkg, P.load(reference), r)
        finally:
            if own:
                r.__exit__()
    tests = result["tests"]
    result["valid"] = not tests.get("sample") or all(not p.startswith(("render_error", "no_page")) for p in tests["sample"])
    result["robust"] = round(sum(not p for p in tests.values()) / len(tests), 3) if tests else 0.0
    result["pass"] = bool(result["valid"] and result["leak"] == 0 and result["robust"] >= PASS_RULE["robust"]
                          and (result["layout"] is None or (result["layout"] >= PASS_RULE["layout"] and result["missing"] <= MAX_MISSING))
                          and (result["coverage"] is None or (result["coverage"] >= MIN_COVERAGE and result["ref_leak"] == 0)))
    return result


def brief(result: dict) -> str:
    bad = {k: v for k, v in result["tests"].items() if v}
    return (f"쓸 만함={result['pass']} 유효={result['valid']} 닮음={result['layout']} 빠짐={result['missing']} 견딤={result['robust']} 샘={result['leak']} "
            + (f"자리재현={result['coverage']} 기준샘={result['ref_leak']} " if result.get("coverage") is not None else "")
            + f"항목={result['fields']} 표={result['tables']}(열 {result['columns']}) 그림자리={result['assets']}"
            + ("\n규칙 위반: " + ", ".join(result["issues"]) if result["issues"] else "")
            + "".join(f"\n깨짐[{k}]: " + ", ".join(v[:8]) + (" …" if len(v) > 8 else "") for k, v in bad.items()))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="python -m tplgen check", description="꾸러미가 쓸 만한지 돌려 보고 잰다")
    ap.add_argument("package")
    ap.add_argument("--image", help="원본 이미지 (주면 닮음 점수도 낸다)")
    ap.add_argument("--out", help="시험마다 그린 그림을 남길 폴더")
    ap.add_argument("--reference", help="기준 꾸러미 폴더 (평가 세트의 reference/). 주면 자리 재현·기준 샘도 잰다")
    a = ap.parse_args(argv)
    print(brief(check(a.package, a.image, a.out, reference=a.reference)))


if __name__ == "__main__":
    main()
