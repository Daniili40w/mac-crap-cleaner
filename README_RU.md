# Mac Crap Cleaner (MacCC)

> Mac Crap Cleaner - Less crap. Zero subscriptions. No bullshit.

Псевдографический инструмент обслуживания macOS в терминале: очистка кэшей,
поиск «сирот» от удалённых программ, глубокий скан раскиданного хлама,
менеджер автозагрузки и обратимые настройки системы.

**Один язык — Python 3.8+, ноль сторонних зависимостей** (только стандартная
библиотека: `pathlib`, `plistlib`, `argparse`, `termios`, `zipfile`).
Псевдографика нарисована на ANSI-escape + `termios`, без `curses` и без `pip install`.

```
mac_tweaker/
├── maccc.py              # точка входа (TUI + CLI)
├── build_bundle.py             # сборка в один файл dist/maccc_bundle.py
├── mactweaker/
│   ├── __init__.py
│   ├── safety.py               # предохранители, stat-обёртки, Корзина, журнал
│   ├── system.py               # сведения о системе и дисках
│   ├── junk.py                 # кэши + глубокий скан хлама
│   ├── leftovers.py            # остатки удалённых программ («сироты»)
│   ├── startup.py              # LaunchAgents / LaunchDaemons / Login Items / BTM
│   ├── tweaks.py               # настройки через defaults (обратимо)
│   ├── ui.py                   # движок псевдографики (чистые функции рендера)
│   ├── app.py                  # экраны и главный цикл
│   └── cli.py                  # субкоманды для скриптов и cron
└── tests/
    ├── make_fake_home.sh       # стенд: фейковое «маковское» дерево
    ├── test_all.py             # 185 проверок (логика + CLI + рендер)
    ├── test_tui_pty.py         # 18 проверок: TUI в настоящем pty
    └── render_preview.py       # рендер экранов в текст/HTML
```

---

## Языки: RU / EN

При самом первом запуске (пока нет конфига) программа спрашивает язык ровно
так, как задумано:

```
Mac Crap Cleaner
Select language / Выберите язык
  1. Русский
  2. English
Select [1/2]:
```

Выбор сохраняется в `~/.mac_tweaker/config.json` и больше не спрашивается.
Дальше язык можно поменять тремя способами:

| Способ | Как |
|---|---|
| Клавиша в главном меню | `l` — переключает RU ↔ EN и сохраняет |
| Флаг | `maccc --lang en …` (работает и для TUI, и для CLI) |
| Окружение | `MACC_LANG=en maccc` |

Переведено всё: шапки вкладок, меню, подсказки клавиш, диалоги, статусы,
справка (отдельный английский текст), имена целей очистки, правила глубокого
скана, вердикты сирот, состояния автозагрузки, названия и описания твиков,
единицы измерения (`ГБ` → `GB`) и длительности (`1 дн. 2 ч.` → `1 d 2 h`).
Строка, для которой нет перевода, показывается по-русски — ничего не падает.
Предпросмотр обеих языковых версий: `dist/preview.html` и `dist/preview-en.html`.

## Быстрый старт

### Вариант 1 — один файл (рекомендуется)

Скачайте **`dist/maccc_bundle.py`** (109 КБ, все модули внутри) и запустите:

```bash
chmod +x maccc_bundle.py
python3 maccc_bundle.py
```

### Вариант 2 — проект целиком

```bash
cd mac_tweaker
python3 maccc.py
```

### Вариант 3 — положить в PATH

```bash
mkdir -p ~/bin
cp dist/maccc_bundle.py ~/bin/maccc
chmod +x ~/bin/maccc
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
maccc
```

Проверка: `maccc --version` → `maccc 2.1.0`.

---

## Псевдографическое меню

Запуск без аргументов открывает TUI на весь экран терминала:

