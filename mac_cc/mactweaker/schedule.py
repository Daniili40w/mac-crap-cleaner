"""
mactweaker.schedule — автоматизация через launchd.

Генерирует агент ~/Library/LaunchAgents/com.dan1lazz.maccc.plist, который
раз в неделю запускает базовый профиль очистки и пишет тихий отчёт в
~/.mac_tweaker/scheduled.log. Всё честно: без sudo (системные кэши
пропускаются), без --hard (удаление только в Корзину), низкий приоритет
CPU/IO, чтобы уборка не мешала работе.

CLI:  maccc schedule status | install | uninstall
TUI:  пункт главного меню «Автоочистка по расписанию».
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from .i18n import tr
from .safety import Paths, run, safe_exists

AGENT_LABEL = "com.dan1lazz.maccc"

#: Дни недели для StartCalendarInterval (0 = воскресенье, как в launchd).
WEEKDAYS = {
    0: "воскресенье", 1: "понедельник", 2: "вторник", 3: "среда",
    4: "четверг", 5: "пятница", 6: "суббота",
}

_PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<!--
  Создано автоматически: Mac Crap Cleaner (MacCC), {generated}.
  Еженедельная автоочистка профиля «{profile}».

  Отчёт о каждом запуске: {log}
  Удаление: только в Корзину (обратимо), без sudo, низкий приоритет.

  Отключить:  launchctl bootout gui/$(id -u)/{label}
              rm ~/Library/LaunchAgents/{label}.plist
-->
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>

    <key>ProgramArguments</key>
    <array>
{argv}
    </array>

    <!-- {weekday_name}, {hour:02d}:{minute:02d} -->
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>{weekday}</integer>
        <key>Hour</key>
        <integer>{hour}</integer>
        <key>Minute</key>
        <integer>{minute}</integer>
    </dict>

    <key>RunAtLoad</key>
    <false/>

    <key>StandardOutPath</key>
    <string>{log}</string>
    <key>StandardErrorPath</key>
    <string>{log}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>LANG</key>
        <string>ru_RU.UTF-8</string>
        <key>NO_COLOR</key>
        <string>1</string>
    </dict>

    <!-- не мешать системе: низкий приоритет CPU и ввода-вывода -->
    <key>Nice</key>
    <integer>10</integer>
    <key>LowPriorityIO</key>
    <true/>
    <key>ProcessType</key>
    <string>Background</string>
</dict>
</plist>
"""


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def agent_plist_path(paths: Paths) -> Path:
    return paths.lib / "LaunchAgents" / (AGENT_LABEL + ".plist")


def report_path(paths: Paths) -> Path:
    """Тихий отчёт еженедельного запуска."""
    return paths.state_dir / "scheduled.log"


def detect_runner(paths: Paths) -> Tuple[str, str]:
    """(python, скрипт) — чем запускать MacCC из-под launchd.

    Приоритет: текущая точка входа (бандл maccc_bundle.py или maccc.py),
    иначе maccc.py рядом с пакетом, иначе системный python3 + «не найдено».
    """
    python = sys.executable or "/usr/bin/python3"
    argv0 = Path(sys.argv[0] or "").resolve() if sys.argv and sys.argv[0] else None
    candidates: List[Path] = []
    if argv0 is not None and argv0.suffix == ".py":
        candidates.append(argv0)
    here = Path(__file__).resolve().parent
    candidates.append(here.parent / "maccc.py")
    candidates.append(here.parent / "dist" / "maccc_bundle.py")
    for c in candidates:
        if safe_exists(c):
            return python, str(c)
    return python, ""


def render_plist(paths: Paths,
                 profile: str = "basic",
                 weekday: int = 0,
                 hour: int = 4,
                 minute: int = 0,
                 runner: Optional[Tuple[str, str]] = None,
                 older_than_days: int = 30) -> str:
    """Содержимое plist-агента (строка)."""
    python, script = runner or detect_runner(paths)
    argv = [python, script, "--no-color", "clean",
            "--profile", profile,
            "--older-than-days", str(older_than_days),
            "--no-commands", "-y"]
    argv_xml = "\n".join(f"        <string>{_xml_escape(a)}</string>" for a in argv)
    log = str(report_path(paths))
    return _PLIST_TEMPLATE.format(
        generated=datetime.now().isoformat(timespec="seconds"),
        profile=profile, log=log, label=AGENT_LABEL, argv=argv_xml,
        weekday=weekday, weekday_name=WEEKDAYS.get(weekday, str(weekday)),
        hour=hour, minute=minute)


