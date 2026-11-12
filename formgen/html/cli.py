"""python -m formgen html <명령> …     (예전 html 길 — 기록·회귀 확인용. 새 평가는 svg 를 쓴다)

  make      이미지 한 장 → 값 자리를 표시한 html
  bench     html 평가 세트(bench/roundtrip_v0)로 모델 하나를 잰다
  score     정답 html 과 만든 html 을 채점한다
  tier      html 의 난이도를 본다 (difficulty-v1)
  selftest  html 채점기 자체 검증
  evaluate  V2 진단 (선택: 브라우저)   → docs/legacy/EVALUATION_V2.md
"""
import json
import sys
from pathlib import Path


def _score(argv):
    from .score import passed, score_html
    if len(argv) != 2:
        raise SystemExit("python -m formgen html score <정답 html> <만든 html>")
    s = score_html(Path(argv[0]).read_text(encoding="utf-8"), Path(argv[1]).read_text(encoding="utf-8"))
    s["pass"] = passed(s)
    print(json.dumps(s, ensure_ascii=False, indent=1))


def _tier(argv):
    from .difficulty import of_html
    for p in argv:
        print(p, json.dumps(of_html(Path(p).read_text(encoding="utf-8")), ensure_ascii=False))


def _evaluate(argv):
    import runpy
    sys.argv = ["python -m formgen html evaluate", *argv]
    runpy.run_module("formgen.html.evaluate", run_name="__main__")


def main(argv):
    from . import bench, make, selftest
    commands = {"make": make.main, "bench": bench.main, "selftest": selftest.main, "score": _score, "tier": _tier, "evaluate": _evaluate}
    if not argv or argv[0] not in commands:
        raise SystemExit(__doc__)
    commands[argv[0]](argv[1:])