```
 Mac Crap Cleaner                                        главное меню   свободно 41.2 ГБ / 465.7 ГБ
────────────────────────────────────────────────────────────────────────────────────────────────────
    ███╗   ███╗ █████╗  ██████╗   ██████╗  ███╗   ███╗              MacBookAir10,1  •  macOS 15.1
    ████╗ ████║██╔══██╗██╔════╝  ██╔════╝  ████╗ ████║   Apple M2  •  ядер: 8  •  RAM: 16.0 ГБ
    ██╔████╔██║███████║██║       ██║  ███╗ ██╔████╔██║   хост: MacBook-Air.local  •  air
    ██║╚██╔╝██║██╔══██║██║       ██║   ██║ ██║╚██╔╝██║        /: свободно 41.2 ГБ из 465.7 ГБ
    ██║ ╚═╝ ██║██║  ██║╚██████╗  ╚██████╔╝ ██║ ╚═╝ ██║             Homebrew  •  Python 3.9.6
    ╚═╝     ╚═╝╚═╝  ╚═╝ ╚═════╝   ╚═════╝  ╚═╝     ╚═╝

  Диск: ████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  91% занято

  ▸1  Очистка кэшей и мусора          системные и пользовательские кэши, логи, crash-отчёты
   2  Глубокий скан хлама             .DS_Store, __pycache__, логи, краш-дампы, установщики
   3  Остатки удалённых программ      «сироты» в Application Support, Caches, Preferences…
   4  Автозагрузка                    LaunchAgents/LaunchDaemons и элементы входа
   5  Настройки системы               Finder, Dock, скриншоты, приватность (обратимо)
   6  Анализ диска                    что занимает место: каталоги и крупные файлы
   7  Журнал и откат                  что сделано в этой и прошлых сессиях
   8  Справка                         горячие клавиши и правила безопасности
────────────────────────────────────────────────────────────────────────────────────────────────────
↑↓ выбор  Enter открыть  i о системе  Esc назад  ? справка
```

### Горячие клавиши

| Клавиша | Действие |
|---|---|
| `↑ ↓` / `j k` | перемещение по списку (заголовки групп перескакиваются в обе стороны) |
| `PgUp` `PgDn` `Home` `End` | навигация по страницам |
| `Пробел` | отметить / снять отметку |
| `a` | отметить всё ↔ снять всё |
| `Enter` | открыть, подтвердить, применить |
| `s` `r` | сканировать / обновить |
| `x` | выполнить действие над отмеченным |
| `d` / `e` | отключить / включить элемент автозагрузки |
| `u` | откатить удаление (вернуть из Корзины) |
| `i` `p` `Tab` `o` | фильтры, профиль, режим удаления |
| `?` `F1` | справка |

Подсказки клавиш внизу экрана и колонка клавиш в справке набраны КАПСОМ;
регистр нажатия не важен (`S` и `s` — одна клавиша).
| `Esc` `q` | назад / выход |

Интерфейс адаптируется к ширине терминала, переживает ресайз окна (`SIGWINCH`),
а при `--ascii` или в терминале без UTF-8 переходит на чистую ASCII-псевдографику.

Долгие операции (анализ диска, глубокий скан, поиск сирот) выполняются **в фоновом
потоке**: интерфейс всё это время рисует анимированный прогресс-бар из символов
`| / - \` (barber-pole, бежит даже когда объём работы ещё неизвестен) и каждые
10 секунд меняет надпись: «подождите пару минут, программа не зависла» →
«просматриваю файлы» → «прохожусь по пыльным местам» → «я почти закончил искать».
Визуально «зависаний» больше нет.

---

## Экраны

### 1. Очистка кэшей и мусора

Три профиля глубины (переключение — `p`):

| Профиль | Что чистит |
|---|---|
| `basic` | `~/Library/Caches`, `/Library/Caches` (sudo), логи, crash-отчёты, savedState, кэш QuickLook/иконок, `Caches` внутри песочных контейнеров |
| `dev` | + Xcode DerivedData/Archives/DeviceSupport, симуляторы, CocoaPods, RubyGems, pip/poetry/mypy/pytest/ruff, npm/yarn/pnpm, Go, Cargo, Gradle/Maven, Composer, JetBrains, VS Code/Cursor, Android SDK, Unity; вызовы `brew cleanup`, `docker system prune`, `xcrun simctl delete unavailable`, `npm cache verify`, `pip cache purge`, `go clean -cache` |
| `aggressive` | + кэши Safari, Chrome, Edge, Brave, Arc, Vivaldi, Opera, Firefox, мессенджеров, почты, облачных клиентов, Adobe |

`Tab` переключает способ удаления: **в Корзину** (по умолчанию, обратимо) или
**жёстко** (`rm`, с отдельным красным подтверждением).
`i` включает фильтр «старше N дней» для `~/Downloads` (удаляет только
`.dmg .pkg .zip .iso` и подобное, обычные файлы не трогает).

### 2. Глубокий скан хлама

Обходит домашний каталог и находит то, что программы раскидали где попало:

- **безопасно** (отмечается сразу): `.DS_Store`, `._*`, `Thumbs.db`, `desktop.ini`,
  `__pycache__`, `*.pyc`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.tox`,
  `.nox`, `.coverage`, `.eslintcache`, `*.log`, `*.crash`, `*.ips`, `*.dmp`,
  `core.*`, `hs_err_pid*.log`
