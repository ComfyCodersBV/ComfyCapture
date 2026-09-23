from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from browsertests import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="browsertests", description="Replay recorded browser tests.")
    parser.add_argument("--version", action="version", version=f"browsertests {__version__}")
    parser.add_subparsers(dest="command")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.print_help()
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
