"""
mactweaker.safety — общие примитивы безопасности и файловые утилиты.

Здесь живут:
  * безопасные обёртки над stat/lstat (macOS DataVault/SIP бросает Errno 1);
  * белый/чёрный списки путей и проверка is_safe();
  * подсчёт размеров, человекочитаемый вывод;
  * удаление через Корзину (обратимо!) и журнал действий с откатом.

Все пути передаются через объект Paths (см. system.py), чтобы код можно было
тестировать на фейковом «маковском» дереве каталогов.
"""

from __future__ import annotations

import errno
import fnmatch
import glob
import json
import os
import shutil
import stat as stat_module
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------- #
#  Безопасные проверки путей
#
#  В macOS часть каталогов (*.datavault, зоны TCC, некоторые /Library/Caches)
#  запрещает даже lstat(): OSError [Errno 1] Operation not permitted.
#  Любой stat ниже обёрнут, чтобы сканер пропускал их, а не падал.
# --------------------------------------------------------------------------- #


def safe_lstat(p) -> Optional[os.stat_result]:
    try:
        return os.lstat(p)
    except (OSError, ValueError):
        return None


def safe_stat(p) -> Optional[os.stat_result]:
    try:
        return os.stat(p)
    except (OSError, ValueError):
        return None


def safe_exists(p) -> bool:
    return safe_lstat(p) is not None


def safe_islink(p) -> bool:
    st = safe_lstat(p)
    return bool(st and stat_module.S_ISLNK(st.st_mode))


def safe_isdir(p) -> bool:
    try:
        return os.path.isdir(p)
    except (OSError, ValueError):
        return False


def safe_isfile(p) -> bool:
    try:
        return os.path.isfile(p)
    except (OSError, ValueError):
        return False


def safe_scandir(p) -> List[os.DirEntry]:
    try:
        with os.scandir(p) as it:
            return list(it)
    except (OSError, ValueError):
        return []


def is_datavault(p: Path) -> bool:
    """macOS DataVault — защищённый SIP/TCC каталог: чистить нельзя и бесполезно."""
    return "datavault" in Path(p).name.lower()


def needs_root(path: Path) -> bool:
    try:
        return not os.access(path, os.W_OK)
    except OSError:
        return True


# --------------------------------------------------------------------------- #
#  Размеры и формат
# --------------------------------------------------------------------------- #

def dir_size(path, follow_symlinks: bool = False, budget: int = 400000) -> Tuple[int, int]:
    """(байты, число файлов). Не следует за симлинками, не падает на SIP-путях."""
    p = Path(path)
    st = safe_lstat(p)
    if st is None:
        return 0, 0
    if stat_module.S_ISLNK(st.st_mode):
        return 0, 1
    if stat_module.S_ISREG(st.st_mode):
        return st.st_size, 1
    if not stat_module.S_ISDIR(st.st_mode):
        return 0, 0

    total = 0
    count = 0
    seen: set = set()
    stack = [p]
    while stack and budget > 0:
        cur = stack.pop()
        try:
            real = os.path.realpath(cur)
        except OSError:
            continue
        if real in seen:
            continue
        seen.add(real)
        for e in safe_scandir(cur):
            budget -= 1
            if budget <= 0:
                break
            try:
                if e.is_symlink():
                    count += 1
                    continue
                if e.is_dir(follow_symlinks=follow_symlinks):
                    stack.append(Path(e.path))
                else:
                    total += e.stat(follow_symlinks=follow_symlinks).st_size
                    count += 1
            except OSError:
                continue
    return total, count


def newest_mtime(path) -> float:
    """Самая свежая mtime внутри дерева (для оценки «давно не использовалось»)."""
    p = Path(path)
    st = safe_lstat(p)
    latest = st.st_mtime if st else 0.0
    stack = [p]
    budget = 20000
    seen: set = set()
    while stack and budget > 0:
        cur = stack.pop()
        try:
            real = os.path.realpath(cur)
        except OSError:
            continue
        if real in seen:
            continue
        seen.add(real)
        for e in safe_scandir(cur):
            budget -= 1
            try:
                if e.is_symlink():
                    continue
                if e.is_dir(follow_symlinks=False):
                    stack.append(Path(e.path))
                    continue
                mt = e.stat(follow_symlinks=False).st_mtime
                if mt > latest:
                    latest = mt
            except OSError:
                continue
    return latest