- **спросить** (отмечается только вручную): `.dmg/.pkg/.iso`, архивы,
  `node_modules/.cache`, `target/`, `xcuserdata`, `.venv`
- **совет** (только отчёт): крупные видео и образы дисков

Внутрь `node_modules`, `.git`, `.venv`, `Library`, `.Trash` сканер не заходит.
`~/Documents` и `~/Desktop` обходятся, но точечно из них вычищаются `.DS_Store`.

### 3. Остатки удалённых программ

Главная новая возможность. Сторонние приложения оставляют данные в десятках
мест; экран находит те, чьей программы на диске больше нет.

**Где ищет:** `Application Support`, `Caches`, `Preferences`, `HTTPStorages`,
`WebKit`, `Application Scripts`, `Containers`, `Group Containers`, `Cookies`,
`Saved Application State`, `Internet Plug-Ins`, `~/.config`, `~/.cache`,
`~/.local/share` — и те же категории в `/Library`.

**Как определяет «живое»:** строит реестр установленных приложений из
`/Applications`, `~/Applications`, `/System/Applications` (читает
`CFBundleIdentifier` из `Info.plist` через `plistlib`), добавляет результаты
Spotlight (`mdfind`, ловит программы на внешних томах) и список запущенных
процессов.

**Вердикты:**

| Вердикт | Значение | Отмечается по умолчанию |
|---|---|---|
| `СИРОТА` | bundle id не найден среди установленных | **да** |
| `устарело` | владелец не определён, но не использовалось > 365 дней | нет |
| `неясно` | ordinary-имя без соответствия — неизвестный владелец | нет |
| `утилита` | данные CLI-инструмента (pip, npm, brew, go…) | нет |
| `система` | `com.apple.*` и служебные каталоги macOS | нет |

В `CURATED` (leftovers.py) — словарь из ~200 соответствий «имя каталога →
bundle id» для популярных программ: Slack, Docker, Zoom, Telegram, Spotify,
Discord, Notion, Figma, Postman, Obsidian, 1Password, Chrome, Firefox, Arc,
JetBrains, Adobe, Steam, Parallels, Ledger, CleanShot и т. д.
**Неизвестное не помечается как мусор** — ложноположительных удалений не будет.

> Элементы в `/Library/...` принадлежат root: для их удаления используйте CLI
> с флагом `--sudo` (см. ниже).

### 4. Автозагрузка

Источники: `~/Library/LaunchAgents`, `/Library/LaunchAgents`,
`/Library/LaunchDaemons`, Login Items (через System Events) и — опционально —
фоновые элементы macOS 13+ (`sfltool dumpbtm`, нужен sudo).

Для каждого элемента показываются: метка, состояние, команда запуска,
**разработчик из подписи** (`codesign -dvv` → `Authority=`), принадлежность
приложению, `RunAtLoad`/`KeepAlive`, размер и дата изменения plist.

Состояния:

| | Значение |
|---|---|
| `▶ работает` | есть PID в `launchctl list` |
| `● загружен` | зарегистрирован в launchd, но не запущен |
| `○ не загружен` | plist лежит в каталоге, но не загружен |
| `✗ падает` | загружен, но завершился с ненулевым кодом |
| `⚠ битый` | **исполняемый файл отсутствует** — программа удалена, запись висит мёртвым грузом |
| `⛔ отключён` | отключён этим тулзом |

