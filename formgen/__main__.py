"""python -m formgen <명령> …

  make      이미지 한 장 → svg 서식                     make --config configs/x.json --name A --image x.png --out 폴더 [--rounds 2]
  bench     설정 파일의 모델들을 golden set 으로 잰다    bench configs/x.json [--only A B]
  compare   여러 모델의 결과를 한 표로                   compare runs/exp1/A runs/exp1/B …
  report    결과 폴더의 표를 다시 만든다 (모델 호출 없음)  report runs/exp1/A
  score     정답 svg 와 만든 svg 를 채점                 score ref.svg out.svg
  validate  svg 가 규격에 맞는지                         validate out.svg
  stats     svg 의 난이도 특징 세기                      stats ref.svg …
  render    svg → png (resvg-py 필요)                   render out.svg --out out.png [--font-file 글꼴.ttf]
  selftest  채점기 자체 검증 (모델 없이)                  selftest
"""
import json
import sys
from pathlib import Path


def _read(path):
    return Path(path).read_text(encoding="utf-8-sig")


def _show(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _score(argv):
    from . import svg
    if len(argv) != 2:
        raise SystemExit("python -m formgen score <정답 svg> <만든 svg>")
    _show(svg.score(_read(argv[0]), _read(argv[1])))


def _validate(argv):
    from . import svg
    result = svg.parse(_read(argv[0]))
    _show({k: result[k] for k in ("valid", "issues")} | {"fields": len(result["fields"]), "texts": len(result["texts"])})
    if not result["valid"]:
        raise SystemExit(1)


def _stats(argv):
    from . import svg
    for p in argv:
        print(p, json.dumps(svg.stats(_read(p)), ensure_ascii=False))


def _render(argv):
    import argparse
    from . import svg
    ap = argparse.ArgumentParser(prog="python -m formgen render")
    ap.add_argument("input")
    ap.add_argument("--out", required=True)
    ap.add_argument("--font-file", action="append", help="글꼴 파일. 없으면 시스템 글꼴")
    a = ap.parse_args(argv)
    _show(svg.render(_read(a.input), a.out, a.font_file))


def _report(argv):
    from . import bench
    print(bench.rereport(argv[0]))


def _compare(argv):
    from . import bench
    print(bench.compare(argv))


def main(argv=None):
    from . import bench, make, selftest
    commands = {"make": make.main, "bench": bench.main, "compare": _compare, "report": _report, "score": _score,
                "validate": _validate, "stats": _stats, "render": _render, "selftest": selftest.main}
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in commands or (len(argv) == 1 and argv[0] in ("compare", "report", "validate", "stats")):
        raise SystemExit(__doc__)
    commands[argv[0]](argv[1:])


if __name__ == "__main__":
    main()