def human(n: float) -> str:
    """Байты → человекочитаемая строка; единицы зависят от языка."""
    from .i18n import get_lang
    units = ("B", "KB", "MB", "GB", "TB") if get_lang() == "en" \
        else ("Б", "КБ", "МБ", "ГБ", "ТБ")
    n = float(n)
    last = units[-1]
    for unit in units:
        if abs(n) < 1024.0 or unit == last:
            return f"{int(n)} {unit}" if unit == units[0] else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} {last}"


def human_signed(n: float) -> str:
    return ("−" if n > 0 else "+") + human(abs(n))


def ago(ts: float) -> str:
    """«3 дн. назад» / «7 мес. назад»."""
    if not ts:
        return "—"
    d = (time.time() - ts) / 86400.0
    if d < 0:
        return "только что"
    if d < 1:
        h = d * 24
        return f"{int(h)} ч. назад" if h >= 1 else "меньше часа назад"
    if d < 31:
        return f"{int(d)} дн. назад"
    if d < 365:
        return f"{int(d / 30.4)} мес. назад"
    return f"{d / 365.25:.1f} г. назад"


# --------------------------------------------------------------------------- #
#  Защита путей
# --------------------------------------------------------------------------- #

#: Имена подкаталогов Application Support, которые можно чистить (кэш-подобные).
APP_SUPPORT_ALLOWED_LEAFS = frozenset({
    "cache", "caches", "cacheddata", "cachedextensionvsixs", "gpucache",
    "code cache", "shadercache", "grshadercache", "logs", "dawnwebgpucache",
    "dawngraphitecache", "service worker/cachestorage", "crashpad",
})

#: Приложения, внутри Application Support у которых разрешено чистить кэш.
APP_SUPPORT_ALLOWED_APPS = (
    "Code", "Code - Insiders", "VSCodium", "Cursor", "Google/Chrome",
    "Chromium", "Microsoft Edge", "BraveSoftware/Brave-Browser",
    "Arc/User Data", "Vivaldi", "com.operasoftware.Opera",
)


@dataclass
class Paths:
    """Все значимые пути системы. Создаётся через Paths.detect()."""

    home: Path
    lib: Path                    # ~/Library
    app_support: Path            # ~/Library/Application Support
    sysroot: Path = Path("/")    # "/" в бою, fakeroot в тестах
    extra_app_dirs: Tuple[Path, ...] = ()

    @classmethod
    def detect(cls, home: Optional[Path] = None, sysroot: Optional[Path] = None) -> "Paths":
        """Определить пути.

        Приоритет: явные аргументы → переменные окружения MACTWEAKER_HOME /
        MACTWEAKER_SYSROOT (используются тестами и для «песочничного» запуска)
        → реальный домашний каталог и "/".
        """
        h = Path(home) if home else Path(
            os.environ.get("MACTWEAKER_HOME") or os.path.expanduser("~"))
        sr = Path(sysroot) if sysroot else Path(
            os.environ.get("MACTWEAKER_SYSROOT") or "/")
        lib = h / "Library"
        app_dirs = tuple(
            p for p in (
                sr / "Applications",
                h / "Applications",
                sr / "System" / "Applications",
                sr / "System" / "Applications" / "Utilities",
            )
        )
        return cls(home=h, lib=lib, app_support=lib / "Application Support",
                   sysroot=sr, extra_app_dirs=app_dirs)

    # --- производные ---
    @property
    def sys_lib(self) -> Path:
        return self.sysroot / "Library"

    @property
    def system_library(self) -> Path:
        return self.sysroot / "System" / "Library"

    @property
    def trash(self) -> Path:
        return self.home / ".Trash"

    @property
    def downloads(self) -> Path:
        return self.home / "Downloads"

    @property
    def state_dir(self) -> Path:
        """Каталог состояния тулзы: бэкапы, журнал, кэш."""
        return self.home / ".mac_tweaker"

    def protected_prefixes(self) -> Tuple[str, ...]:
        h, lib, sr = self.home, self.lib, self.sysroot
        return tuple(str(p) for p in (
            h / "Documents", h / "Desktop", h / "Pictures", h / "Music",
            h / "Movies", h / "Public", h / "Sites",
            lib / "Application Support", lib / "Containers",
            lib / "Group Containers", lib / "Keychains", lib / "Mail",
            lib / "Messages", lib / "Calendars", lib / "Contacts",
            lib / "Photos", lib / "Mobile Documents", lib / "AddressBook",
            h / ".ssh", h / ".gnupg", h / ".aws", h / ".config", h / ".azure",
            h / ".kube", h / ".docker", h / ".gem",
            sr / "System", sr / "usr", sr / "bin", sr / "sbin", sr / "etc",
            sr / "private" / "etc", sr / "private" / "var" / "db",
            sr / "Users" / "Shared", sr / "Library" / "Keychains",
            self.state_dir,
        ))

    def forbidden_exact(self) -> frozenset:
        h, lib = self.home, self.lib
        return frozenset({
            "", "/", str(h), str(lib), str(h / "Library"),
            str(h / ".Trash"), str(lib / "Caches"), str(lib / "Logs"),
            str(self.sysroot / "Library"), str(self.sysroot / "Library" / "Caches"),
        })

    def short(self, p) -> str:
        s = str(p)
        if s.startswith(str(self.home)):
            s = "~" + s[len(str(self.home)):]
        if s.startswith(str(self.sysroot)) and str(self.sysroot) != "/":
            s = "<sysroot>" + s[len(str(self.sysroot)):]
        return s


