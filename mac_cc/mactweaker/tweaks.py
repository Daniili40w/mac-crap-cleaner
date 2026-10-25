"""
mactweaker.tweaks — обратимые настройки macOS через `defaults`.

Каждый твик описан декларативно: домен, ключ, тип, «включённое» и «выключенное»
значение. Состояние читается тем же `defaults read`, поэтому экран честно
показывает, что уже включено. Все изменения обратимы одной кнопкой, плюс есть
экспорт/импорт всех настроек пользователя в plist-бэкап.

Ничего из списка не требует перезагрузки системы; части твиков нужен
повторный вход (помечено need_logout) или перезапуск приложения (restart).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .i18n import tr
from .safety import Paths, run, safe_exists

TYPE_BOOL = "bool"
TYPE_INT = "int"
TYPE_FLOAT = "float"
TYPE_STRING = "string"


@dataclass
class Tweak:
    tid: str
    section: str
    name: str
    description: str
    domain: str                       # com.apple.finder, NSGlobalDomain, …
    key: str
    vtype: str
    on_value: object
    off_value: object = None          # None = удалить ключ
    need_logout: bool = False
    restart: str = ""                 # приложение для перезапуска (killall)
    risky: bool = False
    state: bool = False
    raw: str = ""


def _all_tweaks() -> List[Tweak]:
    T = Tweak
    return [
        # ---------------- Finder ----------------
        T("finder-hidden", "Finder", "Показывать скрытые файлы",
          "Файлы и каталоги, начинающиеся с точки",
          "com.apple.finder", "AppleShowAllFiles", TYPE_BOOL, True, False,
          restart="Finder"),
        T("finder-extensions", "Finder", "Показывать расширения файлов",
          "Полезно видеть .sh/.command/.dmg",
          "NSGlobalDomain", "AppleShowAllExtensions", TYPE_BOOL, True, False),
        T("finder-pathbar", "Finder", "Показывать строку пути",
          "Полный путь к текущему каталогу внизу окна",
          "com.apple.finder", "ShowPathbar", TYPE_BOOL, True, False,
          restart="Finder"),
        T("finder-statusbar", "Finder", "Показывать строку состояния",
          "Число объектов и свободное место на диске",
          "com.apple.finder", "ShowStatusBar", TYPE_BOOL, True, False,
          restart="Finder"),
        T("finder-desktop-icons", "Finder", "Иконки на рабочем столе",
          "Выключите, если скриншоты должны быть чистыми",
          "com.apple.finder", "CreateDesktop", TYPE_BOOL, True, False,
          restart="Finder"),
        T("finder-usb-desktop", "Finder", "Внешние диски на рабочем столе",
          "Показывать съёмные тома и сетевые диски",
          "com.apple.finder", "ShowExternalHardDrivesOnDesktop", TYPE_BOOL,
          True, False, restart="Finder"),
        T("finder-recent-tags", "Finder", "Недавние теги в меню",
          "Убирает замусоренный список тегов",
          "com.apple.finder", "RecentTags", TYPE_BOOL, False, True,
          restart="Finder"),
        T("finder-warn-empty", "Finder", "Подтверждение очистки Корзины",
          "Внимание: выключение уберёт предупреждающий диалог",
          "com.apple.finder", "WarnOnEmptyTrash", TYPE_BOOL, True, False,
          restart="Finder", risky=True),
        T("finder-new-window", "Finder", "Новые окна в домашнем каталоге",
          "Вместо «Недавние»",
          "com.apple.finder", "NewWindowTarget", TYPE_STRING, "PfHm", "PfRe",
          restart="Finder"),

        # ---------------- Скриншоты ----------------
        T("shot-location", "Скриншоты", "Сохранять скриншоты в ~/Pictures/Screenshots",
          "Перестаёт засорять рабочий стол (нужен перезапуск Finder)",
          "com.apple.screencapture", "location", TYPE_STRING,
          "~/Pictures/Screenshots", "~/Desktop", need_logout=False,
          restart="Finder"),
        T("shot-shadow", "Скриншоты", "Без тени у окон",
          "Скриншоты окон без декоративной тени",
          "com.apple.screencapture", "disable-shadow", TYPE_BOOL, True, False),
        T("shot-format", "Скриншоты", "Формат PNG",
          "PNG вместо JPEG (больше размер, выше качество)",
          "com.apple.screencapture", "type", TYPE_STRING, "png", "jpg"),
        T("shot-delay", "Скриншоты", "Задержка 0 секунд",
          "Убирает задержку перед снимком",
          "com.apple.screencapture", "delay", TYPE_INT, 0, 5),

        # ---------------- Dock ----------------
        T("dock-autohide", "Dock", "Скрывать Dock автоматически",
          "Освобождает ~70 px высоты экрана",
          "com.apple.dock", "autohide", TYPE_BOOL, True, False, restart="Dock"),
        T("dock-size", "Dock", "Компактный размер иконок (48 px)",
          "Меньше иконки — больше места",
          "com.apple.dock", "tilesize", TYPE_INT, 48, 64, restart="Dock"),
        T("dock-magnification", "Dock", "Увеличение при наведении",
          "Эффект лупы под курсором",
          "com.apple.dock", "magnification", TYPE_BOOL, True, False,
          restart="Dock"),
        T("dock-recents", "Dock", "Секция «Недавние программы»",
          "Выключение убирает лишние иконки справа",
          "com.apple.dock", "show-recents", TYPE_BOOL, False, True,
          restart="Dock"),
        T("dock-anim", "Dock", "Мгновенное появление (без анимации)",
          "autohide-time-modifier = 0",
          "com.apple.dock", "autohide-time-modifier", TYPE_FLOAT, 0.0, 1.0,
          restart="Dock"),

        # ---------------- Система / интерфейс ----------------
        T("ui-dark", "Интерфейс", "Тёмная тема оформления",
          "Переключает систему в тёмный режим",
          "Apple Global Domain", "AppleInterfaceStyle", TYPE_STRING,
          "Dark", None, need_logout=False),
        T("ui-reduce-transparency", "Интерфейс", "Уменьшить прозрачность",
          "Помогает на старых Mac и улучшает читаемость",
          "com.apple.universalaccess", "reduceTransparency", TYPE_BOOL,
          True, False, need_logout=True),
        T("ui-reduce-motion", "Интерфейс", "Уменьшить движение",
          "Отключает параллакс и анимации Spaces",
          "com.apple.universalaccess", "reduceMotion", TYPE_BOOL, True, False,
          need_logout=True),
        T("ui-font-smoothing", "Интерфейс", "Сглаживание шрифтов (среднее)",
          "AppleFontSmoothing: 0=выкл, 1=лёгкое, 2=среднее, 3=сильное",
          "Apple Global Domain", "AppleFontSmoothing", TYPE_INT, 2, None,
          need_logout=True),
        T("ui-key-repeat", "Интерфейс", "Быстрый повтор клавиш",
          "InitialKeyRepeat=15, KeyRepeat=2 — удобно в терминале и редакторах",
          "NSGlobalDomain", "KeyRepeat", TYPE_INT, 2, 6, need_logout=True),
        T("ui-beep", "Интерфейс", "Звук системных предупреждений",
          "Отключить надоедливый «бип»",
          "NSGlobalDomain", "com.apple.sound.beep.feedback", TYPE_BOOL,
          False, True),
        T("ui-startup-sound", "Интерфейс", "Звук при включении",
          "Классический аккорд при загрузке",
          "com.apple.loginwindow", "LoginSound", TYPE_BOOL, False, True),

        # ---------------- Безопасность и приватность ----------------
        T("sec-firewall", "Безопасность", "Включить файрвол",
          "Блокирует входящие соединения (нужен перезапуск loginwindow)",
          "com.apple.alf", "globalstate", TYPE_INT, 1, 0, need_logout=True,
          risky=True),
        T("sec-firewall-stealth", "Безопасность", "Скрытый режим файрвола",
          "Не отвечать на ICMP-пинг и закрытые порты",
          "com.apple.alf", "allowstealthmode", TYPE_INT, 1, 0,
          need_logout=True, risky=True),
        T("sec-guest", "Безопасность", "Отключить гостевой вход",
          "GuestEnabled = 0",
          "com.apple.loginwindow", "GuestEnabled", TYPE_BOOL, False, True,
          need_logout=True),
        T("sec-screensaver-password", "Безопасность", "Пароль сразу после сна",
          "askForPassword=1, askForPasswordDelay=0",
          "com.apple.screensaver", "askForPassword", TYPE_INT, 1, 0),
        T("sec-bonjour", "Безопасность", "Отключить Bonjour-обнаружение",
          "Меньше «шума» в локальной сети",
          "com.apple.mDNSResponder", "NoMulticastAdvertisements", TYPE_BOOL,
          True, False, need_logout=True, risky=True),

        # ---------------- Производительность ----------------
        T("perf-turbo", "Производительность", "Отключить turbo boost (Intel)",
          "Меньше нагрев и троттлинг; на Apple Silicon не применяется",
          "com.apple.TurboBoost", "Enabled", TYPE_BOOL, False, True,
          risky=True),
        T("perf-ram-disks", "Производительность", "Не создавать RAM-диски Time Machine",
          "Отключает временные диски локальных снапшотов",
          "com.apple.TimeMachine", "DoNotOfferNewDisksForBackup", TYPE_BOOL,
          True, False, risky=True),
        T("perf-local-snapshots", "Производительность", "Локальные снапшоты TM",
          "Выключение освобождает место, но уменьшает защиту данных",
          "com.apple.TimeMachine", "AutoBackup", TYPE_BOOL, False, True,
          risky=True),
        T("perf-sudden-motion", "Производительность", "Датчик падения (HDD)",
          "Актуально только для Mac с жёстким диском",
          "com.apple.sudden_motion", "sms", TYPE_INT, 0, 1, risky=True),

        # ---------------- Прочее ----------------
        T("misc-quicklook-text", "Прочее", "Выделять текст в Quick Look",
          "Можно копировать текст из предпросмотра",
          "com.apple.finder", "QLEnableTextSelection", TYPE_BOOL, True, False),
        T("misc-spring-load", "Прочее", "Открытие папок перетаскиванием",
          "Spring-loading с небольшой задержкой",
          "NSGlobalDomain", "com.apple.springing.enabled", TYPE_BOOL,
          True, False),
        T("misc-hotcorner-tl", "Прочее", "Горячий угол: показать рабочий стол",
          "Левый верхний угол → рабочий стол",
          "com.apple.dock", "wvous-tl-corner", TYPE_INT, 4, 0, restart="Dock"),
        T("misc-hotcorner-br", "Прочее", "Горячий угол: блокировка экрана",
          "Правый нижний угол → заблокировать экран",
          "com.apple.dock", "wvous-br-corner", TYPE_INT, 13, 0, restart="Dock"),
        T("misc-rescue-sleep", "Прочее", "Не спать при подключённом питании",
          "Удобно для загрузок и долгих сборок",
          "com.apple.PowerManagement", "Sleep On Power Button", TYPE_BOOL,
          False, True, risky=True),
    ]


def all_tweaks() -> List[Tweak]:
    return _all_tweaks()


def sections(tweaks: Sequence[Tweak]) -> List[str]:
    out: List[str] = []
    for t in tweaks:
        if t.section not in out:
            out.append(t.section)
    return out


# --------------------------------------------------------------------------- #
#  Чтение/запись defaults
# --------------------------------------------------------------------------- #

def _fmt_value(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def read_state(t: Tweak) -> Tuple[bool, str]:
    """(включено ли, сырое значение)."""
    code, out = run(["defaults", "read", t.domain, t.key], timeout=15)
    if code != 0:
        # ключ не задан → считаем состоянием «по умолчанию»
        return False, "(не задано)"
    raw = (out or "").strip()
    want = _fmt_value(t.on_value)
    got = raw
    if t.vtype == TYPE_BOOL:
        got = "1" if raw.lower() in ("1", "true", "yes") else "0"
    return got == want, raw


def refresh(tweaks: Sequence[Tweak], progress=None) -> None:
    for i, t in enumerate(tweaks):
        if progress:
            progress(i, len(tweaks), t.name)
        t.state, t.raw = read_state(t)


def apply(tweaks: Sequence[Tweak], on: bool, progress=None,
          dry_run: bool = False) -> List[Tuple[Tweak, bool, str]]:
    """Применить (on=True) или откатить (on=False) список твиков."""
    res: List[Tuple[Tweak, bool, str]] = []
    restarts: Dict[str, bool] = {}
    for i, t in enumerate(tweaks):
        if progress:
            progress(i, len(tweaks), t.name)
        value = t.on_value if on else t.off_value
        if dry_run:
            res.append((t, True, f"будет записано {t.domain} {t.key} = {value}"))
            continue
        if value is None and not on:
            code, out = run(["defaults", "delete", t.domain, t.key], timeout=15)
            ok = code == 0 or "does not exist" in out
            res.append((t, ok, tr("ключ удалён (значение по умолчанию)") if ok
                        else tr("не удалось удалить: {err}").format(err=out[:60])))
        else:
            args = ["defaults", "write", t.domain, t.key]
            if t.vtype == TYPE_BOOL:
                args += ["-bool", "true" if value else "false"]
            elif t.vtype == TYPE_INT:
                args += ["-int", str(int(value))]
            elif t.vtype == TYPE_FLOAT:
                args += ["-float", str(float(value))]
            else:
                sval = str(value)
                if sval.startswith("~"):
                    sval = str(Path(sval).expanduser())
                args += ["-string", sval]
            code, out = run(args, timeout=15)
            res.append((t, code == 0, "ok" if code == 0 else (out or "ошибка")[:80]))
        if t.restart:
            restarts[t.restart] = True
        t.state = bool(on) if value is not None else False

    for app in restarts:
        if not dry_run:
            run(["killall", app], timeout=20)
    return res


def export_defaults(paths: Paths) -> Tuple[bool, str]:
    """Сохранить все настройки пользователя в ~/.mac_tweaker/defaults-<дата>.plist."""
    d = paths.state_dir
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False, f"не удалось создать {d}"
    out_file = d / f"defaults-{time.strftime('%Y%m%d-%H%M%S')}.plist"
    code, out = run(["defaults", "export", str(out_file), "-all"], timeout=120)
    if code == 0 and safe_exists(out_file):
        size = out_file.stat().st_size
        return True, tr("сохранено {path} ({size} КБ)").format(
            path=paths.short(out_file), size=size // 1024)
    return False, tr("ошибка экспорта: {err}").format(err=out[:120])


def list_backups(paths: Paths) -> List[Path]:
    import glob
    return sorted((Path(x) for x in glob.glob(str(paths.state_dir / "defaults-*.plist"))),
                  key=lambda p: p.stat().st_mtime if safe_exists(p) else 0,
                  reverse=True)


def import_defaults(paths: Paths, backup: Optional[Path] = None) -> Tuple[bool, str]:
    backups = list_backups(paths)
    if backup is None:
        if not backups:
            return False, tr("Резервных копий настроек не найдено.")
        backup = backups[0]
    code, out = run(["defaults", "import", str(backup)], timeout=180)
    if code == 0:
        return True, tr("настройки восстановлены из {name} (нужен выход из системы)") \
            .format(name=backup.name)
    return False, tr("ошибка импорта: {err}").format(err=out[:120])
