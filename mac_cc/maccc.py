#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mac Crap Cleaner (MacCC) — псевдографический инструмент обслуживания macOS.

Запуск:
    python3 maccc.py                  # псевдографическое меню
    python3 maccc.py --help           # список субкоманд
    python3 maccc.py info
    python3 maccc.py scan --profile dev
    python3 maccc.py orphans --clean -y
    python3 maccc.py startup dead

Требования: macOS 11+, Python 3.8+ (системный python3 подходит),
никаких сторонних библиотек.
"""

from __future__ import annotations

import os
import sys

# Позволяет запускать скрипт из любой директории без установки пакета.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _guard_python_version() -> None:
    if sys.version_info < (3, 8):
        sys.stderr.write(
            "Нужен Python 3.8 или новее, найден "
            f"{sys.version.split()[0]}.\n"
            "В macOS его ставит Xcode Command Line Tools: xcode-select --install\n")
        raise SystemExit(2)


def main() -> int:
    _guard_python_version()
    from mactweaker.cli import main as cli_main
    return cli_main()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.stdout.write("\033[0m\033[?25l\033[?1049l\nПрервано.\n")
        sys.exit(130)
    except BrokenPipeError:
        sys.exit(0)