def _app_support_cache_ok(s: str, paths: Paths) -> bool:
    """Разрешено ли чистить этот путь внутри ~/Library/Application Support.

    Разрешаем только известные приложения (APP_SUPPORT_ALLOWED_APPS) и только
    если в пути встречается кэш-подобный сегмент (APP_SUPPORT_ALLOWED_LEAFS):
        .../Code/CachedData/xyz   → можно
        .../Code/User/settings.json → нельзя
    """
    base = str(paths.app_support) + os.sep
    if not s.startswith(base):
        return False
    low = s[len(base):].lower()
    for app in APP_SUPPORT_ALLOWED_APPS:
        a = app.lower()
        if not (low == a or low.startswith(a + "/")):
            continue
        rest = [x for x in low[len(a):].split("/") if x]
        if not rest:
            continue
        if any(part in APP_SUPPORT_ALLOWED_LEAFS for part in rest):
            return True
        joined = "/".join(rest[-2:])
        if joined in APP_SUPPORT_ALLOWED_LEAFS:
            return True
    return False


def is_safe(p, paths: Paths) -> bool:
    """Главный предохранитель: можно ли вообще трогать этот путь."""
    try:
        s = str(Path(os.path.abspath(os.path.expanduser(str(p)))))
    except (OSError, ValueError):
        return False

    if s.rstrip("/") in paths.forbidden_exact():
        return False
    if len([x for x in s.split(os.sep) if x]) < 2:
        return False
    if is_datavault(Path(s)):
        return False
    if _app_support_cache_ok(s, paths):
        return True
    for prot in paths.protected_prefixes():
        if s == prot or s.startswith(prot + os.sep):
            return False
    return True


#: Каталоги, в которые сканеры не заходят (но удалять их целиком тоже нельзя).
NO_TRAVERSE = ("Documents", "Pictures", "Music", "Movies", "Public", "Sites",
               ".Trash", "Library", ".ssh", ".gnupg", "node_modules", ".git")


def is_traversable(p, paths: Paths) -> bool:
    """Можно ли ЗАЙТИ в каталог при сканировании (не то же, что удалить)."""
    try:
        s = str(Path(os.path.abspath(os.path.expanduser(str(p)))))
    except (OSError, ValueError):
        return False
    if s.rstrip("/") in paths.forbidden_exact():
        return False
    name = Path(s).name
    if name in NO_TRAVERSE or is_datavault(Path(s)):
        return False
    # защищённые префиксы: заходить можно только в разрешённые кэш-зоны
    for prot in paths.protected_prefixes():
        if s == prot or s.startswith(prot + os.sep):
            return _app_support_cache_ok(s, paths)
    return True