@dataclass
class AgentStatus:
    installed: bool = False
    loaded: bool = False
    plist: str = ""
    log: str = ""
    runner: str = ""
    last_report: str = ""

    def summary(self, paths: Paths) -> List[str]:
        out = [
            tr("Агент: {path}").format(path=paths.short(Path(self.plist))),
            tr("Статус: ") + (tr("установлен") if self.installed else tr("не установлен")),
        ]
        if self.installed:
            out.append(tr("Загружен в launchd: ") +
                       (tr("да") if self.loaded else tr("нет")))
        out.append(tr("Отчёт: {path}").format(path=paths.short(Path(self.log))))
        if self.last_report:
            out.append(tr("Последний отчёт: {ago}").format(ago=self.last_report))
        return out


def agent_status(paths: Paths) -> AgentStatus:
    plist = agent_plist_path(paths)
    st = AgentStatus(installed=safe_exists(plist), plist=str(plist),
                     log=str(report_path(paths)))
    python, script = detect_runner(paths)
    st.runner = f"{python} {script}".strip()
    log = report_path(paths)
    if safe_exists(log):
        from .safety import ago
        try:
            st.last_report = ago(log.stat().st_mtime)
        except OSError:
            st.last_report = ""
    if st.installed:
        code, out = run(["launchctl", "list", AGENT_LABEL], timeout=20)
        st.loaded = code == 0
    return st


def install_agent(paths: Paths,
                  profile: str = "basic",
                  weekday: int = 0,
                  hour: int = 4,
                  minute: int = 0) -> Tuple[bool, str]:
    """Создать plist агента и загрузить его в launchd."""
    _python, script = detect_runner(paths)
    if not script:
        return False, tr("не найден запускаемый скрипт MacCC — установите "
                         "бандл или запустите генерацию из каталога проекта")
    plist = agent_plist_path(paths)
    try:
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_text(render_plist(paths, profile=profile, weekday=weekday,
                                      hour=hour, minute=minute),
                         encoding="utf-8")
        os.chmod(plist, 0o644)
    except OSError as exc:
        return False, tr("не удалось записать plist: {err}").format(err=str(exc)[:80])

    # загрузка: сначала современный bootstrap, затем классический load
    uid = os.getuid() if hasattr(os, "getuid") else 501
    code, out = run(["launchctl", "bootout", f"gui/{uid}/{AGENT_LABEL}"], timeout=30)
    code, out = run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)], timeout=30)
    if code != 0:
        code, out = run(["launchctl", "load", "-w", str(plist)], timeout=30)
    if code != 0:
        return True, tr("plist создан, но launchctl недоступен — загрузите вручную: "
                        "launchctl load {path}").format(path=str(plist))
    return True, tr("агент установлен: очистка профиля «{profile}» каждые "
                    "{weekday} в {hour:02d}:{minute:02d}").format(
                        profile=profile, weekday=tr(WEEKDAYS.get(weekday, "?")),
                        hour=hour, minute=minute)


def uninstall_agent(paths: Paths) -> Tuple[bool, str]:
    """Снять агент с launchd и удалить plist (в Корзину не переносим — он наш)."""
    plist = agent_plist_path(paths)
    uid = os.getuid() if hasattr(os, "getuid") else 501
    if safe_exists(plist):
        run(["launchctl", "bootout", f"gui/{uid}/{AGENT_LABEL}"], timeout=30)
        run(["launchctl", "unload", "-w", str(plist)], timeout=30)
        try:
            plist.unlink()
        except OSError as exc:
            return False, tr("не удалось удалить plist: {err}").format(err=str(exc)[:80])
        return True, tr("агент удалён и снят с launchd")
    return False, tr("агент не установлен")