Фильтр `f` → «только проблемные» оставляет битые, падающие и подозрительные
(обновляторы, телеметрия, агенты синхронизации).

**Отключение обратимо:** элемент снимается с launchd
(`launchctl bootout` / `unload -w`), а его plist переносится в
`~/.mac_tweaker/disabled/`, причём исходный путь запоминается внутри файла
(ключ `MTDisabledFrom`). «Включить» (`e`) возвращает plist **на исходное место**
и грузит его заново. Системные элементы (`/System/Library`, `com.apple.*`)
помечены `[SIP]` и не отключаются вообще.

### 5. Настройки системы

45+ переключателей через `defaults`, сгруппированных по разделам:
Finder, Скриншоты, Dock, Интерфейс, Безопасность, Производительность, Прочее.
Состояние каждого читается тем же `defaults read`, поэтому экран честно
показывает, что уже включено.

- `Enter` — применить отмеченные
- `Backspace` — вернуть отмеченные в исходное состояние
- `x` — **экспорт всех настроек пользователя** в `~/.mac_tweaker/defaults-<дата>.plist`
- `i` — импорт (откат) из последнего экспорта

Рискованные твики помечены `⚠`, требующие выхода из системы — сообщают об этом.

### 6. Анализ диска

Крупнейшие каталоги с полосами-индикаторами; `Enter` — войти в каталог,
`Backspace` — наверх, `b` — список файлов крупнее 300 МБ.

### 7. Журнал и откат

Все действия пишутся в `~/.mac_tweaker/journal-<дата>.jsonl`.
`u` — вернуть из Корзины всё удалённое в этой сессии,
`Backspace` — восстановить всю отключённую автозагрузку.

---

## CLI-режим (для cron, ssh и скриптов)

Глобальные флаги (`--ascii`, `--no-color`, `--no-tui`, `--home`, `--sysroot`)
указываются **до** субкоманды.

```bash
# система и диск
python3 maccc.py info
python3 maccc.py disk --min-mb 1000

# кэши
python3 maccc.py scan  --profile dev --report ~/Desktop/junk.json
python3 maccc.py clean --profile dev -y
python3 maccc.py clean --profile aggressive --older-than-days 30 --sudo -y
python3 maccc.py clean --profile basic --only "Xcode" -y
python3 maccc.py clean -y --empty-trash --hard        # навсегда, без Корзины

# глубокий скан
python3 maccc.py deep --risk 0                        # только безопасное
python3 maccc.py deep --clean --risk 0 -y             # и сразу удалить
python3 maccc.py deep --root ~/Projects --older-than-days 60

# остатки удалённых программ
python3 maccc.py orphans                              # отчёт
python3 maccc.py orphans --include-unknown            # + неясные и устаревшие
python3 maccc.py orphans --clean -y                   # удалить сирот
python3 maccc.py orphans --clean --sudo -y            # включая /Library

# автозагрузка
python3 maccc.py startup list
python3 maccc.py startup dead                         # что висит мёртвым грузом
python3 maccc.py startup disable --label adobe -y
python3 maccc.py startup enable  --label adobe -y
python3 maccc.py startup restore                      # вернуть всё отключённое
python3 maccc.py startup list --btm --sudo            # + фоновые элементы BTM

# настройки
python3 maccc.py tweaks list
python3 maccc.py tweaks apply --id finder-hidden --id shot-location -y
python3 maccc.py tweaks revert --id dock -y
python3 maccc.py tweaks export

# журнал
python3 maccc.py undo --list
python3 maccc.py undo -y                              # вернуть из Корзины
```

Без TTY (пайп, cron) автоматически включается текстовое меню вместо псевдографики.

---

## Безопасность

### Удаление обратимо

По умолчанию всё перемещается **в Корзину** — через Finder AppleScript, а если
он недоступен, через `mv` в `~/.Trash`. Жёсткое удаление (`--hard` / `Tab` в TUI)
спрашивает отдельное красное подтверждение. Журнал `~/.mac_tweaker/journal-*.jsonl`
позволяет вернуть удалённое одной командой.

### Предохранители

`is_safe()` проверяет каждый путь перед удалением. **Никогда не удаляются:**