def matches_exclude(p: Path, excludes: Sequence[str]) -> bool:
    if not excludes:
        return False
    s = str(p)
    return any(fnmatch.fnmatch(s, pat) or fnmatch.fnmatch(p.name, pat)
               or fnmatch.fnmatch(s.lower(), pat.lower()) for pat in excludes)


def expand_glob(pattern: str, paths: Paths,
                excludes: Sequence[str] = ()) -> List[Path]:
    """Раскрыть glob, отбросив недоступные, защищённые и DataVault-пути."""
    out: List[Path] = []
    try:
        matches = glob.glob(pattern)
    except OSError:
        return out
    for raw in matches:
        p = Path(raw)
        try:
            if is_datavault(p) or matches_exclude(p, excludes):
                continue
            if not is_safe(p, paths):
                continue
            out.append(p)
        except Exception:  # noqa: BLE001 — лучше пропустить, чем упасть
            continue
    return out


# --------------------------------------------------------------------------- #
#  Внешние команды
# --------------------------------------------------------------------------- #

def run(cmd: Sequence[str], timeout: int = 900) -> Tuple[int, str]:
    try:
        p = subprocess.run(list(cmd), stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "").strip()
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def sudo_ok(non_interactive: bool = True) -> bool:
    code, _ = run(["sudo", "-n", "true"] if non_interactive else ["sudo", "-v"])
    return code == 0


# --------------------------------------------------------------------------- #
#  Удаление: Корзина по умолчанию
# --------------------------------------------------------------------------- #

class Deleter:
    """Удаляет файлы — по умолчанию в Корзину (обратимо).

    mode="trash"  — через Finder AppleScript, иначе mv в ~/.Trash;
    mode="hard"   — rm -rf (с sudo при необходимости);
    mode="dry"    — ничего не делать.
    """

    def __init__(self, paths: Paths, mode: str = "trash", use_sudo: bool = False,
                 journal: Optional["Journal"] = None):
        self.paths = paths
        self.mode = mode
        self.use_sudo = use_sudo
        self.journal = journal
        self._finder_ok: Optional[bool] = None

    # -- публичное API --
    def delete(self, targets: Sequence[Path]) -> Tuple[int, List[Path]]:
        """Возвращает (освобождено байт, список неудач)."""
        freed = 0
        failed: List[Path] = []
        targets = [Path(t) for t in targets if safe_exists(Path(t))]
        if not targets or self.mode == "dry":
            return 0, []

        if self.mode == "trash":
            # размеры считаем ДО удаления — иначе после move получатся нули
            sizes = {str(p): dir_size(p)[0] for p in targets}
            ok_paths = self._to_trash(targets)
            ok_set = {str(p) for p in ok_paths}
            for p in targets:
                if str(p) in ok_set:
                    freed += sizes.get(str(p), 0)
                else:
                    failed.append(p)
            return freed, failed

        for p in targets:
            size = dir_size(p)[0]
            try:
                if self._rm(p):
                    freed += size
                else:
                    failed.append(p)
            except (PermissionError, OSError):
                failed.append(p)
        return freed, failed

    # -- внутреннее --
    def _to_trash(self, targets: Sequence[Path]) -> List[Path]:
        ok: List[Path] = []
        if self._finder_available():
            # Finder умеет принимать список; ограничим пачками по 60 элементов
            for i in range(0, len(targets), 60):
                chunk = targets[i:i + 60]
                items = ", ".join(
                    'POSIX file "%s"' % str(p).replace('"', '\\"') for p in chunk)
                code, _ = run(["osascript", "-e",
                               f"tell application \"Finder\" to delete {{{items}}}"],
                              timeout=300)
                if code == 0:
                    ok.extend(p for p in chunk if not safe_exists(p))
                else:
                    self._finder_ok = False
                    break
        # запасной путь: mv в ~/.Trash (сохраняем уникальность имён)
        trash = self.paths.trash
        for p in targets:
            if p in ok:
                continue
            try:
                trash.mkdir(parents=True, exist_ok=True)
                dest = trash / p.name
                n = 1
                while safe_exists(dest):
                    dest = trash / f"{p.stem} {n}{p.suffix}"
                    n += 1
                shutil.move(str(p), str(dest))
                if not safe_exists(p):
                    ok.append(p)
            except (OSError, shutil.Error):
                if self.use_sudo:
                    code, _ = run(["sudo", "-n", "mv", "--", str(p), str(trash)])
                    if code == 0 and not safe_exists(p):
                        ok.append(p)
        if self.journal:
            for p in ok:
                self.journal.add("trash", str(p))
        return ok

    def _rm(self, p: Path) -> bool:
        try:
            if safe_islink(p) or safe_isfile(p):
                p.unlink()
            elif safe_isdir(p):
                self._rmtree(p)
            else:
                return True
            gone = not safe_exists(p)
            if gone and self.journal:
                self.journal.add("delete", str(p))
            return gone
        except FileNotFoundError:
            return True
        except PermissionError:
            if self.use_sudo:
                code, _ = run(["sudo", "-n", "rm", "-rf", "--", str(p)])
                if code == 0 and not safe_exists(p):
                    if self.journal:
                        self.journal.add("delete", str(p))
                    return True
            return False

    def _rmtree(self, p: Path) -> None:
        def onerror(func, path, exc_info):  # noqa: ANN001
            eno = None
            try:
                eno = exc_info[1].errno if exc_info and exc_info[1] else None
            except Exception:  # noqa: BLE001
                pass
            if eno == errno.EPERM:      # SIP/TCC: sudo не поможет
                return
            try:
                os.chmod(path, 0o755)
                func(path)
            except OSError:
                if self.use_sudo:
                    run(["sudo", "-n", "rm", "-rf", "--", path])

        try:
            shutil.rmtree(p, onerror=onerror)
        except OSError:
            pass

    def _finder_available(self) -> bool:
        if self._finder_ok is None:
            self._finder_ok = (
                os.uname().sysname == "Darwin" and have("osascript")
            )
        return self._finder_ok


