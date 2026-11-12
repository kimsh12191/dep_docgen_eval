"""채점기 자체 검증 (가설: svg 채점기가 틀린 답을 틀렸다고 한다). 모델 없이 돌린다.

평가 항목의 정답 svg 를 일부러 망가뜨려 넣고, 점수가 기대한 대로 움직이는지 본다. 기대와 다르면 실패로 끝난다.
  same        그대로                       → 모든 점수 1.0, 유효
  drop_half   값 자리를 하나 걸러 지움      → 값 자리 F1 ≈ 0.67 (재현 절반, 정밀 1), 문구 1.0
  shift_small 값 자리를 5 만큼 옮김         → 값 자리·위치 그대로 1.0, 겹침만 조금 하락
  shift_far   값 자리를 쪽 너비의 30% 옮김   → 값 자리 1.0, 위치 점수는 크게 하락
  retype      종류 text → amount           → text 값 자리 비율만큼 값 자리 점수 하락
  half_text   <text> 를 하나 걸러 지움      → 값 자리 그대로, 문구 재현 하락
  no_text     <text> 를 모두 지움           → 유효하지 않음 (no_editable_text), 문구 0
  no_fields   값 자리 표시를 모두 지움      → 유효하지 않음 (no_fields), 값 자리 0
  other_form  다른 항목의 정답을 넣음       → 모든 점수가 낮아야 (변별력)
  truncated   앞 절반만                    → 유효하지 않음, 0
  empty       빈 답                        → 유효하지 않음, 0

실행: python -m formgen selftest --items bench/official_pilot_v1 --out results/selftest_svg
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from . import svg

FIELD = re.compile(r"<rect\b[^>]*\bdata-field=[^>]*/>")
TEXT = re.compile(r"<text\b.*?</text>", re.S)
SHOW = ("valid", "typed_field_f1", "located_field_f1", "field_iou_mean", "text_f1", "text_r")


def _every_other(pattern, s):
    n = [0]

    def keep(m):
        n[0] += 1
        return "" if n[0] % 2 == 0 else m.group()
    return pattern.sub(keep, s)


def _shift(s, dx):
    move = lambda m: re.sub(r'\bx="([-\d.]+)"', lambda q: f'x="{float(q.group(1)) + dx}"', m.group(), count=1)
    return FIELD.sub(move, s)


def cases(ref: str, other: str) -> dict:
    width = svg.parse(ref)["width"]
    fields = svg.parse(ref)["fields"]
    room = min(width - f["bbox"][0] - f["bbox"][2] for f in fields)   # 쪽 밖으로 나가지 않게 왼쪽으로 옮긴다
    far = -0.3 * width if min(f["bbox"][0] for f in fields) > 0.3 * width else (0.3 * width if room > 0.3 * width else None)
    out = {"same": ref, "drop_half": _every_other(FIELD, ref), "shift_small": _shift(ref, -5),
           "retype": ref.replace('data-type="text"', 'data-type="amount"'),
           "half_text": _every_other(TEXT, ref), "no_text": TEXT.sub("", ref), "no_fields": FIELD.sub("", ref),
           "other_form": other, "truncated": ref[:len(ref) // 2], "empty": ""}
    if far is not None:
        out["shift_far"] = _shift(ref, far)
    return out


def expect(case: str, r: dict, ref_stats: dict) -> list[str]:
    """기대와 다른 점 목록 (비면 통과)."""
    bad = []
    need = lambda ok, why: bad.append(why) if not ok else None
    f, loc, iou, tf, tr = (r[k] for k in SHOW[1:])
    n = ref_stats["fields"]
    if case == "same":
        need(r["valid"] and f == loc == iou == tf == 1, "그대로인데 1.0 이 아님")
    elif case == "drop_half":
        kept = (n + 1) // 2
        need(abs(f - 2 * kept / (n + kept)) < 1e-3 and tf == 1, "값 자리 절반: F1 이 기대와 다름")
    elif case == "shift_small":
        need(f == 1 and loc == 1 and iou < 1, "조금 옮김: 값 자리·위치는 1.0, 겹침은 1 미만이어야")
    elif case == "shift_far":
        need(f == 1 and loc < 0.5, "멀리 옮김: 위치 점수가 크게 떨어져야")
    elif case == "retype":
        text_share = ref_stats["types"].get("text", 0) / n
        need(abs(f - (1 - text_share)) < 1e-3, "종류 바꿈: 바꾼 비율만큼 떨어져야")
    elif case == "half_text":
        need(f == 1 and tr < 0.9 and tf < 0.95, "문구 절반: 값 자리 그대로, 문구 하락")
    elif case == "no_text":
        need(not r["valid"] and tf == 0, "문구 없음: 유효하지 않아야")
    elif case == "no_fields":
        need(not r["valid"] and f == 0, "값 자리 없음: 유효하지 않아야")
    elif case == "other_form":
        need(f < 0.5 and loc < 0.3 and tf < 0.5, "다른 서식: 점수가 낮아야")
    elif case in ("truncated", "empty"):
        need(not r["valid"] and f == 0 and tf == 0, "잘림·빈 답: 유효하지 않고 0 이어야")
    return bad


def run(items: str | Path) -> dict:
    items = Path(items)
    refs = {p.name: (p / "ref.svg").read_text(encoding="utf-8-sig") for p in sorted(items.iterdir()) if (p / "ref.svg").is_file()}
    if len(refs) < 2:
        raise SystemExit(f"ref.svg 가 있는 항목이 둘 이상 필요합니다: {items}")
    names, rows, failed = list(refs), [], []
    for k, name in enumerate(names):
        ref, other = refs[name], refs[names[(k + 1) % len(names)]]
        ref_stats = svg.stats(ref)
        for case, value in cases(ref, other).items():
            r = svg.score(ref, value)
            bad = expect(case, r, ref_stats)
            rows.append({"id": name, "case": case, **{key: r[key] for key in SHOW}, "issues": r["issues"], "unexpected": bad})
            failed += [f"{name}/{case}: {b}" for b in bad]
    return {"version": svg.VERSION, "items": str(items), "n_items": len(names), "rows": rows, "failed": failed, "ok": not failed}


def table(result: dict) -> str:
    lines = ["| 항목 | 망가뜨린 방법 | 유효 | 값 자리 | 값 자리+위치 | 겹침 | 문구 F1 | 문구 재현 | 기대대로 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in result["rows"]:
        lines.append(f"| {r['id']} | {r['case']} | {'예' if r['valid'] else '아니오'} | " + " | ".join(f"{r[k]:.2f}" for k in SHOW[1:])
                     + f" | {'예' if not r['unexpected'] else '아니오: ' + '; '.join(r['unexpected'])} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m formgen selftest", description="svg 채점기 자체 검증 (모델 없이)")
    ap.add_argument("--items", default="bench/official_pilot_v1")
    ap.add_argument("--out", default=None, help="selftest.json · selftest.md 를 쓸 폴더")
    a = ap.parse_args(argv)
    result = run(a.items)
    text = table(result)
    if a.out:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "selftest.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "selftest.md").write_text(f"# svg 채점기 자체 검증 ({result['version']}, {result['items']})\n\n" + text, encoding="utf-8")
    print(text)
    print("통과" if result["ok"] else "실패:\n" + "\n".join(result["failed"]))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