`~/Documents`, `~/Desktop`, `~/Pictures`, `~/Music`, `~/Movies`, `~/Public`,
`~/Library/Application Support` (кроме кэш-подпапок белого списка приложений),
`~/Library/Containers`, `Group Containers`, `Keychains`, `Mail`, `Messages`,
`Calendars`, `Contacts`, `Photos`, `Mobile Documents`, `~/.ssh`, `~/.gnupg`,
`~/.aws`, `~/.config`, `~/.kube`, `~/.docker`, `/System`, `/usr`, `/bin`,
`/sbin`, `/etc`, `/private/etc`, `/private/var/db`, `/Users/Shared`,
`/Library/Keychains`, домашний каталог целиком, `~/Library`, `/`,
и все каталоги **DataVault** (защита SIP/TCC — `lstat` на них отвечает
`Operation not permitted`; скрипт их пропускает, а не падает).

Пароли, закладки, история браузера, переписка, лицензии, проекты и настройки
приложений не трогаются. Сканеры не следуют по символьным ссылкам.

### Автозагрузка

Системные элементы (`/System/Library/...`, `com.apple.*`) помечены
`critical`/`protected` и не отключаются даже через CLI. Перед отключением plist
копируется в хранилище с сохранением исходного пути, поэтому восстановление
возвращает файл ровно туда, где он лежал.

### Root

Псевдографика от root не запускается (случайные повреждения системы слишком
дороги); для системных объектов используйте флаг `--sudo` — он точечно вызывает
`sudo` только там, где без него не обойтись.

---

## Разработка и тесты

```bash
cd mac_tweaker

# 1. создать тестовый стенд (фейковое дерево macOS)
bash tests/make_fake_home.sh /tmp/fake_mac

# 2. «состарить» файлы, чтобы проверялся фильтр по возрасту
python3 - <<'PY'
import os, time
old = time.time() - 730 * 86400
for p in ("/tmp/fake_mac/home/Library/Application Support/RemovedApp",
          "/tmp/fake_mac/home/.config/removedtool",
          "/tmp/fake_mac/home/Downloads/BigInstaller.dmg"):
    os.path.exists(p) and os.utime(p, (old, old))
PY

# 3. прогнать 185 проверок
HOME=/tmp/fake_mac/home \
MACTWEAKER_HOME=/tmp/fake_mac/home \
MACTWEAKER_SYSROOT=/tmp/fake_mac/sys \
  python3 tests/test_all.py

# 4. отрендерить все экраны в текст и HTML (проверка вёрстки)
HOME=/tmp/fake_mac/home MACTWEAKER_HOME=/tmp/fake_mac/home \
MACTWEAKER_SYSROOT=/tmp/fake_mac/sys \
  python3 tests/render_preview.py /tmp/preview --html
open /tmp/preview/preview.html

# 5. собрать single-file bundle
python3 build_bundle.py && python3 dist/maccc_bundle.py --version

# 6. прогнать TUI в настоящем псевдотерминале (18 проверок)
chmod -R a+rwX /tmp/fake_mac
HOME=/tmp/fake_mac/home MACTWEAKER_HOME=/tmp/fake_mac/home \
MACTWEAKER_SYSROOT=/tmp/fake_mac/sys \
  python3 tests/test_tui_pty.py
```

`tests/test_tui_pty.py` запускает интерфейс через `pty.fork()`, «нажимает» 25
клавиш (меню → скан → отметки → диалог → автозагрузка → настройки → остатки →
глубокий скан → справка → выход) и проверяет, что: включается alternate screen,
есть цвет, нет трейсбеков и `Operation not permitted`, ни одна строка кадра не
шире терминала, процесс выходит с кодом 0. Если тесты идут в root-песочнице,
дочерний процесс сам сбрасывает uid до nobody — TUI от root не запускается.

Итого 284 автоматические проверки (257 unit + 27 pty), включая
проверки полноты каталога переводов и рендера обеих языковых версий. Тесты покрывают: предохранители `is_safe`/`is_traversable`, DataVault и
`Operation not permitted`, удаление в Корзину и откат из неё, dry-режим,
профили очистки, глубокий скан (включая «не трогает node_modules и Documents»),
реестр приложений и все вердикты классификатора сирот, сбор/отключение/
восстановление автозагрузки, движок псевдографики (ширина строк, ANSI,
truncate, ListView, Dialog), рендер всех 10 экранов без выхода за границы
терминала и все CLI-субкоманды end-to-end.

