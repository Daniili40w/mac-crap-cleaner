"""
mactweaker.startup — автозагрузка macOS: что грузится, зачем и что можно выключить.

Источники:
  ~/Library/LaunchAgents            агенты текущего пользователя
  /Library/LaunchAgents             агенты всех пользователей
  /Library/LaunchDaemons            демоны (root)
  /System/Library/Launch{Agents,Daemons}  системные (SIP, только просмотр)
  Login Items (System Events)       элементы входа
  sfltool dumpbtm                   фоновые элементы (macOS 13+, нужен sudo)

Действия обратимы: перед отключением plist переносится в
~/.mac_tweaker/disabled/<label>.plist, запись пишется в журнал; «Включить»
возвращает файл на место и грузит его.
"""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .i18n import tr
from .safety import (Paths, human, is_datavault, run, safe_exists, safe_isdir,
                     safe_isfile, safe_scandir, sudo_ok)

DOMAIN_USER = "user"            # ~/Library/LaunchAgents
DOMAIN_GLOBAL = "global"        # /Library/LaunchAgents
DOMAIN_DAEMON = "daemon"        # /Library/LaunchDaemons
DOMAIN_SYSTEM = "system"        # /System/Library/... (только просмотр)
DOMAIN_LOGIN = "login"          # Login Items
DOMAIN_BTM = "btm"              # Background Task Management

DOMAIN_LABEL = {
    DOMAIN_USER: "агент пользователя",
    DOMAIN_GLOBAL: "агент (все пользователи)",
    DOMAIN_DAEMON: "демон (root)",
    DOMAIN_SYSTEM: "система (SIP)",
    DOMAIN_LOGIN: "элемент входа",
    DOMAIN_BTM: "фоновый элемент",
}

STATE_RUNNING = "running"
STATE_LOADED = "loaded"
STATE_STOPPED = "stopped"
STATE_FAILED = "failed"
STATE_UNLOADED = "unloaded"
STATE_BROKEN = "broken"
STATE_DISABLED = "disabled"

STATE_MARK = {
    STATE_RUNNING: "▶ работает",
    STATE_LOADED: "● загружен",
    STATE_STOPPED: "○ остановлен",
    STATE_FAILED: "✗ падает",
    STATE_UNLOADED: "— не загружен",
    STATE_BROKEN: "⚠ битый",
    STATE_DISABLED: "⛔ отключён",
}

#: Метки, которые нельзя трогать ни при каких условиях.
CRITICAL_LABELS = frozenset({
    "com.apple.WindowServer", "com.apple.loginwindow", "com.apple.launchd",
    "com.apple.opendirectoryd", "com.apple.notifyd", "com.apple.syslogd",
    "com.apple.securityd", "com.apple.distnoted", "com.apple.cfprefsd",
    "com.apple.taskgated", "com.apple.coreduetd", "com.apple.UserEventAgent",
})

#: Подозрительные признаки «мёртвого груза».
DEAD_WEIGHT_HINTS = (
    ("обновлятор", "updater"), ("проверка лицензии", "license"),
    ("агент синхронизации", "sync"), ("сбор телеметрии", "analytics"),
    ("отчёты об использовании", "usage"), ("краш-репортер", "crash"),
)


