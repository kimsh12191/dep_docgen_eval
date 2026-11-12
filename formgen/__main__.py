"""python -m formgen <svg|harness|make|bench|score|tier|selftest> ..."""
import json
import sys
from pathlib import Path


def _score(argv):
    from .score import passed, score_html
    if len(argv)!=2:raise SystemExit('python -m formgen score <reference html> <predicted html>')
    s=score_html(Path(argv[0]).read_text(encoding='utf-8'),Path(argv[1]).read_text(encoding='utf-8'))
    s['pass']=passed(s)
    print(json.dumps(s,ensure_ascii=False,indent=1))


def _tier(argv):
    from .difficulty import of_html
    for p in argv:
        print(p,json.dumps(of_html(Path(p).read_text(encoding='utf-8')),ensure_ascii=False))


def main():
    if len(sys.argv)<2:raise SystemExit(__doc__)
    cmd=sys.argv[1]
    if cmd=='harness':
        from . import harness
        return harness.main(sys.argv[2:])
    if cmd=='svg':
        from . import svg_cli
        return svg_cli.main(sys.argv[2:])
    if cmd=='score':return _score(sys.argv[2:])
    if cmd=='tier':return _tier(sys.argv[2:])
    if cmd=='make':
        from . import make
        return make.main(sys.argv[2:])
    if cmd=='bench':
        from . import bench
        return bench.main(sys.argv[2:])
    if cmd=='selftest':
        from . import selftest
        return selftest.main(sys.argv[2:])
    raise SystemExit(__doc__)


if __name__=='__main__':main()
