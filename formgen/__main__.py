"""python -m formgen <명령> …   명령: selftest (채점기 자체 검증)"""
import sys

from . import selftest

COMMANDS = {"selftest": selftest.main}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        raise SystemExit(__doc__)
    COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