@dataclass
class LaunchItem:
    label: str
    path: Optional[Path]
    domain: str
    kind: str = "agent"              # agent | daemon | login | btm
    program: str = ""
    args: List[str] = field(default_factory=list)
    run_at_load: bool = False
    keep_alive: bool = False
    state: str = STATE_UNLOADED
    pid: int = 0
    last_exit: int = 0
    size: int = 0
    mtime: float = 0.0
    developer: str = ""
    missing_binary: bool = False
    critical: bool = False
    protected: bool = False
    #: заметки как (ru-шаблон, аргументы) — переводятся в момент показа
    notes: List[Tuple[str, dict]] = field(default_factory=list)
    selected: bool = False
    app_name: str = ""

    def note_texts(self) -> List[str]:
        """Заметки на текущем языке (шаблон переводится при показе).

        Терпит оба формата записей: (ru-шаблон, аргументы) и простую строку —
        старые/сторонние заметки не должны ронять интерфейс.
        """
        out: List[str] = []
        for item in self.notes:
            if isinstance(item, (tuple, list)) and len(item) == 2:
                tpl, kw = item
            else:
                tpl, kw = str(item), {}
            fmt = {k: (tr(v) if isinstance(v, str) else v) for k, v in kw.items()}
            out.append(tr(tpl).format(**fmt))
        return out

    @property
    def domain_label(self) -> str:
        return DOMAIN_LABEL.get(self.domain, self.domain)

    @property
    def state_mark(self) -> str:
        return STATE_MARK.get(self.state, self.state)

    @property
    def disable_allowed(self) -> bool:
        return not (self.critical or self.protected or self.domain == DOMAIN_SYSTEM)

    @property
    def command(self) -> str:
        return " ".join([self.program] + self.args).strip()


# --------------------------------------------------------------------------- #
#  Сбор
# --------------------------------------------------------------------------- #

def _dirs(paths: Paths) -> List[Tuple[str, Path, str, bool]]:
    """(домен, каталог, тип, только-просмотр)."""
    return [
        (DOMAIN_USER, paths.lib / "LaunchAgents", "agent", False),
        (DOMAIN_GLOBAL, paths.sys_lib / "LaunchAgents", "agent", False),
        (DOMAIN_DAEMON, paths.sys_lib / "LaunchDaemons", "daemon", False),
        (DOMAIN_SYSTEM, paths.system_library / "LaunchAgents", "agent", True),
        (DOMAIN_SYSTEM, paths.system_library / "LaunchDaemons", "daemon", True),
    ]


def _launchctl_state() -> Dict[str, Tuple[int, int]]:
    """label -> (pid, last_exit) из `launchctl list`."""
    out: Dict[str, Tuple[int, int]] = {}
    code, text = run(["launchctl", "list"], timeout=30)
    if code != 0:
        return out
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        pid_s, status_s, label = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if label in ("Label", ""):
            continue
        try:
            pid = int(pid_s) if pid_s not in ("-", "") else 0
        except ValueError:
            pid = 0
        try:
            status = int(status_s) if status_s not in ("-", "") else 0
        except ValueError:
            status = 0
        out[label] = (pid, status)
    return out


_sign_cache: Dict[str, str] = {}


def developer_of(binary: str) -> str:
    """Кто подписал исполняемый файл (из codesign)."""
    if not binary or binary in _sign_cache:
        return _sign_cache.get(binary, "")
    dev = ""
    code, out = run(["codesign", "-dvv", "--", binary], timeout=20)
    text = out if code in (0, 1) else ""
    for line in text.splitlines():
        if line.startswith("Authority="):
            value = line.split("=", 1)[1].strip()
            if value and "Apple" not in value:
                dev = value
                break
            if value and not dev:
                dev = value
    _sign_cache[binary] = dev
    return dev


def _parse_plist(p: Path) -> Dict:
    try:
        with open(p, "rb") as fh:
            data = plistlib.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _program_of(data: Dict) -> Tuple[str, List[str]]:
    prog = str(data.get("Program") or "").strip()
    args = [str(a) for a in (data.get("ProgramArguments") or [])]
    if args and not prog:
        prog = args[0]
        args = args[1:]
    return prog, args