Переменные окружения `MACTWEAKER_HOME` и `MACTWEAKER_SYSROOT` подменяют
домашний каталог и корень ФС — поэтому тесты работают и на Linux.

---

.app-обёртка: двойной клик → терминал 124×35

Для тех, кто не любит терминальные запуски, есть готовая обёртка:

```
Mac Crap Cleaner.app/
└── Contents/
    ├── Info.plist          имя, версия, иконка, LSUIElement (stub не светится в Dock)
    ├── MacOS/
    │   └── launcher        bash: открывает Terminal 124×35 и запускает TUI
    └── Resources/
        ├── MacCC.icns      иконка (ic10/ic09/ic08/ic07, пакуется из tools/icon_src.png)
        ├── maccc_bundle.py single-file бандл программы
        └── run.command     запасной запуск двойным кликом
```

Сборка и установка:

```bash
python3 build_bundle.py && python3 build_app.py
unzip -o dist/Mac-Crap-Cleaner-app.zip -d /Applications/

# первый запуск: Gatekeeper может потребовать подтверждения
xattr -dr com.apple.quarantine '/Applications/Mac Crap Cleaner.app'
# (опционально) ad-hoc подпись для своего Mac
codesign --force --deep -s - '/Applications/Mac Crap Cleaner.app'
```

Поведение при двойном клике:

1. `launcher` находит python3 3.8+ (Homebrew → /usr/local → системный);
2. через AppleScript открывает **новое окно Terminal 124×35** (Menlo 12 pt)
   и запускает в нём TUI; после завершения сессии окно ждёт клавишу и закрывается;
3. если автоматизация Terminal запрещена — fallback: `open -a Terminal run.command`;
4. если python3 нет — диалог с подсказкой `xcode-select --install`;
5. вне macOS (ssh, Linux) launcher запускает программу прямо в текущем терминале.

Сама stub-программа не показывает иконку в Dock (`LSUIElement`): визуально
существует только окно Terminal с интерфейсом MacCC.

### Авто-ресайз окна при запуске из обычного терминала

Если запустить `maccc_bundle.py` вручную в маленьком окне (80×24), программа
сама попробует дорасти до 124×35 двумя способами: ESC-последовательностью
`CSI 8;35;124t` (iTerm2/kitty/alacritty) и AppleScript по tty окна
(Terminal.app; первый раз macOS спросит разрешение на автоматизацию).
Отключается через `MACC_FIT=0`. Если окно всё равно уже 100 колонок,
в статусной строке появится подсказка.

## Автоочистка по расписанию (launchd)

```bash
cp com.user.maccrapcleaner.plist ~/Library/LaunchAgents/
# отредактируйте USERNAME в путях, затем:
launchctl load ~/Library/LaunchAgents/com.user.maccrapcleaner.plist
launchctl list | grep mactweaker
cat ~/Library/Logs/mac_crap_cleaner.log
```

По умолчанию: `clean --profile dev --older-than-days 30 -y` каждое воскресенье
в 04:00. В расписании не используется `sudo` (нет терминала для пароля) и не
используется `--hard` — всё уходит в Корзину.

---

## Что почистить вручную (вне тулзы)

| Место | Команда |
|---|---|
| Локальные снапшоты Time Machine | `tmutil listlocalsnapshots /` → `sudo tmutil deletelocalsnapshots <дата>` |
| Старые iOS-рантаймы Xcode | Xcode → Settings → Components |
| Docker целиком | `docker system prune -a --volumes` (удалит и тома!) |
| Кэш установщика macOS | `/Applications/Install macOS *.app` |
| Загрузки в Mail | Mail → Настройки → учётная запись |

---

## Лицензия

MIT. Перед первым запуском сделайте `scan` (dry-run по сути) и, в идеале,
снимок Time Machine. Инструмент старается быть безопасным, но ответственность
за ваши данные остаётся на вас.
