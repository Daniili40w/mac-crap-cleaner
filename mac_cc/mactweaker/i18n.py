"""
mactweaker.i18n — двуязычный интерфейс (RU / EN).

Принцип: весь код и данные пишутся по-русски (исходный язык проекта),
а пользовательские строки оборачиваются в tr(...). При языке "en" строка
ищется в каталоге RU→EN; если перевода нет — показывается оригинал
(деградация мягкая, ничего не ломается).

Выбор языка:
  * флаг CLI/TUI:  --lang ru | --lang en
  * переменная окружения MACC_LANG
  * сохранённый выбор в ~/.mac_tweaker/config.json  {"lang": "en"}
  * если ничего нет и stdin — терминал: интерактивный вопрос при старте
    (ровно тот экран, что просил пользователь):

        Mac Crap Cleaner
        Select language / Выберите язык
          1. Русский
          2. English
        Select [1/2]:
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional

LANGS = ("ru", "en")
_current: str = "ru"

#: Имя продукта: заголовок окна терминала, шапка кадров, документация.
APP_TITLE = "Mac Crap Cleaner"
APP_SHORT = "MacCC"

# --------------------------------------------------------------------------- #
#  Каталог переводов RU → EN
# --------------------------------------------------------------------------- #

CATALOG: Dict[str, str] = {
    # ---- общее / шапка ----
    "главное меню": "main menu",
    "назад": "back",
    "справка": "help",
    "о системе": "system info",
    "Да": "Yes",
    "Нет": "No",
    "Отмена": "Cancel",
    "Продолжить?": "Continue?",
    "Отменено": "Cancelled",
    "Готово": "Done",
    "ОК": "OK",
    "система": "system",
    "живое": "alive",
    "утилита": "tool",

    # ---- главное меню: пункты ----
    "Очистка кэшей и мусора": "Cache & junk cleanup",
    "системные и пользовательские кэши, логи, crash-отчёты":
        "system and user caches, logs, crash reports",
    "Глубокий скан хлама": "Deep junk scan",
    ".DS_Store, __pycache__, логи, краш-дампы, установщики":
        ".DS_Store, __pycache__, logs, crash dumps, installers",
    "Остатки удалённых программ": "Leftovers of uninstalled apps",
    "«сироты» в Application Support, Caches, Preferences…":
        "orphans in Application Support, Caches, Preferences…",
    "Автозагрузка": "Startup items",
    "LaunchAgents/LaunchDaemons и элементы входа":
        "LaunchAgents/LaunchDaemons and login items",
    "Настройки системы": "System settings",
    "Finder, Dock, скриншоты, приватность (обратимо)":
        "Finder, Dock, screenshots, privacy (reversible)",
    "Анализ диска": "Disk analysis",
    "что занимает место: каталоги и крупные файлы":
        "what takes space: folders and large files",
    "Журнал и откат": "Log & undo",
    "что сделано в этой и прошлых сессиях":
        "what was done in this and previous sessions",
    "горячие клавиши и правила безопасности":
        "hotkeys and safety rules",

    # ---- заголовки экранов (subtitle) ----
    "очистка кэшей": "cache cleanup",
    "глубокий скан хлама": "deep junk scan",
    "остатки удалённых программ": "leftovers of uninstalled apps",
    "автозагрузка": "startup items",
    "настройки системы": "system settings",
    "анализ диска": "disk analysis",
    "журнал и откат": "log & undo",

    # ---- подсказки: клавиши ----
    "Пробел": "Space",
    "Esc": "Esc",
    "Enter": "Enter",
    "Tab": "Tab",
    "Backspace": "Backspace",
    "↑↓": "↑↓",
    "PgUp PgDn": "PgUp PgDn",
    "Home End": "Home End",
    "?": "?",
    "F1": "F1",
    "{d} дн. {h} ч.": "{d} d {h} h",
    "{h} ч. {m} мин.": "{h} h {m} min",
    "{m} мин.": "{m} min",

    # ---- подсказки (значения; клавиши капсом автоматически) ----
    "выбор": "select",
    "открыть": "open",
    "отметить": "toggle",
    "всё": "all",
    "очистить": "clean",
    "удалить": "delete",
    "скан": "scan",
    "обновить": "refresh",
    "фильтр": "filter",
    "фильтр риска": "risk filter",
    "профиль": "profile",
    "жёсткое удаление": "hard delete",
    "отключить": "disable",
    "включить": "enable",
    "откатить": "revert",
    "внутрь": "enter",
    "наверх": "up",
    "крупные файлы": "big files",
    "прокрутка": "scroll",
    "откат последней сессии": "undo last session",
    "откат автозагрузки": "restore startup",
    "показать в Finder": "reveal in Finder",
    "экспорт": "export",
    "переключить": "switch",

    # ---- очистка кэшей ----
    "профиль: {profile} • старше {days} дн. • удаление: {mode}":
        "profile: {profile} • older than {days} d • delete: {mode}",
    " профиль: {profile} • старше {days} дн. • удаление: {mode} ":
        " profile: {profile} • older than {days} d • delete: {mode} ",
    "ИТОГО": "TOTAL",
    "Установлено программ: {n}": "Installed apps: {n}",
    "в Корзину": "to Trash",
    "жёсткое (rm)": "hard (rm)",
    "Нажмите «s», чтобы просканировать диск.":
        "Press “s” to scan the disk.",
    "p — сменить профиль,  i — фильтр по возрасту":
        "p — change profile,  i — age filter",
    "Найдено {n} целей на {size} — отметьте нужное и нажмите «x»":
        "Found {n} targets totaling {size} — mark what you need and press “x”",
    "отмечено: {n} целей, {size}, файлов: {files}":
        "selected: {n} targets, {size}, files: {files}",
    "Ничего не отмечено": "Nothing is selected",
    "Целей: {n}   Объём: {size}": "Targets: {n}   Size: {size}",
    "Способ: ": "Method: ",
    "перемещение в Корзину (обратимо)": "move to Trash (reversible)",
    "ЖЁСТКОЕ УДАЛЕНИЕ (rm -rf) — необратимо!": "HARD DELETE (rm -rf) — irreversible!",
    "Часть целей системные — потребуется пароль sudo.":
        "Some targets are system-wide — sudo password required.",
    "Очистка": "Cleanup",
    "Освобождено {size}": "Freed {size}",
    "Корзина: ": "Trash: ",
    "очищается отдельно": "cleaned separately",
    "не использовалась": "not used",
    "Режим удаления: ": "Delete mode: ",
    "в Корзину (обратимо)": "to Trash (reversible)",
    "Профиль: {profile}. Нажмите «s» для сканирования":
        "Profile: {profile}. Press “s” to scan",
    "Фильтр ~/Downloads: старше {days} дн.":
        "~/Downloads filter: older than {days} d",

    # ---- глубокий скан ----
    " уровень: {risk} • глубина {depth} • старше {days} дн. ":
        " level: {risk} • depth {depth} • older than {days} d ",
    "только безопасное": "safe only",
    "безопасное + спорное": "safe + questionable",
    "всё, включая советы": "everything, incl. advice",
    "Ищет то, что программы раскидали по домашнему каталогу:":
        "Looks for stuff programs scattered around your home directory:",
    ".DS_Store • __pycache__ • *.pyc • кэши линтеров":
        ".DS_Store • __pycache__ • *.pyc • linter caches",
    "логи • краш-дампы • .dmg/.pkg • кэши сборки":
        "logs • crash dumps • .dmg/.pkg • build caches",
    " — начать сканирование ": " — start scanning ",
    "(занимает от 10 секунд до пары минут)": "(takes 10 seconds to a few minutes)",
    "Не трогает: node_modules, .venv, .git, Library, ваши документы и проекты.":
        "Skips: node_modules, .venv, .git, Library, your documents and projects.",
    "Найдено {n} объектов; безопасного мусора на {size}":
        "Found {n} items; safe junk totals {size}",
    "отмечено: {n} объектов на {size}": "selected: {n} items totaling {size}",
    "Объектов: {n}   Объём: {size}": "Items: {n}   Size: {size}",
    "Всё будет перемещено в Корзину (обратимо).":
        "Everything will be moved to Trash (reversible).",
    "Спорных элементов: {n} — проверьте список!":
        "Questionable items: {n} — review the list!",
    "Удаление хлама": " Junk deletion",
    "Удаление хлама ": "Junk deletion ",
    "Уровень изменён — нажмите «s» для нового скана":
        "Level changed — press “s” for a new scan",

    # ---- остатки программ ----
    " фильтр: {name} ": " filter: {name} ",
    "только сироты": "orphans only",
    "сироты + неясные и устаревшие": "orphans + unclear & stale",
    "всё, включая системные": "everything, incl. system",
    "Ищет данные программ, которых на этом Mac уже нет.":
        "Finds data left behind by apps that are no longer on this Mac.",
    "Проверяются: Application Support, Caches, Preferences,":
        "Scanned: Application Support, Caches, Preferences,",
    "Containers, Group Containers, HTTPStorages, WebKit,":
        "Containers, Group Containers, HTTPStorages, WebKit,",
    "Application Scripts, Cookies, Logs, Saved Application State,":
        "Application Scripts, Cookies, Logs, Saved Application State,",
    "Internet Plug-Ins, ~/.config, ~/.cache, ~/.local/share,":
        "Internet Plug-Ins, ~/.config, ~/.cache, ~/.local/share,",
    "а также те же каталоги в /Library.":
        "and the same folders under /Library.",
    "Реестр живых программ: /Applications, ~/Applications,":
        "Registry of live apps: /Applications, ~/Applications,",
    "/System/Applications, Spotlight (mdfind) и запущенные процессы.":
        "/System/Applications, Spotlight (mdfind) and running processes.",
    " — сканировать   ": " — scan   ",
    " — фильтр": " — filter",
    "Элементы «неясно» по умолчанию не отмечаются: решение за вами.":
        "“Unclear” items are not pre-selected: the call is yours.",
    "Установлено программ: {n} • сирот: {orph} на {size}":
        "Installed apps: {n} • orphans: {orph} totaling {size}",
    "отмечено: {n} на {size}": "selected: {n} totaling {size}",
    "Из них «неясных»: {n} — убедитесь, что это действительно мусор!":
        "{n} of them are “unclear” — make sure it really is junk!",
    "Удаление остатков программ": "App leftovers deletion",
    "Всё перемещается в Корзину — можно вернуть.":
        "Everything goes to Trash — you can restore it.",
    "Фильтр: {name} — нажмите «s»": "Filter: {name} — press “s”",
    "читаю реестр установленных программ…":
        "reading the installed-app registry…",

    # ---- автозагрузка ----
    "агент пользователя": "user agent",
    "агент (все пользователи)": "agent (all users)",
    "демон (root)": "daemon (root)",
    "система (SIP)": "system (SIP)",
    "элемент входа": "login item",
    "фоновый элемент": "background item",
    "▶ работает": "▶ running",
    "● загружен": "● loaded",
    "○ остановлен": "○ stopped",
    "✗ падает": "✗ crashing",
    "— не загружен": "— not loaded",
    "⚠ битый": "⚠ broken",
    "⛔ отключён": "⛔ disabled",
    "все": "all",
    "только проблемные": "problematic only",
    "отключённые": "disabled",
    "агенты пользователя": "user agents",
    "Элементов: {n} • подозрительных: {bad}":
        "Items: {n} • suspicious: {bad}",
    "Отметьте элементы пробелом": "Mark items with Space",
    "Нельзя отключить": "Cannot disable",
    "Все отмеченные элементы защищены системой (SIP) или являются критическими.":
        "All selected items are SIP-protected or critical.",
    "Отключить элементов: {n}": "Disable {n} item(s)",
    "Они будут сняты с launchd, а их plist-файлы перенесены в":
        "They will be unloaded from launchd and their plists moved to",
    "~/.mac_tweaker/disabled/ — включение восстанавливает всё обратно.":
        "~/.mac_tweaker/disabled/ — enabling restores everything back.",
    "Есть демоны root — потребуется пароль sudo.":
        "There are root daemons — sudo password required.",
    "Защищённых пропущено: {n}": "Protected skipped: {n}",
    "Отключение автозагрузки": "Startup disable",
    "Отключено: {ok} из {total}": "Disabled: {ok} of {total}",
    "Пропущено защищённых: {n}": "Protected skipped: {n}",
    "Вернуть: отметьте и нажмите «e»": "Restore: mark and press “e”",
    "Включено: {ok} из {total}": "Enabled: {ok} of {total}",
    "Включение": "Enable",
    "Нет отключённых элементов": "No disabled items",
    "исполняемый файл отсутствует — программа удалена":
        "executable is missing — the app was uninstalled",
    "запускается по требованию, а не при входе":
        "runs on demand, not at login",
    "загружен, но завершился с кодом {code}": "loaded but exited with code {code}",
    "возможное назначение: {what}": "likely purpose: {what}",
    "обновлятор": "updater",
    "проверка лицензии": "license check",
    "агент синхронизации": "sync agent",
    "сбор телеметрии": "telemetry",
    "отчёты об использовании": "usage reports",
    "краш-репортер": "crash reporter",
    "отключён, резервная копия: {path}": "disabled, backup: {path}",
    "отключён через Mac Crap Cleaner": "disabled by Mac Crap Cleaner",
    " plist не найден на диске": " plist not found on disk",
    "нет прав на перемещение plist": "no permission to move the plist",
    "нет прав на перемещение plist (нужен sudo)":
        "no permission to move the plist (sudo needed)",
    "защищённый/системный элемент — нельзя отключать":
        "protected/system item — cannot be disabled",
    "элементы входа добавляются в Системных настройках":
        "login items are added in System Settings",
    "резервная копия plist не найдена": "plist backup not found",
    "элемент уже на месте": "item is already in place",
    "не удалось вернуть plist на место": "could not restore the plist",
    "элемент входа удалён": "login item removed",
    "Подозрительные (мёртвый груз)": "Suspicious (dead weight)",

    # ---- детали элемента ----
    "Тип": "Type",
    "Состояние": "State",
    "Путь": "Path",
    "Команда": "Command",
    "Разработчик": "Developer",
    "Приложение": "App",
    "RunAtLoad": "RunAtLoad",
    "KeepAlive": "KeepAlive",
    "Размер plist": "plist size",
    "Изменён": "Modified",
    "Защита": "Protection",
    "нельзя отключать (системный)": "cannot disable (system)",
    "можно отключать": "can be disabled",
    " Заметки ": " Notes ",
    "не подписан / неизвестно": "unsigned / unknown",
    "Отключение сохраняет plist в ~/.mac_tweaker/disabled/ — это обратимо.":
        "Disabling keeps the plist in ~/.mac_tweaker/disabled/ — reversible.",
    "элемент автозагрузки": "startup item",
    "Открыто в Finder": "Revealed in Finder",

    # ---- настройки ----
    " обратимые настройки через defaults ": " reversible settings via defaults ",
    "Твиков: {n} • уже включено: {on}": "Tweaks: {n} • already on: {on}",
    "отмечено: {n}   ": "selected: {n}   ",
    "Enter — включить": "Enter — apply",
    "Backspace — вернуть как было": "Backspace — revert",
    "Отметьте твики пробелом": "Mark tweaks with Space",
    "Твиков: {n} → {action}": "Tweaks: {n} → {action}",
    "включить": "apply",
    "вернуть в исходное": "revert",
    "Есть рискованные: {n} — прочитайте описания!":
        "Risky ones: {n} — read the descriptions!",
    "Потребуется выход из системы: {n}": "Requires logout: {n}",
    "Настройки системы ": "System settings ",
    "Применить": "Apply",
    "Применено: {ok} из {total}": "Applied: {ok} of {total}",
    "Откачено: {ok} из {total}": "Reverted: {ok} of {total}",
    "Часть изменений заработает после выхода из системы.":
        "Some changes take effect after logout.",
    "экспортирую defaults…": "exporting defaults…",
    "Экспорт": "Export",
    "Импорт": "Import",
    "Резервных копий настроек не найдено.": "No settings backups found.",
    "Сначала нажмите «x» (экспорт).": "Press “x” (export) first.",
    "Восстановить из {name}?": "Restore from {name}?",
    "Текущие настройки будут перезаписаны.":
        "Current settings will be overwritten.",
    "Восстановить": "Restore",
    "настройки: {ids}": "settings: {ids}",

    # ---- диск / инфо ----
    "Занято": "Used",
    "свободно": "free",
    " Крупнейшие каталоги дома ": " Largest home folders ",
    " Система ": " System ",
    "нажмите «t», чтобы посчитать (может занять минуту)":
        "press “t” to compute (may take a minute)",
    "Посчитано: {n} каталогов": "Computed: {n} folders",
    "Данные обновлены": "Data refreshed",
    "считаю {path}…": "measuring {path}…",
    "считаю размеры каталогов…": "measuring folder sizes…",
    " Крупные файлы ": " Large files ",

    # ---- журнал ----
    " журнал: {path} ": " journal: {path} ",
    "── Отключённая автозагрузка • {n}": "── Disabled startup items • {n}",
    "── Журнал действий • {n} записей": "── Action journal • {n} entries",
    "Журнал обновлён": "Journal refreshed",
    "Откат удаления": "Undo deletion",
    "Вернуть из Корзины всё, что удалял Mac Crap Cleaner":
        "Restore everything Mac Crap Cleaner moved to Trash",
    "в этой сессии?": "in this session?",
    "Работает только для удаления в Корзину.":
        "Only works for Trash-based deletion.",
    "Вернуть": "Restore",
    "Восстановлено из Корзины: {n}": "Restored from Trash: {n}",
    "проблем: {n}": "problems: {n}",
    "Восстановление автозагрузки": "Startup restore",
    "Вернуть {n} отключённых элементов?": "Restore {n} disabled items?",
    "Включено обратно: {ok} из {total}": "Restored: {ok} of {total}",
    "Нет отключённых элементов автозагрузки": "No disabled startup items",

    # ---- советы главного меню ----
    "Сначала сканируйте («s»), потом удаляйте («x») — вы увидите объёмы заранее.":
        "Scan first (“s”), delete later (“x”) — you’ll see sizes upfront.",
    "Всё удалённое попадает в Корзину: пункт «Журнал и откат» → «u» вернёт файлы.":
        "Everything deleted goes to Trash: “Log & undo” → “u” brings files back.",
    "Экран «Остатки удалённых программ» обычно даёт больше всего места после кэшей.":
        "The “Leftovers” screen usually frees the most space after caches.",
    "В автозагрузке ищите элементы со статусом «⚠ битый» — программа удалена, а запись грузится впустую.":
        "In startup items look for “⚠ broken” — the app is gone but the entry still loads.",
    "Перед массовым применением настроек нажмите «x» — это экспортирует все defaults в бэкап.":
        "Before applying settings en masse press “x” — it exports all defaults to a backup.",
    "Профиль aggressive чистит кэши браузеров — закройте их заранее, иначе часть файлов останется.":
        "The aggressive profile cleans browser caches — quit browsers first or some files stay.",
    "Системные кэши помечены ⚿ и требуют прав администратора (sudo).":
        "System caches are marked ⚿ and need admin rights (sudo).",
    "«Глубокий скан» не трогает node_modules, .venv, .git, Documents и Desktop.":
        "Deep scan never touches node_modules, .venv, .git, Documents or Desktop.",
    " Совет ": " Tip ",

    # ---- статусы очистки ----
    "освобождено: {size}": "freed: {size}",
    "не удалось: {n}": "failed: {n}",
    "пропущено (нет прав): {n}": "skipped (no rights): {n}",
    "ошибок: {n}": "errors: {n}",
    "sudo недоступен — системные кэши будут пропущены":
        "sudo unavailable — system caches will be skipped",
    "системные кэши пропущены (нужен --sudo)":
        "system caches skipped (--sudo needed)",
    "Корзина очищена: −{size}": "Trash emptied: −{size}",
    "Не удалось очистить Корзину": "Could not empty the Trash",
    "Освобождено за сессию: {size}": "Freed this session: {size}",
    "Диск: ": "Disk: ",
    "занято": "used",

    # ---- категории мусора ----
    "Система": "System",
    "Пользователь": "User",
    "Разработка": "Development",
    "Браузеры": "Browsers",
    "Приложения": "Apps",
    "Своё": "Custom",
    "Корзина": "Trash",

    # ---- имена целей очистки ----
    "Системные кэши (/Library/Caches)": "System caches (/Library/Caches)",
    "Кэш общесистемных сервисов. Нужен пароль администратора.":
        "System-wide service caches. Admin password required.",
    "Ротированные системные логи": "Rotated system logs",
    "Сжатые/старые логи. Активные не трогаются.":
        "Compressed/old logs. Active ones untouched.",
    "Системные отчёты об ошибках": "System diagnostic reports",
    "Краш-логи общесистемных процессов.": "Crash logs of system processes.",
    "Кэш установщиков macOS": "macOS installer cache",
    "Скачанные, но уже применённые обновления системы.":
        "Downloaded updates that were already applied.",
    "Кэши пользователя (~/Library/Caches)": "User caches (~/Library/Caches)",
    "Главный источник мусора. Приложения пересоздадут кэш сами.":
        "The main junk source. Apps recreate caches themselves.",
    "Краш-логи и отчёты приложений": "App crash logs & reports",
    "Crash-репорты: полезны только для отладки.":
        "Crash reports: only useful for debugging.",
    "Логи приложений (~/Library/Logs)": "App logs (~/Library/Logs)",
    "Только файлы .log/.old/.gz, не сами каталоги.":
        "Only .log/.old/.gz files, not the folders themselves.",
    "Сохранённые состояния окон": "Saved window states",
    "Списки открытых окон/вкладок. Безвредно.":
        "Lists of open windows/tabs. Harmless.",
    "Кэш QuickLook (миниатюры)": "QuickLook cache (thumbnails)",
    "Кэш иконок и шрифтов": "Icon & font cache",
    "Кэш WebKit/HTTPStorages": "WebKit/HTTPStorages cache",
    "Только файлы cookies-кэша, не каталоги сессий.":
        "Only cookie-cache files, not session folders.",
    "Кэш контейнеров (Caches внутри Containers)":
        "Container caches (Caches inside Containers)",
    "Кэш песочных приложений; сами данные не трогаются.":
        "Sandboxed app caches; app data untouched.",
    "Xcode DerivedData": "Xcode DerivedData",
    "Артефакты сборки. Первая сборка будет дольше.":
        "Build artifacts. First build will be slower.",
    "Xcode Archives": "Xcode Archives",
    "Архивы сборок для публикации. Удаляйте, только если не нужны!":
        "Archives for publishing. Delete only if you don’t need them!",
    "Xcode iOS DeviceSupport": "Xcode iOS DeviceSupport",
    "Отладочные символы; скачаются заново при подключении устройства.":
        "Debug symbols; re-downloaded when a device connects.",
    "Xcode UserData (кэш интерфейса)": "Xcode UserData (interface cache)",
    "Кэш симуляторов iOS": "iOS simulator cache",
    "Кэш CocoaPods": "CocoaPods cache",
    "Кэш RubyGems": "RubyGems cache",
    "Кэш Python (pip/poetry/mypy/pytest/ruff)": "Python cache (pip/poetry/mypy/pytest/ruff)",
    "Кэш Node.js (npm/yarn/pnpm)": "Node.js cache (npm/yarn/pnpm)",
    "Кэш Go": "Go cache",
    "Кэш Rust (cargo)": "Rust cache (cargo)",
    "Кэш Gradle / Maven": "Gradle / Maven cache",
    "Maven-репозиторий скачается заново при сборке.":
        "The Maven repo re-downloads on next build.",
    "Кэш PHP Composer": "PHP Composer cache",
    "Кэши IDE JetBrains": "JetBrains IDE caches",
    "Индексы проектов: переиндексируются при запуске (займёт время).":
        "Project indexes: re-indexed on launch (takes a while).",
    "Кэш VS Code / Cursor": "VS Code / Cursor cache",
    "Только кэш: настройки и расширения не трогаются.":
        "Cache only: settings and extensions untouched.",
    "Кэш Android SDK / эмуляторов": "Android SDK / emulator cache",
    "Кэш Unity": "Unity cache",
    "Safari (кэш, иконки)": "Safari (cache, icons)",
    "Закройте Safari. Пароли, вкладки и история НЕ трогаются.":
        "Quit Safari. Passwords, tabs and history are NOT touched.",
    "Google Chrome (Cache/Code Cache/GPUCache)": "Google Chrome (Cache/Code Cache/GPUCache)",
    "Закройте Chrome. Пароли и закладки НЕ трогаются.":
        "Quit Chrome. Passwords and bookmarks are NOT touched.",
    "Edge / Brave / Arc / Vivaldi / Opera": "Edge / Brave / Arc / Vivaldi / Opera",
    "Firefox (cache2, shader-cache)": "Firefox (cache2, shader-cache)",
    "Кэш мессенджеров, почты, музыки": "Messenger, mail & music cache",
    "Кэш облачных клиентов": "Cloud client cache",
    "Кэш Adobe / офисных пакетов": "Adobe / office suite cache",
    "Только кэш-каталоги, не лицензии и не настройки.":
        "Cache folders only — not licenses, not settings.",
    "Старые установщики в ~/Downloads": "Old installers in ~/Downloads",
    "Файлы .dmg/.pkg/.zip и т.п. старше {days} дн.":
        ".dmg/.pkg/.zip and similar older than {days} d.",
    "Каталог {name}": "Folder {name}",
    "Добавлен через --include-dir": "Added via --include-dir",
    "Homebrew cleanup": "Homebrew cleanup",
    "Удаляет старые версии формул и кэш загрузок.":
        "Removes old formula versions and download cache.",
    "Docker: висячие образы и кэш сборки": "Docker: dangling images & build cache",
    "Остановленные контейнеры, dangling-образы, сети, build cache.":
        "Stopped containers, dangling images, networks, build cache.",
    "Недоступные симуляторы iOS": "Unavailable iOS simulators",
    "Симуляторы для удалённых версий runtime.":
        "Simulators for removed runtime versions.",
    "npm cache verify": "npm cache verify",
    "Проверка и уплотнение кэша npm.": "Verify and compact the npm cache.",
    "pip cache purge": "pip cache purge",
    "Go: очистка кэша сборки": "Go: clean build cache",
    "команда": "command",

    # ---- глубокий скан: правила ----
    "Системный мусор": "System junk",
    "Сборка": "Build",
    "Логи": "Logs",
    "Установщики": "Installers",
    "Архивы": "Archives",
    "Медиа": "Media",
    "Finder .DS_Store": "Finder .DS_Store",
    "Служебные файлы Finder: пересоздаются автоматически":
        "Finder service files: recreated automatically",
    "Служебные файлы Finder в защищённом каталоге":
        "Finder service files in a protected folder",
    "Метаданные AppleDouble": "AppleDouble metadata",
    "Файлы ._* после копирования с не-Mac томов":
        "._* files left after copying from non-Mac volumes",
    "Thumbs.db / desktop.ini": "Thumbs.db / desktop.ini",
    "Следы Windows-разделов": "Traces of Windows partitions",
    "__pycache__ / *.pyc": "__pycache__ / *.pyc",
    "Байткод Python: пересоздаётся при импорте":
        "Python bytecode: recreated on import",
    "Кэши линтеров и тестов": "Linter & test caches",
    "Пересоздаются при следующем запуске": "Recreated on the next run",
    "Кэш сборщика внутри node_modules": "Builder cache inside node_modules",
    "Кэш webpack/babel/vite — не сами зависимости":
        "webpack/babel/vite cache — not the dependencies themselves",
    "Артефакты сборки Maven/Gradle": "Maven/Gradle build artifacts",
    "target/ и build/ пересоберутся, но сборка займёт время":
        "target/ and build/ will rebuild, but builds take time",
    "Кэш сборки Xcode в проекте": "Xcode build cache in project",
    "xcuserdata и промежуточные данные": "xcuserdata and intermediate data",
    "Виртуальное окружение (.venv/venv)": "Virtual environment (.venv/venv)",
    "Удаляйте, только если проект больше не нужен":
        "Delete only if the project is no longer needed",
    "Файлы логов": "Log files",
    "Журналы внутри домашнего каталога": "Logs inside the home directory",
    "Краш-дампы": "Crash dumps",
    "Отчёты о падениях: нужны только для отладки":
        "Crash reports: only needed for debugging",
    "Установщики и образы дисков": "Installers & disk images",
    ".dmg/.pkg/.iso — после установки обычно не нужны":
        ".dmg/.pkg/.iso — usually useless after installation",
    "Старые архивы": "Old archives",
    ".zip/.rar/.7z/.tar — проверьте, распакованы ли они":
        ".zip/.rar/.7z/.tar — check whether they are unpacked",
    "Крупные видео и образы": "Large videos & images",
    "Только отчёт: решайте сами": "Report only: you decide",
    "безопасно": "safe",
    "спросить": "ask",
    "совет": "advice",

    # ---- вердикты сирот ----
    "СИРОТА": "ORPHAN",
    "неясно": "unclear",
    "устарело": "stale",
    "bundle id «{owner}» не найден среди установленных":
        "bundle id “{owner}” not found among installed apps",
    "приложение не найдено: {ids}": "app not found: {ids}",
    "компонент macOS": "macOS component",
    "служебный каталог macOS": "macOS service folder",
    "установлено: {bid}": "installed: {bid}",
    "установлено приложение «{name}»": "app “{name}” is installed",
    "похоже на установленное «{name}»": "looks like installed “{name}”",
    "данные утилиты {name}": "CLI tool data: {name}",
    "владелец не определён — не трогаем": "owner unknown — leaving alone",
    "не использовалось {days} дн.; владелец не определён":
        "unused for {days} d; owner unknown",
    "приложения вендора «{vendor}» установлены в системе":
        "apps from vendor “{vendor}” are installed",

    # ---- источники сирот ----
    "Application Support": "Application Support",
    "Caches": "Caches",
    "Preferences": "Preferences",
    "Preferences/ByHost": "Preferences/ByHost",
    "HTTPStorages": "HTTPStorages",
    "WebKit": "WebKit",
    "Application Scripts": "Application Scripts",
    "Containers": "Containers",
    "Group Containers": "Group Containers",
    "Cookies": "Cookies",
    "Logs": "Logs",
    "Saved Application State": "Saved Application State",
    "Internet Plug-Ins": "Internet Plug-Ins",
    "/Library/App Support": "/Library/App Support",
    "/Library/Caches": "/Library/Caches",
    "/Library/Preferences": "/Library/Preferences",
    "/Library/Internet Plug-Ins": "/Library/Internet Plug-Ins",
    "/Library/Logs": "/Library/Logs",
    ".config": ".config",
    ".cache": ".cache",
    ".local/share": ".local/share",

    # ---- твики: разделы ----
    "Finder": "Finder",
    "Скриншоты": "Screenshots",
    "Dock": "Dock",
    "Интерфейс": "Interface",
    "Безопасность": "Security",
    "Производительность": "Performance",
    "Прочее": "Misc",

    # ---- твики: имена ----
    "Показывать скрытые файлы": "Show hidden files",
    "Файлы и каталоги, начинающиеся с точки": "Dot-files and dot-folders",
    "Показывать расширения файлов": "Show file extensions",
    "Полезно видеть .sh/.command/.dmg": "Useful to see .sh/.command/.dmg",
    "Показывать строку пути": "Show path bar",
    "Полный путь к текущему каталогу внизу окна":
        "Full path of the current folder at the window bottom",
    "Показывать строку состояния": "Show status bar",
    "Число объектов и свободное место на диске":
        "Item count and free disk space",
    "Иконки на рабочем столе": "Desktop icons",
    "Выключите, если скриншоты должны быть чистыми":
        "Turn off if you need clean screenshots",
    "Внешние диски на рабочем столе": "External disks on desktop",
    "Показывать съёмные тома и сетевые диски":
        "Show removable volumes and network disks",
    "Недавние теги в меню": "Recent tags in menu",
    "Убирает замусоренный список тегов": "Removes the cluttered tag list",
    "Подтверждение очистки Корзины": "Confirm emptying the Trash",
    "Внимание: выключение уберёт предупреждающий диалог":
        "Warning: turning off removes the confirmation dialog",
    "Новые окна в домашнем каталоге": "New windows open in home",
    "Вместо «Недавние»": "Instead of “Recents”",
    "Сохранять скриншоты в ~/Pictures/Screenshots":
        "Save screenshots to ~/Pictures/Screenshots",
    "Перестаёт засорять рабочий стол (нужен перезапуск Finder)":
        "Stops cluttering the desktop (Finder restart needed)",
    "Без тени у окон": "No window shadow",
    "Скриншоты окон без декоративной тени":
        "Window screenshots without the decorative shadow",
    "Формат PNG": "PNG format",
    "PNG вместо JPEG (больше размер, выше качество)":
        "PNG instead of JPEG (bigger files, better quality)",
    "Задержка 0 секунд": "Zero-second delay",
    "Убирает задержку перед снимком": "Removes the pre-capture delay",
    "Скрывать Dock автоматически": "Auto-hide the Dock",
    "Освобождает ~70 px высоты экрана": "Frees ~70 px of screen height",
    "Компактный размер иконок (48 px)": "Compact icon size (48 px)",
    "Меньше иконки — больше места": "Smaller icons — more room",
    "Увеличение при наведении": "Magnification on hover",
    "Эффект лупы под курсором": "Loupe effect under the cursor",
    "Секция «Недавние программы»": "“Recent apps” section",
    "Выключение убирает лишние иконки справа":
        "Turning it off removes extra icons on the right",
    "Мгновенное появление (без анимации)": "Instant appearance (no animation)",
    "autohide-time-modifier = 0": "autohide-time-modifier = 0",
    "Тёмная тема оформления": "Dark appearance",
    "Переключает систему в тёмный режим": "Switches the system to dark mode",
    "Уменьшить прозрачность": "Reduce transparency",
    "Помогает на старых Mac и улучшает читаемость":
        "Helps on older Macs and improves readability",
    "Уменьшить движение": "Reduce motion",
    "Отключает параллакс и анимации Spaces":
        "Disables parallax and Spaces animations",
    "Сглаживание шрифтов (среднее)": "Font smoothing (medium)",
    "AppleFontSmoothing: 0=выкл, 1=лёгкое, 2=среднее, 3=сильное":
        "AppleFontSmoothing: 0=off, 1=light, 2=medium, 3=strong",
    "Быстрый повтор клавиш": "Fast key repeat",
    "InitialKeyRepeat=15, KeyRepeat=2 — удобно в терминале и редакторах":
        "InitialKeyRepeat=15, KeyRepeat=2 — handy in terminals and editors",
    "Звук системных предупреждений": "System alert sound",
    "Отключить надоедливый «бип»": "Disable the annoying beep",
    "Звук при включении": "Startup chime",
    "Классический аккорд при загрузке": "The classic chord at boot",
    "Включить файрвол": "Enable the firewall",
    "Блокирует входящие соединения (нужен перезапуск loginwindow)":
        "Blocks incoming connections (loginwindow restart needed)",
    "Скрытый режим файрвола": "Firewall stealth mode",
    "Не отвечать на ICMP-пинг и закрытые порты":
        "Don’t answer ICMP pings and closed ports",
    "Отключить гостевой вход": "Disable guest login",
    "GuestEnabled = 0": "GuestEnabled = 0",
    "Пароль сразу после сна": "Password right after sleep",
    "askForPassword=1, askForPasswordDelay=0":
        "askForPassword=1, askForPasswordDelay=0",
    "Отключить Bonjour-обнаружение": "Disable Bonjour advertising",
    "Меньше «шума» в локальной сети": "Less noise on the local network",
    "Отключить turbo boost (Intel)": "Disable turbo boost (Intel)",
    "Меньше нагрев и троттлинг; на Apple Silicon не применяется":
        "Less heat and throttling; not applicable on Apple Silicon",
    "Не создавать RAM-диски Time Machine": "Don’t create Time Machine RAM disks",
    "Отключает временные диски локальных снапшотов":
        "Disables temporary local-snapshot disks",
    "Локальные снапшоты TM": "TM local snapshots",
    "Выключение освобождает место, но уменьшает защиту данных":
        "Turning off frees space but weakens data protection",
    "Датчик падения (HDD)": "Sudden motion sensor (HDD)",
    "Актуально только для Mac с жёстким диском":
        "Only relevant for Macs with a spinning disk",
    "Выделять текст в Quick Look": "Select text in Quick Look",
    "Можно копировать текст из предпросмотра":
        "You can copy text from previews",
    "Открытие папок перетаскиванием": "Spring-loading folders",
    "Spring-loading с небольшой задержкой": "Spring-loading with a small delay",
    "Горячий угол: показать рабочий стол": "Hot corner: show desktop",
    "Левый верхний угол → рабочий стол": "Top-left corner → desktop",
    "Горячий угол: блокировка экрана": "Hot corner: lock screen",
    "Правый нижний угол → заблокировать экран":
        "Bottom-right corner → lock the screen",
    "Не спать при подключённом питании": "Don’t sleep on power",
    "Удобно для загрузок и долгих сборок":
        "Handy for downloads and long builds",

    # ---- сводка системы / шапка ----
    "Справка": "Help",
    "свободно {free} / {total}": "free {free} / {total}",
    "ядер: {n}  •  RAM: {total}, свободно {free}":
        "cores: {n}  •  RAM: {total}, free {free}",
    "хост: {host}  •  {user}  •  аптайм: {up}":
        "host: {host}  •  {user}  •  uptime: {up}",
    "{path}: свободно {free} из {total} ({pct}%)":
        "{path}: free {free} of {total} ({pct}%)",
    "sudo: активен": "sudo: active",
    "Каталоги": "Folders",
    "не найдено": "not found",
    "не очищена": "not cleaned",
    "всё в Корзине — можно вернуть или очистить её":
        "everything is in the Trash — restore or empty it",
    "всего найдено": "found in total",
    "Сирот не найдено.": "No orphans found.",
    "Нечего удалять (безопасных объектов нет).":
        "Nothing to delete (no safe items).",
    "Нечего отключать (все защищены).": "Nothing to disable (all protected).",
    "Укажите --label <часть имени> для отключения.":
        "Pass --label <name substring> to disable.",
    "не найдено — автозагрузка выглядит чистой":
        "none found — startup looks clean",
    "Использовать sudo для системных кэшей?":
        "Use sudo for system caches?",
    "Будет очищено": "Will be cleaned",
    "Итого": "Total",
    "ИТОГО можно освободить": "TOTAL reclaimable",
    "ИТОГО найдено": "TOTAL found",
    "Удалить {n} объектов ({size}) {mode}?":
        "Delete {n} items ({size}) {mode}?",
    "Удалить {n} остатков удалённых программ ({size})?":
        "Delete {n} leftovers of uninstalled apps ({size})?",
    "Из них «неясных»: {n} — убедитесь, что это действительно мусор!":
        "{n} of them are “unclear” — make sure it really is junk!",
    "Показывает всё, что запускается само:":
        "Shows everything that starts by itself:",
    "Помечены состояния: ▶ работает  ● загружен  ✗ падает":
        "States: ▶ running  ● loaded  ✗ crashing",
    "⚠ битый (программа удалена)  ⛔ отключён вами":
        "⚠ broken (app uninstalled)  ⛔ disabled by you",
    "Отключение обратимо: plist сохраняется в ~/.mac_tweaker/disabled/":
        "Disabling is reversible: the plist is kept in ~/.mac_tweaker/disabled/",
    " — собрать список   ": " — collect list   ",
    " — фильтр «проблемные»": " — “problematic” filter",
    "ключ удалён (значение по умолчанию)":
        "key deleted (default value restored)",
    "не удалось удалить: {err}": "could not delete: {err}",
    "сохранено {path} ({size} КБ)": "saved {path} ({size} KB)",
    "ошибка экспорта: {err}": "export error: {err}",
    "настройки восстановлены из {name} (нужен выход из системы)":
        "settings restored from {name} (logout required)",
    "ошибка импорта: {err}": "import error: {err}",
    "не использовалось {days} дн.; владелец не определён":
        "unused for {days} d; owner unknown",
    "── Отключённая автозагрузка • {n}": "── Disabled startup items • {n}",
    "── Журнал действий • {n} записей": "── Action journal • {n} entries",
    "Вернуть {n} отключённых элементов?": "Restore {n} disabled items?",
    "Включено обратно: {ok} из {total}": "Restored: {ok} of {total}",
    "Восстановление": "Restore",
    "Восстановлено из Корзины: {n}": "Restored from Trash: {n}",
    "проблем: {n}": "problems: {n}",
    "Вернуть из Корзины всё, что удалял Mac Crap Cleaner":
        "Restore everything Mac Crap Cleaner moved to Trash",
    "в этой сессии?": "in this session?",
    "Работает только для удаления в Корзину.":
        "Only works for Trash-based deletion.",
    "Резервных копий настроек не найдено.": "No settings backups found.",
    "Сначала нажмите «x» (экспорт).": "Press “x” (export) first.",
    "Восстановить из {name}?": "Restore from {name}?",
    "Текущие настройки будут перезаписаны.":
        "Current settings will be overwritten.",
    "Tweaks: {n}": "Tweaks: {n}",

    # ---- сменные надписи долгих операций ----
    "подождите пару минут, программа не зависла":
        "hang in there — the program has not frozen",
    "просматриваю файлы": "browsing files",
    "прохожусь по пыльным местам": "sweeping the dusty corners",
    "я почти закончил искать": "almost done searching",

    # ---- описания профилей очистки ----
    "кэши пользователя и системы, логи, crash-отчёты":
        "user and system caches, logs, crash reports",
    "+ Xcode, симуляторы, brew, pip/npm/go/cargo/gradle, IDE, Docker":
        "+ Xcode, simulators, brew, pip/npm/go/cargo/gradle, IDEs, Docker",
    "+ кэши браузеров, мессенджеров, облачных клиентов":
        "+ browser, messenger and cloud client caches",

    "окно уже 100 колонок: разверните его или запустите через .app (124×35)":
        "window is under 100 columns: enlarge it or launch via the .app (124×35)",
    "BTM: {what}": "BTM: {what}",
    "запуск от root: псевдографика отключена, доступен текстовый режим":
        "running as root: TUI disabled, text mode available",

    # ---- текстовое меню (без TTY) ----
    "Mac Crap Cleaner (MacCC) — текстовый режим (нет TTY)":
        "Mac Crap Cleaner (MacCC) — text mode (no TTY)",
    "Выбор: ": "Choice: ",
    "Очистка кэшей (scan)": "Cache cleanup (scan)",
    "Очистка кэшей разработчика": "Developer cache cleanup",
    "Глубокий скан хлама": "Deep junk scan",
    "Остатки удалённых программ": "Leftovers of uninstalled apps",
    "Автозагрузка: список": "Startup items: list",
    "Автозагрузка: подозрительные": "Startup items: suspicious",
    "Настройки: список": "Settings: list",
    "Анализ диска": "Disk analysis",
    "Информация о системе": "System information",
    "Выход": "Quit",

    # ---- выбор языка ----
    "Select language / Выберите язык": "Select language / Выберите язык",
    "Выбор языка": "Language selection",
    "Язык переключён: {lang}": "Language switched: {lang}",
    "язык": "language",
}

# Служебные строки, которые встречаются в данных как части фраз
EXTRA_KEYS = ()


def tr(text: str) -> str:
    """Перевести строку интерфейса. При языке ru возвращает как есть."""
    if _current == "ru" or not text:
        return text
    return CATALOG.get(text, text)


def _(text: str) -> str:
    return tr(text)


def get_lang() -> str:
    return _current


def set_lang(lang: str, persist: bool = True, paths=None) -> str:
    global _current
    lang = (lang or "ru").lower()
    if lang not in LANGS:
        lang = "ru"
    _current = lang
    if persist:
        try:
            cfg = config_path(paths)
            cfg.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if cfg.exists():
                try:
                    data = json.loads(cfg.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    data = {}
            data["lang"] = lang
            cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
        except OSError:
            pass
    return lang


def config_path(paths=None) -> Path:
    if paths is not None:
        return Path(paths.state_dir) / "config.json"
    home = os.environ.get("MACTWEAKER_HOME") or os.path.expanduser("~")
    return Path(home) / ".mac_tweaker" / "config.json"


def saved_lang(paths=None) -> Optional[str]:
    env = os.environ.get("MACC_LANG")
    if env in LANGS:
        return env
    try:
        data = json.loads(config_path(paths).read_text(encoding="utf-8"))
        lang = str(data.get("lang", "")).lower()
        return lang if lang in LANGS else None
    except (OSError, ValueError):
        return None


LANGUAGE_PROMPT = """Mac Crap Cleaner
Select language / Выберите язык
  1. Русский
  2. English
Select [1/2]: """


def ask_language() -> str:
    """Интерактивный выбор языка при первом запуске."""
    sys.stdout.write(LANGUAGE_PROMPT)
    sys.stdout.flush()
    try:
        ans = sys.stdin.readline().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return "ru"
    if ans in ("2", "en", "english"):
        return "en"
    return "ru"


def resolve_lang(cli_value: Optional[str] = None, paths=None,
                 interactive: bool = True) -> str:
    """Приоритет: --lang → MACC_LANG/config → интерактивный вопрос → ru."""
    if cli_value in LANGS:
        return set_lang(cli_value, persist=True, paths=paths)
    saved = saved_lang(paths)
    if saved:
        return set_lang(saved, persist=False, paths=paths)
    if interactive and sys.stdin.isatty() and sys.stdout.isatty():
        return set_lang(ask_language(), persist=True, paths=paths)
    return set_lang("ru", persist=False, paths=paths)
