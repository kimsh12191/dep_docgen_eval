"""python -m tplgen <명령> …

  make     이미지 한 장 → 템플릿 꾸러미 (모델 + 셀프 고치기)   make --config c.json --name A --image x.png --out out/x
  render   꾸러미 + 값 → 이미지 + 라벨                        render out/x/final --data my.json --out gen/0001
  vary     꾸러미에 임의 값을 넣어 여러 장                     vary out/x/final --n 20 --out gen/
  check    꾸러미가 쓸 만한지 돌려 보고 잰다                    check out/x/final --image x.png
  bench    여러 모델 × 여러 이미지 비교                        bench c.json [--only A B]
"""
import sys


def main(argv=None):
    from . import bench, check, gen, make
    commands = {"make": make.main, "render": gen.render_main, "vary": gen.vary_main, "check": check.main, "bench": bench.main}
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in commands:
        raise SystemExit(__doc__)
    commands[argv[0]](argv[1:])


if __name__ == "__main__":
    main()
