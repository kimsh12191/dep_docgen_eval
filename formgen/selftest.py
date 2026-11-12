"""채점기 자체 검증: 채점기가 틀린 답을 틀렸다고 하는가. 모델 없이 돌린다.

golden set 의 정답 svg 를 일부러 망가뜨려 넣고 점수가 기대대로 움직이는지 본다. 기대와 다르면 실패로 끝난다.
  same        그대로                          → 모두 1.0
  drop_half   값 자리를 하나 걸러 지움         → 재현 ≈ 0.5, 정밀 1.0
  extra       값 자리를 빈 곳에 그만큼 더 넣음  → 재현 1.0, 정밀 ≈ 0.5
  nudge       값 자리를 3 만큼 옮김            → 재현 1.0 (조금 어긋난 것은 봐준다), 겹침만 하락
  far         값 자리를 쪽 밖 가까이로 모음     → 재현이 크게 하락
  relabel     항목명을 모두 바꿈               → 재현 1.0, 항목명 0  (이름이 달라도 자리가 맞으면 찾은 것)
  rekind      체크 칸을 값 칸으로              → 체크 칸 비율만큼 재현 하락
  half_text   <text> 를 하나 걸러 지움         → 값 자리 그대로, 문구 하락
  no_fields   값 자리를 모두 지움              → 유효하지 않음
  other_form  다른 항목의 정답                 → 모두 낮아야
  truncated   앞 절반만 / empty 빈 답          → 유효하지 않음, 0

실행: python -m formgen selftest [--items bench/golden_v1]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from . import svg

FIELD = re.compile(r"<rect\b[^>]*\bdata-field=[^>]*/>")
TEXT = re.compile(r"<text\b.*?</text>", re.S)
SHOW = ("field_recall", "field_precision", "label_acc", "iou_mean", "text_f1")


def _every_other(pattern, s):
    n = [0]

    def keep(m):
        n[0] += 1
        return "" if n[0] % 2 == 0 else m.group()
    return pattern.sub(keep, s)


def _attr(rect: str, name: str, value) -> str:
    return re.sub(rf'\b{name}="[^"]*"', f'{name}="{value}"', rect, count=1)


def cases(ref: str, other: str) -> dict:
    n = [0]

    def corner(m):   # 값 자리를 왼쪽 위 구석에 작은 상자로 줄지어 놓는다 (정답 자리와 겹치지 않게)
        n[0] += 1
        r = m.group()
        for name, value in (("x", 1 + 3 * (n[0] % 20)), ("y", 1 + 3 * (n[0] // 20)), ("width", 2), ("height", 2)):
            r = _attr(r, name, value)
        return r

    def extra(m):
        n[0] += 1
        return m.group() + _attr(corner(m), "data-field", f"extra{n[0]}")

    nudge = lambda m: _attr(m.group(), "x", float(re.search(r'\bx="([-\d.]+)"', m.group()).group(1)) - 3)
    return {"same": ref, "drop_half": _every_other(FIELD, ref), "extra": FIELD.sub(extra, ref), "nudge": FIELD.sub(nudge, ref),
            "far": FIELD.sub(corner, ref), "relabel": re.sub(r'data-label="[^"]*"', 'data-label="가나다라"', ref),
            "rekind": re.sub(r'data-type="checkbox" data-options="[^"]*"', 'data-type="text"', ref),
            "half_text": _every_other(TEXT, ref), "no_fields": FIELD.sub("", ref),
            "other_form": other, "truncated": ref[:len(ref) // 2], "empty": ""}


def expect(case: str, r: dict, ref_stats: dict) -> str:
    """기대와 다르면 그 까닭 (기대대로면 빈 글)."""
    rec, prec, lab, tf = r["field_recall"], r["field_precision"], r["label_acc"], r["text_f1"]
    n, checks = ref_stats["fields"], ref_stats["checkbox_groups"]
    ok = {"same": r["valid"] and rec == prec == tf == 1 and lab == 1,
          "drop_half": abs(rec - ((n + 1) // 2) / n) < 0.01 and prec == 1 and tf == 1,
          "extra": rec == 1 and abs(prec - 0.5) < 0.01,
          "nudge": rec == 1 and r["iou_mean"] < 1,
          "far": rec < 0.2,
          "relabel": rec == 1 and lab == 0,
          "rekind": abs(rec - (n - checks) / n) < 0.01,
          "half_text": rec == 1 and tf < 0.95,
          "no_fields": not r["valid"] and rec == 0,
          "other_form": rec < 0.5 and tf < 0.5,
          "truncated": not r["valid"] and rec == 0 and tf == 0,
          "empty": not r["valid"] and rec == 0 and tf == 0}[case]
    return "" if ok else "기대와 다름"


def run(items) -> dict:
    refs = {p.name: (p / "ref.svg").read_text(encoding="utf-8-sig") for p in sorted(Path(items).iterdir()) if (p / "ref.svg").is_file()}
    if len(refs) < 2:
        raise SystemExit(f"ref.svg 가 있는 항목이 둘 이상 필요합니다: {items}")
    names, rows = list(refs), []
    for k, name in enumerate(names):
        ref, other = refs[name], refs[names[(k + 1) % len(names)]]
        for case, value in cases(ref, other).items():
            r = svg.score(ref, value)
            rows.append({"id": name, "case": case, "valid": r["valid"], **{key: r[key] for key in SHOW}, "bad": expect(case, r, svg.stats(ref))})
    return {"rows": rows, "failed": [f"{r['id']}/{r['case']}" for r in rows if r["bad"]]}


def table(result: dict) -> str:
    """망가뜨린 방법마다 항목 전체의 평균."""
    fmt = lambda xs: "-" if not xs else f"{sum(xs) / len(xs):.2f}"
    lines = ["| 망가뜨린 방법 | 유효 | 값 자리 재현 | 값 자리 정밀 | 항목명 | 겹침 | 문구 | 기대대로 |", "|---|---|---|---|---|---|---|---|"]
    for case in dict.fromkeys(r["case"] for r in result["rows"]):
        rs = [r for r in result["rows"] if r["case"] == case]
        lines.append(f"| {case} | {sum(r['valid'] for r in rs)}/{len(rs)} | " + " | ".join(fmt([r[k] for r in rs if r[k] is not None]) for k in SHOW)
                     + f" | {sum(not r['bad'] for r in rs)}/{len(rs)} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m formgen selftest", description="svg 채점기 자체 검증 (모델 없이)")
    ap.add_argument("--items", default="bench/golden_v1")
    a = ap.parse_args(argv)
    result = run(a.items)
    print(table(result))
    if result["failed"]:
        raise SystemExit("실패: " + ", ".join(result["failed"]))
    print("통과")


if __name__ == "__main__":
    main()
