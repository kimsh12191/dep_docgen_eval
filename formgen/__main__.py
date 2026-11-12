"""python -m formgen <명령> …        (svg 서식 — 지금 쓰는 길)

  make      이미지 한 장 → 값 자리를 표시한 svg 서식            make --image x.png --endpoint URL --model NAME --out 폴더
  bench     평가 세트로 모델 하나를 잰다 (난이도별 통과율 표)    bench --items 폴더 --endpoint URL --model NAME --out 폴더
  report    bench 결과 폴더의 표를 다시 만든다 (모델 호출 없음)  report 결과폴더
  score     정답 svg 와 만든 svg 를 채점한다                    score ref.svg out.svg [--out score.json]
  validate  svg 가 규격(svg-v1)에 맞는지 본다                   validate out.svg
  stats     svg 에서 난이도 특징을 센다 (수동 분류 보조)         stats ref.svg …
  render    svg → png (resvg-py 필요, 브라우저 불필요)          render out.svg --out out.png [--font-file 글꼴.ttf]
  selftest  채점기 자체 검증 (모델 없이)                        selftest [--items 폴더] [--out 폴더]

  html …    예전 html 길 (기록용): html make | bench | score | tier | selftest | evaluate
  svg …     위 명령과 같다 (예전 문서의 `python -m formgen svg make …` 를 위해 남김)
"""
import argparse
import json
import sys
from pathlib import Path


def _read(path):
    return Path(path).read_text(encoding="utf-8-sig")


def _show(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _score(argv):
    from . import svg
    ap = argparse.ArgumentParser(prog="python -m formgen score")
    ap.add_argument("ref")
    ap.add_argument("pred")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    result = svg.score(_read(a.ref), _read(a.pred))
    if a.out:
        Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    _show(result)


def _validate(argv):
    from . import svg
    ap = argparse.ArgumentParser(prog="python -m formgen validate")
    ap.add_argument("input")
    a = ap.parse_args(argv)
    result = svg.parse(_read(a.input))
    _show(result)
    if not result["valid"]:
        raise SystemExit(1)


def _stats(argv):
    from . import svg
    for p in argv:
        print(p, json.dumps(svg.stats(_read(p)), ensure_ascii=False))


def _render(argv):
    from . import svg
    ap = argparse.ArgumentParser(prog="python -m formgen render")
    ap.add_argument("input")
    ap.add_argument("--out", required=True)
    ap.add_argument("--font-file", action="append", help="글꼴 파일 (여러 번 줄 수 있다). 없으면 시스템 글꼴 = 재현 안 됨으로 기록")
    a = ap.parse_args(argv)
    result = svg.render(_read(a.input), a.out, a.font_file)
    Path(str(a.out) + ".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    _show(result)


def _report(argv):
    from . import bench
    if len(argv) != 1:
        raise SystemExit("python -m formgen report <bench 결과 폴더>")
    print(bench.rereport(argv[0]))


def _html(argv):
    from .html import cli
    cli.main(argv)


def main(argv=None):
    from . import bench, make, selftest
    commands = {"make": make.main, "bench": bench.main, "report": _report, "score": _score, "validate": _validate,
                "stats": _stats, "render": _render, "selftest": selftest.main, "html": _html}
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["svg"]:
        argv = argv[1:]
    if not argv or argv[0] not in commands:
        raise SystemExit(__doc__)
    commands[argv[0]](argv[1:])


if __name__ == "__main__":
    main()