def collect(paths: Paths,
            include_system: bool = False,
            include_login_items: bool = True,
            include_btm: bool = False,
            registry=None,
            progress=None) -> List[LaunchItem]:
    items: List[LaunchItem] = []
    states = _launchctl_state()
    dirs = _dirs(paths)
    if not include_system:
        dirs = [d for d in dirs if d[0] != DOMAIN_SYSTEM]

    for i, (domain, d, kind, readonly) in enumerate(dirs):
        if progress:
            progress(i, len(dirs), str(d))
        if not safe_isdir(d):
            continue
        for e in safe_scandir(d):
            if not e.name.endswith(".plist") or is_datavault(Path(e.path)):
                continue
            p = Path(e.path)
            items.append(_item_from_plist(p, domain, kind, readonly, states, registry))

    if include_login_items:
        items.extend(_login_items(states))
    if include_btm:
        items.extend(_btm_items(paths))

    # отключённые ранее этим тулзом
    for e in safe_scandir(disabled_dir(paths)):
        if e.name.endswith(".plist"):
            it = _item_from_plist(Path(e.path), DOMAIN_USER, "agent", True, {}, registry)
            it.state = STATE_DISABLED
            it.notes.append("отключён через Mac Crap Cleaner")
            items.append(it)

    if progress:
        progress(len(dirs), len(dirs), "")
    items.sort(key=lambda it: (it.domain != DOMAIN_USER, it.domain, it.label.lower()))
    return items


def _item_from_plist(p: Path, domain: str, kind: str, readonly: bool,
                     states: Dict[str, Tuple[int, int]], registry=None) -> LaunchItem:
    data = _parse_plist(p)
    label = str(data.get("Label") or p.stem)
    prog, args = _program_of(data)
    keep_alive = data.get("KeepAlive")
    if isinstance(keep_alive, dict):
        keep_alive = bool(keep_alive)
    run_at_load = bool(data.get("RunAtLoad"))

    it = LaunchItem(
        label=label, path=p, domain=domain, kind=kind,
        program=prog, args=args,
        run_at_load=run_at_load, keep_alive=bool(keep_alive),
        size=(p.stat().st_size if safe_isfile(p) else 0),
        mtime=(p.stat().st_mtime if safe_isfile(p) else 0.0),
        protected=readonly,
        critical=(domain == DOMAIN_SYSTEM or label in CRITICAL_LABELS
                  or label.startswith("com.apple.")),
    )

    # состояние из launchctl
    pid, status = states.get(label, (0, 0))
    it.pid, it.last_exit = pid, status
    if pid > 0:
        it.state = STATE_RUNNING
    elif label in states:
        it.state = STATE_FAILED if status not in (0, 173) else STATE_LOADED
    else:
        it.state = STATE_UNLOADED

    # бинарник
    binary = prog
    if binary and not os.path.isabs(binary):
        binary = shutil.which(binary) or ""
    if binary and not safe_exists(binary):
        it.missing_binary = True
        it.state = STATE_BROKEN
        it.notes.append(("исполняемый файл отсутствует — программа удалена", {}))
    if binary:
        it.developer = developer_of(binary)
        it.app_name = _guess_app_name(binary, registry)

    if it.state == STATE_FAILED:
        it.notes.append(("загружен, но завершился с кодом {code}", {"code": status}))
    if not it.run_at_load and not it.keep_alive:
        it.notes.append(("запускается по требованию, а не при входе", {}))
    low = label.lower() + " " + binary.lower()
    for ru, en in DEAD_WEIGHT_HINTS:
        if en in low:
            it.notes.append(("возможное назначение: {what}", {"what": ru}))
            break
    return it


def _guess_app_name(binary: str, registry=None) -> str:
    """Имя приложения по пути бинарника (/Applications/Foo.app/Contents/...)."""
    m = re.search(r"/([^/]+)\.app/", binary)
    if m:
        return m.group(1)
    if registry is not None:
        for app in getattr(registry, "apps", []):
            if str(app.path) in binary:
                return app.name
    return Path(binary).stem if binary else ""


