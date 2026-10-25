#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Собирает проект в ОДИН исполняемый файл dist/maccc_bundle.py.

Внутри — zipapp (PEP 441) в base64: Python умеет импортировать модули прямо
из zip-архива, поэтому никакой установки пакета и никаких временных файлов
не требуется. Скачали один файл → запустили.

    python3 build_bundle.py                # → dist/mac_tweaker_bundle.py
    python3 dist/mac_tweaker_bundle.py     # проверка
"""

from __future__ import annotations

import base64
import io
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG = "mactweaker"
OUT_DIR = ROOT / "dist"
OUT = OUT_DIR / "maccc_bundle.py"

STUB = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mac Crap Cleaner (MacCC) — single-file bundle (все модули внутри, base64+zip).

Собран автоматически скриптом build_bundle.py из пакета `{pkg}`.
Никакой установки: скачали один файл — запустили.

    python3 {out}                # псевдографическое меню
    python3 {out} --help         # субкоманды
"""
import base64 as _b64
import importlib.abc as _abc
import importlib.machinery as _mach
import io as _io
import sys as _sys
import zipfile as _zip

if _sys.version_info < (3, 8):
    _sys.stderr.write("Нужен Python 3.8+ (найден %s)\\n" % _sys.version.split()[0])
    raise SystemExit(2)

_ZIP = _b64.b64decode("""
{payload}
""")

_PKG = "{pkg}"


class _BundleLoader(_abc.Loader):
    def __init__(self, data):
        self._data = data

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        name = getattr(module, "__file__", None) or getattr(
            module, "__name__", "<bundle>")
        exec(compile(self._data, str(name), "exec"), module.__dict__)


class _BundleFinder(_abc.MetaPathFinder):
    """Импортер, читающий модули из zip-архива в памяти (без временных файлов)."""

    def __init__(self, archive):
        self._z = archive
        self._cache = {{}}
        self._packages = set()
        for name in archive.namelist():
            if name.endswith("/"):
                self._packages.add(name[:-1].replace("/", "."))
            elif name.endswith(".py"):
                mod = name[:-3].replace("/", ".")
                self._packages.add(mod.rpartition(".")[0])

    def find_spec(self, fullname, path=None, target=None):
        as_pkg = fullname + "/__init__.py"
        as_mod = fullname.replace(".", "/") + ".py"
        if as_pkg in self._z.namelist() or fullname in self._packages \
                and as_pkg not in self._z.namelist() and as_mod not in self._z.namelist():
            init = self._z.read(as_pkg) if as_pkg in self._z.namelist() else b""
            return _mach.ModuleSpec(fullname, _BundleLoader(init),
                                    is_package=True,
                                    origin="{out}!" + as_pkg)
        if as_mod in self._z.namelist():
            if fullname not in self._cache:
                self._cache[fullname] = self._z.read(as_mod)
            return _mach.ModuleSpec(fullname,
                                    _BundleLoader(self._cache[fullname]),
                                    origin="{out}!" + as_mod)
        return None


if __name__ == "__main__":
    _sys.meta_path.insert(0, _BundleFinder(_zip.ZipFile(_io.BytesIO(_ZIP))))
    from mactweaker.cli import main as _main
    try:
        raise SystemExit(_main())
    except KeyboardInterrupt:
        _sys.stdout.write("\\033[0m\\033[?25l\\033[?1049l\\nПрервано.\\n")
        raise SystemExit(130)
    except BrokenPipeError:
        raise SystemExit(0)
'''


def build() -> int:
    buf = io.BytesIO()
    files = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(ROOT / "maccc.py", "__main__.py")
        for p in sorted((ROOT / PKG).glob("*.py")):
            zf.write(p, f"{PKG}/{p.name}")
            files += 1
        # вложенные пакеты (если появятся)
        for p in sorted((ROOT / PKG).rglob("*.py")):
            rel = p.relative_to(ROOT)
            name = str(rel).replace(os.sep, "/")
            if name not in zf.namelist():
                zf.write(p, name)
                files += 1
    payload = base64.b64encode(buf.getvalue()).decode("ascii")
    wrapped = "\n".join(
        payload[i:i + 96] for i in range(0, len(payload), 96))
    text = STUB.format(pkg=PKG, out=OUT.name, payload=wrapped)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    OUT.chmod(0o755)
    size = OUT.stat().st_size
    print(f"  собрано {OUT.relative_to(ROOT)}: {size // 1024} КБ, "
          f"{files} модулей, payload {len(payload) // 1024} КБ base64")
    return 0


if __name__ == "__main__":
    sys.exit(build())