# --------------------------------------------------------------------------- #
#  Журнал действий + откат
# --------------------------------------------------------------------------- #

class Journal:
    """JSON-журнал в ~/.mac_tweaker/journal-<дата>.jsonl с возможностью отката."""

    def __init__(self, paths: Paths, enabled: bool = True):
        self.paths = paths
        self.enabled = enabled
        self.entries: List[Dict] = []
        self.file = paths.state_dir / f"journal-{datetime.now():%Y%m%d}.jsonl"

    def add(self, kind: str, target: str, extra: Optional[Dict] = None) -> None:
        rec = {"ts": datetime.now().isoformat(timespec="seconds"),
               "kind": kind, "target": target}
        if extra:
            rec.update(extra)
        self.entries.append(rec)
        if not self.enabled:
            return
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    @classmethod
    def load(cls, paths: Paths) -> List[Dict]:
        out: List[Dict] = []
        for f in sorted(glob.glob(str(paths.state_dir / "journal-*.jsonl"))):
            try:
                for line in Path(f).read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        out.append(json.loads(line))
            except (OSError, json.JSONDecodeError):
                continue
        return out

    def undo_last_session(self) -> Tuple[int, List[str]]:
        """Вернуть из Корзины всё, что было перемещено последней сессией."""
        restored, problems = 0, []
        for rec in reversed(self.entries):
            if rec.get("kind") != "trash":
                continue
            src = Path(rec["target"])
            if safe_exists(src):
                restored += 1
                continue
            found = self._find_in_trash(src.name)
            if found:
                try:
                    shutil.move(str(found), str(src))
                    restored += 1
                except (OSError, shutil.Error) as exc:
                    problems.append(f"{src}: {exc}")
            else:
                problems.append(f"{src}: не найдено в Корзине")
        return restored, problems

    def _find_in_trash(self, name: str) -> Optional[Path]:
        trash = self.paths.trash
        cand = trash / name
        if safe_exists(cand):
            return cand
        stem = Path(name).stem
        for e in safe_scandir(trash):
            if e.name.startswith(stem):
                return Path(e.path)
        return None