def _login_items(states: Dict[str, Tuple[int, int]]) -> List[LaunchItem]:
    script = ('tell application "System Events" to get the name of every login item')
    code, out = run(["osascript", "-e", script], timeout=45)
    if code != 0 or not out:
        return []
    script_path = ('tell application "System Events" to get the path of every login item')
    _, paths_out = run(["osascript", "-e", script_path], timeout=45)
    names = [x.strip() for x in out.split(",") if x.strip()]
    item_paths = [x.strip() for x in (paths_out or "").split(",")]
    res: List[LaunchItem] = []
    for i, name in enumerate(names):
        p = item_paths[i] if i < len(item_paths) else ""
        it = LaunchItem(label=name, path=Path(p) if p else None,
                        domain=DOMAIN_LOGIN, kind="login",
                        program=p, run_at_load=True,
                        state=STATE_LOADED, protected=False)
        it.app_name = name
        if p:
            it.developer = developer_of(_binary_inside(p))
            if not safe_exists(p):
                it.missing_binary = True
                it.state = STATE_BROKEN
                it.notes.append("путь недоступен — возможно, программа удалена")
        res.append(it)
    return res


def _binary_inside(app: str) -> str:
    p = Path(app)
    if p.suffix != ".app":
        return app
    info = _parse_plist(p / "Contents" / "Info.plist")
    exe = str(info.get("CFBundleExecutable") or "")
    cand = p / "Contents" / "MacOS" / exe
    return str(cand) if exe and safe_exists(cand) else app


def _btm_items(paths: Paths) -> List[LaunchItem]:
    """sfltool dumpbtm — фоновые элементы macOS 13+ (нужен root)."""
    if not sudo_ok(non_interactive=True):
        return []
    code, out = run(["sudo", "-n", "sfltool", "dumpbtm"], timeout=60)
    if code != 0 or not out:
        return []
    items: List[LaunchItem] = []
    cur: Dict[str, str] = {}
    for line in out.splitlines():
        line = line.strip()
        m = re.match(r"^(name|identifier|disposition|type|url|developer|state):\s*(.+)$",
                     line)
        if m:
            cur[m.group(1)] = m.group(2).strip()
        elif line.startswith("---") or not line:
            if cur.get("identifier"):
                items.append(_btm_to_item(cur))
            cur = {}
    if cur.get("identifier"):
        items.append(_btm_to_item(cur))
    return items


def _btm_to_item(cur: Dict[str, str]) -> LaunchItem:
    label = cur.get("identifier") or cur.get("name") or "?"
    disposition = cur.get("disposition", "").lower()
    it = LaunchItem(label=label, path=None, domain=DOMAIN_BTM, kind="btm",
                    program=cur.get("url", ""),
                    app_name=cur.get("name", ""),
                    developer=cur.get("developer", ""))
    it.state = STATE_LOADED if "allow" in disposition else STATE_STOPPED
    if "deny" in disposition or "disabled" in disposition:
        it.state = STATE_DISABLED
    btm = f"{cur.get('type', '')} {cur.get('disposition', '')}".strip()
    it.notes.append(("BTM: {what}", {"what": btm}))
    it.protected = True      # управление только через Системные настройки
    return it


# --------------------------------------------------------------------------- #
#  Хранилище отключённых
# --------------------------------------------------------------------------- #

def disabled_dir(paths: Paths) -> Path:
    d = paths.state_dir / "disabled"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def _unique(dest: Path) -> Path:
    if not safe_exists(dest):
        return dest
    n = 1
    while safe_exists(dest.with_name(f"{dest.stem}.{n}{dest.suffix}")):
        n += 1
    return dest.with_name(f"{dest.stem}.{n}{dest.suffix}")


# --------------------------------------------------------------------------- #
#  Действия
# --------------------------------------------------------------------------- #

def _uid() -> str:
    code, out = run(["id", "-u"], timeout=10)
    return out.strip() if code == 0 else str(os.getuid())


