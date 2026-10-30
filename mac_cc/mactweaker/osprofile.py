"""
mactweaker.osprofile — версионированная конфигурация под конкретную macOS.

Apple от версии к версии меняет и расположение данных, и системные вызовы:
  * Ventura (13)   — автозагрузка переехала в Background Task Management;
  * Sonoma (14)    — виджеты на рабочем столе, новые ключи WindowManager;
  * Sequoia (15)   — iPhone Mirroring, ещё более строгие TCC/SIP;
  * Tahoe (26)     — локальные модели Apple Intelligence + «иллюзия свободного
                     места» из-за локальных снапшотов APFS;
  * Golden Gate (27) — конец поддержки Intel: Rosetta-проверки больше не нужны.

Чтобы не размазывать if/else по всем сканерам, версия ОС читается ОДИН раз
(platform.mac_ver()) и упаковывается в dataclass OSFeatures. Сканеры берут
готовые пути и флаги из этого профиля; при выходе новой macOS достаточно
дописать ветку в get_os_features().

Здесь же:
  * has_full_disk_access() — явная проверка прав (TCC/FDA), чтобы утилита
    честно говорила «нет прав», а не молча пропускала каталоги;
  * локальные снапшоты APFS (tmutil listlocalsnapshots) — причина, по которой
    очистка кэшей иногда «не освобождает» место.
"""

from __future__ import annotations

import os
import platform
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .i18n import tr
from .safety import Paths, run

#: Соответствие «мажорная версия → маркетинговое имя».
MACOS_NAMES: Dict[int, str] = {
    11: "Big Sur",
    12: "Monterey",
    13: "Ventura",
    14: "Sonoma",
    15: "Sequoia",
    26: "Tahoe",
    27: "Golden Gate",
}


@dataclass(frozen=True)
class OSFeatures:
    """Что умеет/требует конкретная версия macOS."""

    name: str
    major: int
    #: Golden Gate (27) и новее — только Apple Silicon.
    supports_intel: bool = True
    #: Background Task Management вместо старых Login Items (Ventura 13+).
    has_btm: bool = False
    #: Виджеты на рабочем столе (Sonoma 14+).
    has_desktop_widgets: bool = False
    #: Stage Manager (Ventura 13+).
    has_stage_manager: bool = False
    #: iPhone Mirroring (Sequoia 15+).
    has_iphone_mirroring: bool = False
    #: Каталоги локальных моделей Apple Intelligence (Tahoe 26+).
    ai_caches_paths: Tuple[str, ...] = ()
    #: Локальные снапшоты APFS «съедают» освобождённое место (Tahoe 26+).
    needs_snapshot_check: bool = False
    #: Архитектура машины (arm64 / x86_64).
    arch: str = ""

    @property
    def is_apple_silicon(self) -> bool:
        return self.arch == "arm64" or not self.supports_intel


#: Базовые кэши локального ИИ (речь/Siri), которые появляются с Tahoe.
AI_CACHE_BASE: Tuple[str, ...] = (
    "{lib}/Caches/com.apple.CoreSpeech",
    "{lib}/Caches/com.apple.speech.synthesis",
    "{lib}/Caches/com.apple.assistant*",
    "{lib}/Caches/com.apple.Siri*",
)

#: Golden Gate добавляет отдельное хранилище весов Apple Intelligence.
AI_CACHE_GOLDEN_GATE: Tuple[str, ...] = (
    "{appsupport}/Apple Intelligence",
    "{lib}/Caches/com.apple.AppleIntelligence*",
)


def macos_major() -> int:
    """Мажорная версия macOS: 15 для «15.1», 0 если это не macOS.

    Приоритет: MACTWEAKER_MACOS_MAJOR (тесты) → platform.mac_ver().
    """
    env = os.environ.get("MACTWEAKER_MACOS_MAJOR")
    if env:
        try:
            return int(env.split(".")[0])
        except ValueError:
            pass
    try:
        ver = platform.mac_ver()[0]
        return int(ver.split(".")[0]) if ver else 0
    except (ValueError, IndexError, AttributeError):
        return 0


def get_os_features(major: Optional[int] = None,
                    arch: Optional[str] = None) -> OSFeatures:
    """Собрать профиль фич ОС. Версия читается один раз."""
    if major is None:
        major = macos_major()
    if arch is None:
        arch = platform.machine() or ""

    ai_paths: Tuple[str, ...] = ()
    name = MACOS_NAMES.get(major, f"macOS {major}" if major else "не macOS")

    if major >= 27:                       # Golden Gate (2026): только ARM
        ai_paths = AI_CACHE_BASE + AI_CACHE_GOLDEN_GATE
        return OSFeatures(name=name, major=major, supports_intel=False,
                          has_btm=True, has_desktop_widgets=True,
                          has_stage_manager=True, has_iphone_mirroring=True,
                          ai_caches_paths=ai_paths, needs_snapshot_check=True,
                          arch=arch)
    if major == 26:                       # Tahoe (2025): локальный ИИ + снапшоты
        return OSFeatures(name=name, major=major, supports_intel=True,
                          has_btm=True, has_desktop_widgets=True,
                          has_stage_manager=True, has_iphone_mirroring=True,
                          ai_caches_paths=AI_CACHE_BASE,
                          needs_snapshot_check=True, arch=arch)
    return OSFeatures(name=name, major=major, supports_intel=True,
                      has_btm=major >= 13,
                      has_desktop_widgets=major >= 14,
                      has_stage_manager=major >= 13,
                      has_iphone_mirroring=major >= 15,
                      ai_caches_paths=(),
                      needs_snapshot_check=False, arch=arch)


