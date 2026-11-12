"""python -m formgen <명령> …

  make      이미지 한 장 → 값 자리를 표시한 html
  bench     평가 세트로 모델 하나를 잰다 (난이도별 통과율)
  score     정답 html 과 만든 html 을 채점한다
  tier      html 의 난이도를 본다
  selftest  채점기 자체 검증 (모델 없이)
"""
import json
import sys
from pathlib import Path


def _score(argv):
    from .score import passed, score_html
    if len(argv) != 2:
        raise SystemExit("python -m formgen score <정답 html> <만든 html>")
    s = score_html(Path(argv[0]).read_text(encoding="utf-8"), Path(argv[1]).read_text(encoding="utf-8"))
    s["pass"] = passed(s)
    print(json.dumps(s, ensure_ascii=False, indent=1))


def _tier(argv):
    from .difficulty import of_html
    for p in argv:
        print(p, json.dumps(of_html(Path(p).read_text(encoding="utf-8")), ensure_ascii=False))


def main():
    from . import bench, make, selftest, svg_cli
    commands = {"svg": svg_cli.main, "make": make.main, "bench": bench.main, "selftest": selftest.main, "score": _score, "tier": _tier}
    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        raise SystemExit(__doc__)
    commands[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