def disable(items: Sequence[LaunchItem], paths: Paths,
            use_sudo: bool = False) -> List[Tuple[LaunchItem, bool, str]]:
    """Выгрузить и убрать из автозапуска. Возвращает [(item, ok, сообщение)]."""
    res: List[Tuple[LaunchItem, bool, str]] = []
    ddir = disabled_dir(paths)
    for it in items:
        if not it.disable_allowed:
            res.append((it, False, tr("защищённый/системный элемент — нельзя отключать")))
            continue
        if it.domain == DOMAIN_LOGIN:
            res.append(_login_item_delete(it))
            continue
        if not it.path or not safe_exists(it.path):
            res.append((it, False, tr(" plist не найден на диске")))
            continue

        # 1. выгрузить из launchd
        unload(it, use_sudo)
        # 2. запомнить исходный путь внутри plist, чтобы «включить» вернуло его туда же
        orig = str(it.path)
        try:
            data = _parse_plist(it.path)
            data["MTDisabledFrom"] = orig
            data["MTDisabledAt"] = int(time.time())
            with open(it.path, "wb") as fh:
                plistlib.dump(data, fh)
        except (OSError, TypeError, plistlib.InvalidFileException):
            pass
        # 3. перенести plist в хранилище
        dest = _unique(ddir / it.path.name)
        try:
            shutil.move(str(it.path), str(dest))
        except (OSError, shutil.Error):
            if use_sudo:
                code, _ = run(["sudo", "-n", "mv", "--", str(it.path), str(dest)])
                if code != 0:
                    res.append((it, False, tr("нет прав на перемещение plist")))
                    continue
            else:
                res.append((it, False, tr("нет прав на перемещение plist (нужен sudo)")))
                continue
        it.state = STATE_DISABLED
        it.notes.append(("отключён, резервная копия: {path}",
                         {"path": paths.short(dest)}))
        res.append((it, True, f"{tr('⛔ отключён')} → {paths.short(dest)}"))
    return res


def enable(items: Sequence[LaunchItem], paths: Paths,
           use_sudo: bool = False) -> List[Tuple[LaunchItem, bool, str]]:
    """Вернуть отключённое обратно."""
    res: List[Tuple[LaunchItem, bool, str]] = []
    ddir = disabled_dir(paths)
    for it in items:
        if it.domain == DOMAIN_LOGIN:
            res.append((it, False, tr("элементы входа добавляются в Системных настройках")))
            continue
        src = it.path if it.path and safe_exists(it.path) else None
        if src is None:
            for e in safe_scandir(ddir):
                if it.label in e.name:
                    src = Path(e.path)
                    break
        if src is None:
            res.append((it, False, tr("резервная копия plist не найдена")))
            continue
        data = _parse_plist(src)
        orig = str(data.get("MTDisabledFrom") or "")
        if orig:
            dest_dir = Path(orig).parent
        elif it.domain == DOMAIN_DAEMON:
            dest_dir = paths.sys_lib / "LaunchDaemons"
        elif it.domain == DOMAIN_GLOBAL:
            dest_dir = paths.sys_lib / "LaunchAgents"
        else:
            dest_dir = paths.lib / "LaunchAgents"
        # уберём служебные ключи перед возвратом на место
        if "MTDisabledFrom" in data or "MTDisabledAt" in data:
            data.pop("MTDisabledFrom", None)
            data.pop("MTDisabledAt", None)
            try:
                with open(src, "wb") as fh:
                    plistlib.dump(data, fh)
            except (OSError, TypeError, plistlib.InvalidFileException):
                pass
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        dest = dest_dir / Path(src).name
        if dest == src:
            res.append((it, False, tr("элемент уже на месте")))
            continue
        try:
            shutil.move(str(src), str(dest))
            moved = True
        except (OSError, shutil.Error):
            moved = False
            if use_sudo:
                moved = run(["sudo", "-n", "mv", "--", str(src), str(dest)])[0] == 0
        if not moved:
            res.append((it, False, tr("не удалось вернуть plist на место")))
            continue
        it.path = dest
        load(it, use_sudo)
        it.state = STATE_LOADED
        res.append((it, True, f"{tr('● загружен')}: {paths.short(dest)}"))
    return res