def get_target_paths(paths: Paths, major: Optional[int] = None) -> Dict[str, object]:
    """Единая карта «что где лежит» для этой версии ОС.

    Сканеры берут пути отсюда, а не собирают их if/else по коду: при выходе
    новой macOS новый ключ добавляется в одном месте.
    """
    if major is None:
        major = macos_major()
    h, lib, syslib = str(paths.home), str(paths.lib), str(paths.sys_lib)
    out: Dict[str, object] = {
        "caches": [f"{lib}/Caches", f"{syslib}/Caches"],
        "logs": [f"{lib}/Logs", f"{syslib}/Logs", f"{paths.sysroot}/private/var/log"],
        "app_support": [f"{lib}/Application Support"],
        "containers": [f"{lib}/Containers"],
        "group_containers": [f"{lib}/Group Containers"],
    }
    if major >= 13:  # Ventura+: автозагрузка живёт в BTM
        out["background_tasks"] = (
            f"{paths.sysroot}/private/var/db/com.apple.backgroundtaskmanagement")
        out["login_items_legacy"] = []          # старые Login Items больше не источник
    if major >= 14:  # Sonoma+: кэши виджетов рабочего стола
        out["widgets_cache"] = [
            f"{lib}/Caches/com.apple.widgetkit",
            f"{lib}/Caches/com.apple.chronod",
            f"{lib}/Group Containers/group.com.apple.notes",   # только чтение!
        ]
    if major >= 26:  # Tahoe+: веса локальных моделей Apple Intelligence
        subs = {"home": h, "lib": lib, "sys": str(paths.sysroot),
                "syslib": syslib, "appsupport": f"{lib}/Application Support"}
        feats = get_os_features(major=major)
        out["ai_models"] = [p.format(**subs) for p in feats.ai_caches_paths]
    return out


# --------------------------------------------------------------------------- #
#  Full Disk Access (TCC)
# --------------------------------------------------------------------------- #

def has_full_disk_access(paths: Optional[Paths] = None) -> Optional[bool]:
    """Дан ли терминалу/процессу Full Disk Access.

    None — не macOS (проверка не имеет смысла). Проверка: пробуем прочитать
    каталог, закрытый TCC для процессов без FDA (база TCC.db, ~/Library/Safari,
    ~/Library/Mail). PermissionError → FDA нет.
    """
    if sys.platform != "darwin" and os.uname().sysname != "Darwin":
        return None
    paths = paths or Paths.detect()
    probes = [
        paths.lib / "Application Support" / "com.apple.TCC",
        paths.lib / "Safari",
        paths.lib / "Mail",
        Path("/Library/Application Support/com.apple.TCC"),
    ]
    for probe in probes:
        try:
            if not probe.exists():
                continue
            with os.scandir(probe) as it:
                list(it)
            return True                      # защищённый каталог открылся → FDA есть
        except PermissionError:
            return False
        except OSError:
            continue                         # недоступен по другой причине
    return None                              # probe-каталогов нет — не определили


def fda_hint() -> str:
    """Инструкция, куда нажать, чтобы выдать FDA."""
    return tr("Системные настройки → Приватность и безопасность → "
              "Полный доступ к диску → включите ваш терминал")


# --------------------------------------------------------------------------- #
#  Локальные снапшоты APFS (tmutil)
# --------------------------------------------------------------------------- #

SNAPSHOT_RE = re.compile(r"com\.apple\.TimeMachine\.(\d{4}-\d{2}-\d{2}-\d{6})\.local")


def snapshots_supported() -> bool:
    return (sys.platform == "darwin" or os.uname().sysname == "Darwin")


def list_local_snapshots(volume: str = "/") -> List[str]:
    """Даты локальных снапшотов APFS (пустой список, если их нет/tmutil нет)."""
    if not snapshots_supported():
        return []
    code, out = run(["tmutil", "listlocalsnapshots", volume], timeout=60)
    if code != 0 or not out:
        return []
    dates: List[str] = []
    for line in out.splitlines():
        m = SNAPSHOT_RE.search(line.strip())
        if m:
            dates.append(m.group(1))
    return sorted(dates)


def delete_local_snapshot(date: str, use_sudo: bool = True) -> Tuple[bool, str]:
    """Удалить один локальный снапшот по его дате (нужен sudo)."""
    if not SNAPSHOT_RE.match("com.apple.TimeMachine." + date + ".local"):
        return False, tr("неверный формат даты снапшота")
    prefix = ["sudo", "-n"] if use_sudo else []
    code, out = run(prefix + ["tmutil", "deletelocalsnapshots", date], timeout=120)
    return code == 0, (out or ("ok" if code == 0 else "error"))[:120]


def snapshots_status(volume: str = "/") -> Dict[str, object]:
    """Сводка для интерфейса: поддерживается ли, сколько снапшотов, даты."""
    return {
        "supported": snapshots_supported(),
        "dates": list_local_snapshots(volume),
        "volume": volume,
    }