def unload(it: LaunchItem, use_sudo: bool = False) -> bool:
    """Снять с launchd (не удаляя файл)."""
    if it.domain == DOMAIN_SYSTEM:
        return False
    prefix = ["sudo", "-n"] if (use_sudo and it.domain == DOMAIN_DAEMON) else []
    target = str(it.path) if it.path and safe_exists(it.path) else it.label
    cmds: List[List[str]] = []
    if it.domain == DOMAIN_DAEMON:
        cmds = [prefix + ["launchctl", "bootout", "system", target],
                prefix + ["launchctl", "unload", "-w", target]]
    else:
        cmds = [["launchctl", "bootout", f"gui/{_uid()}", target],
                ["launchctl", "unload", "-w", target],
                ["launchctl", "remove", it.label]]
    for c in cmds:
        code, _ = run(c, timeout=30)
        if code == 0:
            return True
    return False


def load(it: LaunchItem, use_sudo: bool = False) -> bool:
    if it.domain == DOMAIN_SYSTEM or not it.path or not safe_exists(it.path):
        return False
    prefix = ["sudo", "-n"] if (use_sudo and it.domain == DOMAIN_DAEMON) else []
    target = str(it.path)
    if it.domain == DOMAIN_DAEMON:
        cmds = [prefix + ["launchctl", "bootstrap", "system", target],
                prefix + ["launchctl", "load", "-w", target]]
    else:
        cmds = [["launchctl", "bootstrap", f"gui/{_uid()}", target],
                ["launchctl", "load", "-w", target]]
    for c in cmds:
        code, _ = run(c, timeout=30)
        if code == 0:
            return True
    return False


def _login_item_delete(it: LaunchItem) -> Tuple[LaunchItem, bool, str]:
    name = it.label.replace('"', '\\"')
    script = f'tell application "System Events" to delete login item "{name}"'
    code, out = run(["osascript", "-e", script], timeout=45)
    if code == 0:
        it.state = STATE_DISABLED
        return it, True, tr("элемент входа удалён")
    return it, False, f"System Events: {out[:80]}"


def restore_all(paths: Paths, use_sudo: bool = False) -> List[Tuple[LaunchItem, bool, str]]:
    """Вернуть всё, что было отключено этим тулзом."""
    return enable(disabled_items(paths), paths, use_sudo)


def disabled_items(paths: Paths) -> List[LaunchItem]:
    ddir = disabled_dir(paths)
    out: List[LaunchItem] = []
    for e in safe_scandir(ddir):
        if not e.name.endswith(".plist"):
            continue
        p = Path(e.path)
        data = _parse_plist(p)
        out.append(LaunchItem(
            label=str(data.get("Label") or p.stem), path=p, domain=DOMAIN_USER,
            kind="agent", program=_program_of(data)[0], state=STATE_DISABLED,
            size=p.stat().st_size if safe_isfile(p) else 0,
            mtime=p.stat().st_mtime if safe_isfile(p) else 0.0,
            notes=["отключён через Mac Crap Cleaner"]))
    return out


def group_by_domain(items: Sequence[LaunchItem]) -> Dict[str, List[LaunchItem]]:
    out: Dict[str, List[LaunchItem]] = {}
    for it in items:
        out.setdefault(it.domain, []).append(it)
    order = [DOMAIN_USER, DOMAIN_GLOBAL, DOMAIN_DAEMON, DOMAIN_LOGIN,
             DOMAIN_BTM, DOMAIN_SYSTEM]
    return {k: out[k] for k in order if k in out}


def dead_weight(items: Sequence[LaunchItem]) -> List[LaunchItem]:
    """Кандидаты на отключение: битые, падающие, чужие обновляторы/телеметрия."""
    bad: List[LaunchItem] = []
    for it in items:
        if not it.disable_allowed:
            continue
        score = 0
        if it.missing_binary:
            score += 3
        if it.state == STATE_FAILED:
            score += 2
        if it.state == STATE_UNLOADED and not it.run_at_load and not it.keep_alive:
            score += 1
        low = (it.label + " " + it.command).lower()
        if any(en in low for _, en in DEAD_WEIGHT_HINTS):
            score += 1
        if it.developer and "Apple" not in it.developer:
            score += 0
        if score >= 2:
            bad.append(it)
    return bad
