"""
mactweaker.app — экраны псевдографического интерфейса и главный цикл.

Экраны:
  MainMenu      главное меню
  InfoScreen    состояние системы и диска
  CleanerScreen очистка кэшей (basic/dev/aggressive)
  DeepScreen    глубокий скан: хлам внутри проектов и каталогов
  OrphansScreen «сироты» — остатки удалённых программ
  StartupScreen автозагрузка: агенты, демоны, элементы входа
  TweaksScreen  настройки системы через defaults (обратимо)
  DiskScreen    анализ занятого места
  LogScreen     журнал действий и откат

Каждый экран — объект с render(ctx) и on_key(key, ctx); App держит стек
экранов, модальный диалог, прогресс-бар и статусную строку.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import junk, leftovers, osprofile, schedule, startup, system, tweaks
from .i18n import APP_SHORT, APP_TITLE, get_lang, set_lang, tr
from .safety import (Deleter, Journal, Paths, ago, dir_size, human,
                     permission_warnings, reset_denied, run, safe_scandir,
                     sudo_ok)
from .ui import (Dialog, Key, ListView, Painter, RenderContext, Row, Screen,
                 Terminal, Theme, dwidth, pad, truncate)

BANNER = r"""
  ███╗   ███╗  █████╗  ██████╗  ██████╗  ██████╗
  ████╗ ████║ ██╔══██╗ ██╔════╝ ██╔════╝ ██╔════╝
  ██╔████╔██║ ███████║ ██║      ██║      ██║
  ██║╚██╔╝██║ ██╔══██║ ██║      ██║      ██║
  ██║ ╚═╝ ██║ ██║  ██║ ╚██████╗ ╚██████╗ ╚██████╗
  ╚═╝     ╚═╝ ╚═╝  ╚═╝  ╚═════╝  ╚═════╝  ╚═════╝
"""

TAGLINE = "Mac Crap Cleaner - Less crap. Zero subscriptions. No bullshit."


SESSION_TIPS = (
    "Сначала сканируйте («s»), потом удаляйте («x») — вы увидите объёмы заранее.",
    "Всё удалённое попадает в Корзину: пункт «Журнал и откат» → «u» вернёт файлы.",
    "Экран «Остатки удалённых программ» обычно даёт больше всего места после кэшей.",
    "В автозагрузке ищите элементы со статусом «⚠ битый» — программа удалена, "
    "а запись грузится впустую.",
    "Перед массовым применением настроек нажмите «x» — это экспортирует все "
    "defaults в бэкап.",
    "Профиль aggressive чистит кэши браузеров — закройте их заранее, иначе "
    "часть файлов останется.",
    "Системные кэши помечены ⚿ и требуют прав администратора (sudo).",
    "«Глубокий скан» не трогает node_modules, .venv, .git, Documents и Desktop.",
)

#: Надписи, которые сменяют друг друга каждые 10 секунд во время долгих
#: операций (анализ диска, глубокий скан), чтобы было видно: процесс живой.
WAIT_MESSAGES = (
    "подождите пару минут, программа не зависла",
    "просматриваю файлы",
    "прохожусь по пыльным местам",
    "я почти закончил искать",
)

HELP_TEXT = """\
Управление
──────────
↑ ↓ / j k        перемещение по списку
PgUp PgDn        страница
Home End         в начало / в конец
Пробел           отметить/снять отметку
a                отметить всё / снять всё
Enter            открыть, подтвердить, применить
r                обновить (пересканировать)
s                сканировать
x                выполнить действие над отмеченным
d                отключить отмеченное (автозагрузка)
e                включить отмеченное
u                откатить последнее действие
i                переключить фильтр/режим
S                локальные снапшоты APFS (из главного меню и «о системе»)
Tab              переключить режим (профиль, жёсткое удаление…)
?  F1            эта справка
Esc  q           назад / выход

Безопасность
────────────
По умолчанию всё удаляется В КОРЗИНУ — действие обратимо.
Жёсткое удаление (rm) включается отдельно и спрашивает подтверждение.
Цели с меткой ⚠ (веса ИИ-моделей, диски Docker/OrbStack) — НЕ кэш:
они не отмечаются автоматически и требуют отдельного подтверждения.
Если у терминала нет Full Disk Access, утилита честно пишет в статус
«Нет прав на сканирование …» вместо молчаливого пропуска каталогов.
Скрипт никогда не трогает: ~/Documents, ~/Desktop, ~/Pictures, Keychains,
Mail, Messages, ~/Library/Containers (кроме подкаталога Caches),
/System, /usr, /etc, ~/.ssh, ~/.gnupg и каталоги DataVault (SIP/TCC).
Отключение автозагрузки всегда сохраняет plist-копию в
~/.mac_tweaker/disabled/ и восстанавливается клавишей «Включить»
или пунктом «Откат» в главном меню.

Профили очистки
───────────────
basic       кэши пользователя и системы, логи, crash-отчёты, savedState
dev         + Xcode, симуляторы, brew, pip/npm/go/cargo/gradle, IDE, Docker,
            Ollama/LM Studio/OrbStack/HuggingFace (⚠ под подтверждением)
aggressive  + кэши браузеров, мессенджеров, облачных клиентов, Adobe

Автоочистка по расписанию
─────────────────────────
Пункт меню «9» создаёт launchd-агент com.dan1lazz.maccc.plist: раз в
неделю запускается очистка выбранного профиля (всё в Корзину, без sudo),
тихий отчёт пишется в ~/.mac_tweaker/scheduled.log.

APFS-снапшоты (клавиша S)
─────────────────────────
Очистка кэшей иногда «не освобождает» место — особенно на macOS Tahoe:
его держат локальные снапшоты APFS. Экран показывает список снапшотов
(tmutil) и удаляет выбранные — место освобождается сразу.

Экран «Остатки программ»
────────────────────────
Ищет данные, оставшиеся от приложений, которых больше нет на диске:
каталоги в Application Support, Caches, Preferences, Containers,
HTTPStorages, WebKit, LaunchAgents, ~/.config и ~/.cache.
Реестр установленных программ строится из /Applications, ~/Applications,
/System/Applications и Spotlight (mdfind), поэтому учитываются и программы
на внешних томах. Элементы с вердиктом «неясно» по умолчанию НЕ предлагаются
к удалению — их можно показать фильтром, но решение всегда за вами.
"""


# --------------------------------------------------------------------------- #
#  Приложение
# --------------------------------------------------------------------------- #

class App:
    def __init__(self, theme: Theme, paths: Paths, use_sudo: bool = False):
        self.theme = theme
        self.p = Painter(theme)
        self.term = Terminal(theme)
        self.paths = paths
        self.use_sudo = use_sudo
        self.stack: List[Screen] = []
        self.dialog: Optional[Dialog] = None
        self.status: str = ""
        self.status_kind: str = "muted"
        self.progress: Optional[Tuple[int, int, str]] = None
        self.journal = Journal(paths, enabled=True)
        self.sysinfo: Optional[system.SystemInfo] = None
        self.registry: Optional[leftovers.AppRegistry] = None
        self._running = True
        self.session_freed = 0
        self._anim = 0            # тик анимации прогресс-бара
        self._rot = 0             # индекс сменной надписи
        self._task_started = 0.0

    # -- жизненный цикл --
    def start(self, screen: Optional[Screen] = None) -> int:
        screen = screen or MainMenu(self)
        self.stack = [screen]
        self.refresh_sysinfo()
        self.term.enter()
        self.term.refresh_size()
        if self.term.width < 100:
            self.say(tr("окно уже 100 колонок: разверните его или запустите "
                        "через .app (124×35)"), "warn")
        try:
            while self._running:
                cur = self.stack[-1]
                ctx = self.context()
                lines = self.frame(cur, ctx)
                self.term.draw(lines)
                key = self.term.read_key(timeout=0.0)
                if key == "":
                    time.sleep(0.008)
                    continue
                if key == Key.CTRL_C:
                    break
                if key == Key.CTRL_L:
                    self.term.refresh_size()
                    continue
                if key in ("mouse",):
                    continue
                if len(key) == 1:
                    key = key.lower()      # подсказки в CAPS, ввод не зависит от регистра
                if self.dialog is not None:
                    res = self.dialog.on_key(key)
                    if res is not None:
                        dlg, self.dialog = self.dialog, None
                        self._deliver_dialog_result(dlg, res, ctx)
                    continue
                if not getattr(cur, "_entered", False):
                    cur.on_enter(ctx)
                    cur._entered = True
                nxt = cur.on_key(key, ctx)
                if nxt is not None:
                    if nxt is cur:
                        continue
                    self.stack.append(nxt)
                    nxt._entered = False
        except KeyboardInterrupt:
            pass
        finally:
            self.term.exit()
        return 0

    def context(self) -> RenderContext:
        self.term.refresh_size()
        return RenderContext(app=self, painter=self.p,
                             width=self.term.width, height=self.term.height)

    def refresh_sysinfo(self) -> system.SystemInfo:
        if self.sysinfo is None:
            self.sysinfo = system.collect(self.paths)
        else:
            free = system.disk_usage(str(self.paths.home))
            if free.total:
                self.sysinfo.disks = [free]
        return self.sysinfo

    def back(self) -> Optional[Screen]:
        if len(self.stack) > 1:
            self.stack.pop()
            return None
        self._running = False
        return None

    def quit(self) -> None:
        self._running = False

    def say(self, text: str, kind: str = "info") -> None:
        self.status, self.status_kind = text, kind

    # -- права доступа (TCC / Full Disk Access) --
    def begin_scan(self) -> None:
        """Сбросить реестр отказов доступа перед новым сканом."""
        reset_denied()

    def report_denials(self) -> None:
        """Если сканер упёрся в TCC — честно сказать об этом в статусе."""
        warns = permission_warnings(self.paths)
        if warns:
            self.say(tr("Нет прав на сканирование {n} каталогов: {ex}. "
                        "Выдайте терминалу Полный доступ к диску (FDA)")
                     .format(n=len(warns), ex=", ".join(warns)), "warn")
        return None

    # -- отрисовка кадра --
    def frame(self, screen: Screen, ctx: RenderContext) -> List[str]:
        lang = get_lang()
        if getattr(self, "_last_lang", None) != lang:
            self._last_lang = lang
            screen.on_lang_change(ctx)
        w, h = ctx.width, ctx.height
        p, t = self.p, self.theme
        si = self.sysinfo
        lines: List[str] = []

        # шапка
        title = f" {APP_TITLE} "
        sub = tr(screen.title or "")
        disk = ""
        if si and si.disks:
            d = si.disks[0]
            disk = tr("свободно {free} / {total}").format(
                free=human(d.free), total=human(d.total))
        head_left = self.p.color(title, self.theme.bold + self.theme.b_cyan)
        head_right = self.p.color(f"{sub}   {disk} ", self.theme.dim)
        gap = max(1, w - dwidth(head_left) - dwidth(head_right))
        lines.append(head_left + " " * gap + head_right)
        lines.append(self.p.color(self.theme.h * w, self.theme.cyan))

        # тело
        body_h = max(3, h - 6)
        body = screen.render(ctx)
        body = body[:body_h]
        while len(body) < body_h:
            body.append("")
        lines.extend(body)

        # прогресс / статус
        lines.append(self.p.color(self.theme.h * w, self.theme.dim))
        if self.progress:
            done, total, label = self.progress
            frac = (done / total) if total else None
            bw = max(12, min(40, w // 3))
            bar = self.p.color("[" + self.p.anim_bar(frac, bw, self._anim) + "]",
                               t.cyan)
            pct = f"{(frac or 0) * 100:3.0f}%" if frac is not None else "  · "
            elapsed = time.time() - self._task_started
            msg = ""
            if elapsed >= 4:
                msg = self.p.color("  •  " + tr(WAIT_MESSAGES[self._rot]), t.yellow)
            # на узких терминалах сначала ужимаем подпись задачи,
            # чтобы сменная надпись всегда помещалась целиком
            lab_w = max(6, w - bw - 12 - (dwidth(msg) if msg else 0))
            text = f" {bar} {pct}  {truncate(label, lab_w)}" + msg
            lines.append(truncate(text, w))
        else:
            color = {"ok": self.theme.green, "bad": self.theme.red,
                     "warn": self.theme.yellow, "info": self.theme.cyan,
                     "muted": self.theme.dim}.get(self.status_kind, self.theme.dim)
            lines.append(truncate(self.p.color(" " + tr(self.status or ""), color), w))

        # подсказки
        hints = list(screen.hints) + [("Esc", "назад"), ("?", "справка")]
        hint_line = "  ".join(
            self.p.color(tr(k).upper(), self.theme.bold) + " "
            + self.p.color(tr(v), self.theme.dim)
            for k, v in hints)
        lines.append(truncate(hint_line, w))

        # модальный диалог поверх
        if self.dialog is not None:
            overlay = self.dialog.render(self.p, w, h)
            lines = overlay[:h]
        return lines

    def _deliver_dialog_result(self, dlg: Dialog, result: str,
                               ctx: RenderContext) -> None:
        cb = getattr(dlg, "callback", None)
        if cb:
            cb(result)

    # -- диалоги --
    def confirm(self, title: str, lines: Sequence[str],
                yes_label: str = "Да", no_label: str = "Нет",
                kind: str = "warn", callback: Optional[Callable[[str], None]] = None,
                yes_code: str = "y") -> None:
        dlg = Dialog(tr(title), [tr(x) for x in lines],
                     options=((yes_code, tr(yes_label)), ("n", tr(no_label))),
                     kind=kind, default=1)
        dlg.callback = callback  # type: ignore[attr-defined]
        self.dialog = dlg

    def alert(self, title: str, lines: Sequence[str], kind: str = "info",
              callback: Optional[Callable[[str], None]] = None) -> None:
        dlg = Dialog(tr(title), [tr(x) for x in lines],
                     options=(("ok", tr("ОК")),), kind=kind, default=0)
        dlg.callback = callback  # type: ignore[attr-defined]
        self.dialog = dlg

    # -- длительные операции с прогрессом --
    def task(self, label: str, fn: Callable[[Callable], None]) -> None:
        """Запустить fn(tick) в фоновом потоке, пока главный поток рисует
        анимированный прогресс-бар и сменные надписи каждые 10 секунд.

        Интерфейс не «зависает» даже если fn молчит минуту: кадры redraw
        идут с частотой ~10/с независимо от того, шлёт ли fn тики.
        """
        import threading

        box: Dict[str, object] = {}

        def tick(done: int = 0, total: int = 0, text: str = "") -> None:
            self.progress = (done, total, text or label)

        def runner() -> None:
            try:
                fn(tick)
                box["ok"] = True
            except BaseException as exc:  # noqa: BLE001
                box["err"] = exc

        self.progress = (0, 0, label)
        self._task_started = time.time()
        self._rot = 0
        th = threading.Thread(target=runner, daemon=True)
        th.start()
        last_rot = self._task_started
        while th.is_alive():
            time.sleep(0.1)
            self._anim += 1
            now = time.time()
            if now - last_rot >= 10:
                last_rot = now
                self._rot = (self._rot + 1) % len(WAIT_MESSAGES)
            try:
                self.term.draw(self.frame(self.stack[-1], self.context()))
            except Exception:  # noqa: BLE001
                pass
        self._anim += 1
        self.progress = None
        if "err" in box:
            raise box["err"]  # type: ignore[misc]

    # -- общее действие: удаление --
    def delete_paths(self, ps: Sequence[Path], hard: bool = False,
                     label: str = "Удаление") -> Tuple[int, List[Path]]:
        label = tr(label)
        """Удалить список путей (по умолчанию в Корзину). Возвращает (байты, ошибки)."""
        deleter = Deleter(self.paths, mode="hard" if hard else "trash",
                          use_sudo=self.use_sudo, journal=self.journal)
        box: List[Tuple[int, List[Path]]] = [(0, [])]

        def work(tick):
            total = max(1, len(ps))
            tick(0, total, label)
            box[0] = deleter.delete(ps)
            tick(total, total, "")

        self.task(label, work)
        freed, failed = box[0]
        self.session_freed += freed
        self.journal.add("freed", str(freed), {"mode": "hard" if hard else "trash"})
        self.refresh_sysinfo()
        return freed, failed

    def needs_sudo_prompt(self, items: Sequence) -> bool:
        """Если среди целей есть системные — предложить sudo."""
        if self.use_sudo:
            return True
        if not any(getattr(i, "root_required", False) for i in items):
            return True
        ok = sudo_ok(non_interactive=False)
        self.use_sudo = ok
        return True

    def sudo_or_skip(self) -> bool:
        if self.use_sudo or sudo_ok(non_interactive=True):
            self.use_sudo = True
            return True
        code, _ = run(["sudo", "-v"], timeout=120)
        self.use_sudo = code == 0
        return self.use_sudo


HELP_TEXT_EN = """\
Controls
────────
↑ ↓ / j k          move through the list
PgUp PgDn          page up / page down
Home End           first / last item
Space              toggle selection
a                  select all / select none
Enter              open, confirm, apply
r                  refresh (rescan)
s                  scan
x                  run the action on selected items
d                  disable selected (startup items)
e                  enable selected
u                undo the last action
i  p  o            filters, profile, age threshold
S                local APFS snapshots (from the main menu / system info)
b                  large files (Disk analysis screen)
Tab                switch delete mode (Trash ↔ rm)
l                  switch language (Russian / English)
? F1               this help
Esc q              back / quit

Safety
──────
By default everything is moved TO THE TRASH — the action is reversible.
Hard deletion (rm) is opt-in and asks for a separate confirmation.
Targets marked ⚠ (AI model weights, Docker/OrbStack VM disks) are NOT
caches: they are never pre-selected and require an explicit confirmation.
If the terminal lacks Full Disk Access, the tool says so in the status
line instead of silently skipping protected folders.
The tool never touches: ~/Documents, ~/Desktop, ~/Pictures, Keychains,
Mail, Messages, ~/Library/Containers (except the Caches subfolder),
/System, /usr, /etc, ~/.ssh, ~/.gnupg and DataVault folders (SIP/TCC).
Disabling a startup item always keeps a plist copy in
~/.mac_tweaker/disabled/ and restores it via “Enable” or the
“Log & undo” menu.

Cleanup profiles
────────────────
basic       user and system caches, logs, crash reports, savedState
dev         + Xcode, simulators, brew, pip/npm/go/cargo/gradle, IDEs, Docker,
            Ollama/LM Studio/OrbStack/HuggingFace (⚠ explicit confirm)
aggressive  + browser, messenger and cloud-client caches

Scheduled cleanup
─────────────────
Menu item “9” creates the launchd agent com.dan1lazz.maccc.plist: once a
week it runs the chosen cleanup profile (everything to Trash, no sudo)
and writes a silent report to ~/.mac_tweaker/scheduled.log.

APFS snapshots (key S)
──────────────────────
Cache cleaning sometimes “does not free space” — especially on macOS
Tahoe: local APFS snapshots hold the deleted blocks. The screen lists
the snapshots (tmutil) and deletes the selected ones.

“Leftovers” screen
──────────────────
Finds data left behind by apps that are no longer on this Mac:
folders in Application Support, Caches, Preferences, Containers,
HTTPStorages, WebKit, LaunchAgents, ~/.config and ~/.cache.
The registry of live apps is built from /Applications, ~/Applications,
/System/Applications and Spotlight (mdfind), so apps on external volumes
count too. Items with the “unclear” verdict are NOT pre-selected:
the final call is always yours.
"""


# --------------------------------------------------------------------------- #
#  Главное меню
# --------------------------------------------------------------------------- #

@dataclass
class MenuItem:
    key: str
    label: str
    desc: str
    factory: Callable[[App], Screen]


class MainMenu(Screen):
    title = "главное меню"
    hints = (("↑↓", "выбор"), ("Enter", "открыть"), ("s", "APFS-снапшоты"),
             ("i", "о системе"), ("l", "язык"))

    def __init__(self, app: App):
        super().__init__(app)
        self.items: List[MenuItem] = []
        self.list = ListView(multi=False)
        self.banner_shown = True

    def on_lang_change(self, ctx: RenderContext) -> None:
        keep = self.list.cursor
        self.items = []
        self.build()
        self.list.cursor = min(keep, max(0, len(self.list.rows) - 1))

    def build(self) -> None:
        self.items = [
            MenuItem("1", "Очистка кэшей и мусора",
                     "системные и пользовательские кэши, логи, crash-отчёты",
                     lambda a: CleanerScreen(a)),
            MenuItem("2", "Глубокий скан хлама",
                     ".DS_Store, __pycache__, логи, краш-дампы, установщики",
                     lambda a: DeepScreen(a)),
            MenuItem("3", "Остатки удалённых программ",
                     "«сироты» в Application Support, Caches, Preferences…",
                     lambda a: OrphansScreen(a)),
            MenuItem("4", "Автозагрузка",
                     "LaunchAgents/LaunchDaemons и элементы входа",
                     lambda a: StartupScreen(a)),
            MenuItem("5", "Настройки системы",
                     "Finder, Dock, скриншоты, приватность (обратимо)",
                     lambda a: TweaksScreen(a)),
            MenuItem("6", "Анализ диска",
                     "что занимает место: каталоги и крупные файлы",
                     lambda a: DiskScreen(a)),
            MenuItem("7", "Журнал и откат",
                     "что сделано в этой и прошлых сессиях",
                     lambda a: LogScreen(a)),
            MenuItem("8", "Справка",
                     "горячие клавиши и правила безопасности",
                     lambda a: HelpScreen(a)),
            MenuItem("9", "Автоочистка по расписанию",
                     "launchd-агент: еженедельная уборка без терминала",
                     lambda a: ScheduleScreen(a)),
        ]
        rows = [Row(cells=[f"{m.key}  {self.app.p.color(tr(m.label), self.app.theme.bold)}"],
                    meta=m) for m in self.items]
        self.list = ListView(rows, multi=False)

    def render(self, ctx: RenderContext) -> List[str]:
        if not self.items:
            self.build()
        p, t = self.app.p, self.app.theme
        w = ctx.width
        out: List[str] = []

        # «шапка» с логотипом и состоянием системы
        si = self.app.refresh_sysinfo()
        logo = BANNER.strip("\n").splitlines()
        info_lines = si.summary_lines()
        h_logo = len(logo)
        logo_w = max(dwidth(x) for x in logo) + 3
        for i, ln in enumerate(logo):
            left = p.color(ln, t.b_cyan if i < 2 else t.cyan)
            right = ""
            if i < len(info_lines):
                avail = max(0, w - logo_w - 1)
                right = p.color(truncate(info_lines[i], avail), t.dim)
            gap = max(1, w - logo_w - dwidth(right))
            out.append(truncate("  " + left + " " * gap + right, w))
        # слоган — строго под ASCII-артом
        out.append("  " + p.color(TAGLINE, t.bold + t.yellow))

        # индикатор диска
        if si.disks:
            d = si.disks[0]
            frac = d.used / d.total if d.total else 0
            color = t.red if frac > 0.9 else (t.yellow if frac > 0.75 else t.green)
            bar = p.bar(frac, min(46, max(12, w - 40)), color + t.checked + t.reset,
                        t.unchecked)
            out.append("")
            out.append("  " + p.color(tr("Диск: "), t.dim) + bar +
                       p.color(f"  {frac * 100:.0f}% {tr('занято')}", t.dim))
        if self.app.session_freed:
            out.append("  " + p.color(
                tr("Освобождено за сессию: {size}").format(
                    size=human(self.app.session_freed)),
                t.green))
        out.append("")

        # меню
        # меню занимает ровно столько строк, сколько в нём пунктов, —
        # остальное место отдаём подсказкам
        room_total = max(4, ctx.height - len(out) - 6)
        menu_h = min(len(self.items), room_total - 4)
        menu_h = max(3, menu_h)
        label_w = max(38, min(w // 2, 52))
        desc_w = max(8, w - label_w - 6)
        rows = self.list.render(p, label_w, menu_h)[:menu_h]
        for i, r in enumerate(rows):
            line = "  " + r
            if i < len(self.items):
                line += "  " + p.color(
                    truncate(tr(self.items[i].desc), desc_w), t.dim)
            out.append(truncate(line, w))

        # подсказки — заполняют свободное место внизу
        room = max(0, ctx.height - len(out) - 6)
        if room >= 2:
            out.append(p.hline(w, t.lt, t.rt, f" {tr(' Совет ').strip()} "))
            tips = [tr(t2) for t2 in SESSION_TIPS]
            start = int(time.time() // 12) % len(tips)
            for k in range(min(room - 1, 4)):
                tip = tips[(start + k) % len(tips)]
                out.append("  " + p.color(t.bullet + " ", t.cyan)
                           + p.color(truncate(tip, w - 6), t.dim))
        return out

    def on_key(self, key: str, ctx: RenderContext) -> Optional[Screen]:
        if not self.items:
            self.build()
        if key in (Key.UP, "k"):
            self.list.move(-1)
            return None
        if key in (Key.DOWN, "j"):
            self.list.move(1)
            return None
        if key in (Key.ENTER, Key.RIGHT):
            item: MenuItem = self.list.current.meta
            return item.factory(self.app)
        if key in "123456789":
            idx = int(key) - 1
            if idx < len(self.items):
                return self.items[idx].factory(self.app)
        if key == "s":
            return SnapshotsScreen(self.app)
        if key == "i":
            return InfoScreen(self.app)
        if key == "l":
            nxt = "en" if get_lang() == "ru" else "ru"
            set_lang(nxt, persist=True, paths=self.app.paths)
            self.app.say(tr("Язык переключён: {lang}").format(lang=nxt), "ok")
            return None
        if key in ("?", "F1"):
            return HelpScreen(self.app)
        return super().on_key(key, ctx)


# --------------------------------------------------------------------------- #
#  О системе
# --------------------------------------------------------------------------- #

class InfoScreen(Screen):
    title = "о системе"
    hints = (("r", "обновить"), ("t", "крупнейшие каталоги"),
             ("s", "APFS-снапшоты"))

    def __init__(self, app: App):
        super().__init__(app)
        self.top: List[Tuple[Path, int]] = []

    def render(self, ctx: RenderContext) -> List[str]:
        p, t = self.app.p, self.app.theme
        w = ctx.width
        si = self.app.refresh_sysinfo()
        feats = osprofile.get_os_features()
        out = [p.hline(w, t.tl, t.tr, tr(" Система "))]
        for ln in si.summary_lines():
            out.append("  " + ln)
        if feats.major:
            out.append("  " + p.color(tr("Профиль ОС: {name} ({major})").format(
                name=feats.name, major=feats.major), t.dim)
                + (p.color("  •  " + tr("только Apple Silicon"), t.dim)
                   if not feats.supports_intel else ""))
        if si.full_disk_access is False:
            out.append("  " + p.color(
                tr("⚠ Нет Full Disk Access: ") + osprofile.fda_hint(), t.yellow))
        out.append(p.hline(w, t.lt, t.rt))

        if si.disks:
            d = si.disks[0]
            frac = d.used / d.total if d.total else 0
            out.append(f"  {p.color(tr('Занято'), t.dim)}: {human(d.used)} / "
                       f"{human(d.total)}    "
                       f"{p.color(tr('свободно'), t.dim)}: "
                       f"{p.color(human(d.free), t.green)} "
                       f"{p.color(f'({100 - d.percent:.0f}%)', t.dim)}")
            out.append("  " + p.bar(frac, min(60, w - 6)))
        out.append(p.hline(w, t.lt, t.rt, tr(" Крупнейшие каталоги дома ")))
        if not self.top:
            out.append("  " + p.color(tr("нажмите «t», чтобы посчитать (может занять минуту)"),
                                      t.dim))
        else:
            total = sum(s for _, s in self.top) or 1
            for path, size in self.top:
                frac = size / total
                bar = p.bar(frac, max(6, min(24, w - 40)))
                out.append("  " + pad(self.app.paths.short(path), 28) + bar +
                           " " + p.color(human(size), t.bold))
        return out

    def on_key(self, key: str, ctx: RenderContext) -> Optional[Screen]:
        if key == "r":
            self.app.sysinfo = None
            self.app.refresh_sysinfo()
            self.app.say(tr("Данные обновлены"), "ok")
            return None
        if key == "s":
            return SnapshotsScreen(self.app)
        if key == "t":
            def work(tick):
                tick(0, 0, "считаю размеры каталогов…")
                self.top = system.top_level_sizes(self.app.paths.home, 14,
                                                   progress=tick)
                tick(1, 1, "")
            self.app.task("Анализ каталогов", work)
            self.app.say(tr("Посчитано: {n} каталогов").format(n=len(self.top)), "ok")
            return None
        return super().on_key(key, ctx)


# --------------------------------------------------------------------------- #
#  Очистка кэшей
# --------------------------------------------------------------------------- #

class CleanerScreen(Screen):
    title = "очистка кэшей"
    hints = (("s", "скан"), ("Пробел", "отметить"), ("a", "всё"),
             ("x", "очистить"), ("Tab", "жёсткое удаление"), ("p", "профиль"))

    def on_lang_change(self, ctx: RenderContext) -> None:
        if self.scanned:
            self.rebuild_rows()

    def __init__(self, app: App):
        super().__init__(app)
        self.profile = "basic"
        self.older_than: Optional[float] = None
        self.hard = False
        self.targets: List[junk.JunkTarget] = []
        self.list = ListView(multi=True)
        self.scanned = False
        self.perm_warn: List[str] = []
        self.columns = [(10, "right"), (-38, "left"), (-34, "left")]

    # -- сканирование --
    def do_scan(self) -> None:
        def work(tick):
            self.app.begin_scan()
            self.targets = junk.scan_junk(
                self.app.paths, profile=self.profile,
                older_than_days=self.older_than, progress=tick)
        self.app.task("Сканирование кэшей", work)
        self.scanned = True
        self.perm_warn = permission_warnings(self.app.paths)
        self.rebuild_rows()
        total = sum(t.size for t in self.targets if t.selected)
        if self.perm_warn:
            self.app.say(tr("Нет прав на сканирование {n} каталогов: {ex}. "
                            "Выдайте терминалу Полный доступ к диску (FDA)")
                         .format(n=len(self.perm_warn),
                                 ex=", ".join(self.perm_warn[:2])), "warn")
        else:
            self.app.say(tr("Найдено {n} целей на {size} — отметьте нужное и нажмите «x»")
                         .format(n=len(self.targets), size=human(total)), "info")

    def rebuild_rows(self) -> None:
        rows: List[Row] = []
        grouped = junk.group_by_category(self.targets)
        for cat in sorted(grouped):
            rows.append(Row(cells=[f"── {tr(cat)} " + "─" * 20], selectable=False,
                            dim=True))
            for t in grouped[cat]:
                size_s = human(t.size) if t.kind != "command" else "команда"
                name = tr(t.name)
                if t.root_required:
                    name = self.app.p.color("⚿ ", self.app.theme.yellow) + name
                if t.dangerous:
                    name = self.app.p.color("⚠ ", self.app.theme.red) + name
                note = truncate(tr(t.note), 44) if t.note else t.preview(self.app.paths, 1)
                rows.append(Row(cells=[size_s, name, self.app.p.color(note,
                                                                      self.app.theme.dim)],
                                checked=t.selected, meta=t))
        self.list = ListView(rows, multi=True)
        self._sync_selection()

    def _sync_selection(self) -> None:
        for r in self.list.rows:
            if isinstance(r.meta, junk.JunkTarget):
                r.meta.selected = r.checked

    def selected_targets(self) -> List[junk.JunkTarget]:
        self._sync_selection()
        return [t for t in self.targets if t.selected]

    def render(self, ctx: RenderContext) -> List[str]:
        p, t = self.app.p, self.app.theme
        w = ctx.width
        out = [p.hline(w, t.tl, t.tr, tr(
            " профиль: {profile} • старше {days} дн. • удаление: {mode} ").format(
                profile=self.profile, days=self.older_than or "—",
                mode=tr("жёсткое (rm)") if self.hard else tr("в Корзину")))]
        if self.scanned and self.perm_warn:
            out.append("  " + p.color(tr("⚠ Нет прав (TCC): {ex} — выдайте "
                                         "терминалу Полный доступ к диску")
                                      .format(ex=", ".join(self.perm_warn[:2])),
                                      t.yellow))
        if not self.scanned:
            out.append("")
            out.append("  " + p.color(tr("Нажмите «s», чтобы просканировать диск."), t.bold))
            out.append("")
            for i, name in enumerate(junk.PROFILES):
                mark = p.color(t.arrow + " ", t.cyan) if name == self.profile else "  "
                line = f"  {mark}{p.color(name, t.bold)}  — " + \
                    p.color(tr(_profile_desc(name)), t.dim)
                out.append(truncate(line, w))
            out.append("")
            out.append("  " + p.color(tr("p — сменить профиль,  i — фильтр по возрасту"),
                                      t.dim))
            return out

        body_h = max(4, ctx.height - len(out) - 9)
        out.extend(self.list.render(p, w - 2, body_h, columns=self.columns))
        sel = self.selected_targets()
        total = sum(x.size for x in sel)
        n_files = sum(x.files for x in sel)
        out.append(p.sep(w))
        out.append("  " + tr("отмечено: {n} целей, {size}, файлов: {files}").format(
            n=p.color(str(len(sel)), t.bold), size=p.color(human(total), t.green),
            files=n_files))
        return out

    def on_key(self, key: str, ctx: RenderContext) -> Optional[Screen]:
        if key == "s":
            self.do_scan()
            return None
        if key == "p":
            i = junk.PROFILES.index(self.profile)
            self.profile = junk.PROFILES[(i + 1) % len(junk.PROFILES)]
            self.scanned = False
            self.app.say(tr("Профиль: {profile}. Нажмите «s» для сканирования")
                         .format(profile=self.profile), "info")
            return None
        if key == "i":
            self.older_than = {None: 30, 30: 90, 90: 7, 7: None}[self.older_than]
            self.scanned = False
            self.app.say(tr("Фильтр ~/Downloads: старше {days} дн.")
                         .format(days=self.older_than or "—"), "info")
            return None
        if key == Key.TAB:
            self.hard = not self.hard
            self.app.say(tr("Режим удаления: ") +
                         ("rm -rf (!)" if self.hard else tr("в Корзину (обратимо)")),
                         "warn" if self.hard else "ok")
            return None
        if key in (Key.UP, "k"):
            self.list.move(-1)
            return None
        if key in (Key.DOWN, "j"):
            self.list.move(1)
            return None
        if key in (Key.PAGEUP,):
            self.list.page(ctx.body_height, up=True); return None
        if key in (Key.PAGEDOWN,):
            self.list.page(ctx.body_height); return None
        if key == Key.HOME:
            self.list.home(); return None
        if key == Key.END:
            self.list.end(); return None
        if key == Key.SPACE:
            self.list.toggle()
            return None
        if key == "a":
            self.list.toggle_all()
            self._sync_selection()
            return None
        if key in ("x", Key.ENTER):
            self._confirm_clean()
            return None
        if key == "?":
            return HelpScreen(self.app)
        return super().on_key(key, ctx)

    def _confirm_clean(self) -> None:
        sel = self.selected_targets()
        if not sel:
            self.app.say(tr("Ничего не отмечено"), "warn")
            return
        total = sum(t.size for t in sel)
        root_needed = any(t.root_required for t in sel)
        dangerous = [t for t in sel if t.dangerous]
        lines = [
            tr("Целей: {n}   Объём: {size}").format(n=len(sel), size=human(total)),
            "",
            tr("Способ: ") + (tr("ЖЁСТКОЕ УДАЛЕНИЕ (rm -rf) — необратимо!")
                              if self.hard else tr("перемещение в Корзину (обратимо)")),
        ]
        if root_needed:
            lines.append(tr("Часть целей системные — потребуется пароль sudo."))
        if dangerous:
            lines += ["", tr("⚠ ОПАСНЫЕ ЦЕЛИ — это НЕ кэш, а данные:")]
            lines += [f"  • {tr(t.name)} ({human(t.size)})" for t in dangerous[:5]]
            lines.append(tr("Веса моделей и диски контейнеров придётся "
                            "создавать/скачивать заново!"))
        lines += ["", tr("Продолжить?")]

        def act(res: str) -> None:
            if res != "y":
                self.app.say(tr("Отменено"), "warn")
                return
            if root_needed and not self.app.sudo_or_skip():
                self.app.say(tr("sudo недоступен — системные кэши будут пропущены"),
                             "warn")
            self._do_clean(sel)

        self.app.confirm(tr("Очистка"), lines, yes_label=tr("очистить"),
                         no_label=tr("Отмена"),
                         kind="danger" if (self.hard or dangerous) else "warn",
                         callback=act)

    def _do_clean(self, sel: Sequence[junk.JunkTarget]) -> None:
        deleter = Deleter(self.app.paths,
                          mode="hard" if self.hard else "trash",
                          use_sudo=self.app.use_sudo, journal=self.app.journal)
        result: Dict[str, int] = {"freed": 0, "errors": 0, "skipped": 0}

        def work(tick):
            freed, errors, skipped = junk.clean_targets(sel, deleter, progress=tick)
            result["freed"], result["errors"], result["skipped"] = freed, errors, skipped

        self.app.task("Очистка", work)
        freed = result["freed"]
        self.app.session_freed += freed
        self.app.refresh_sysinfo()
        self.app.journal.add("clean", f"{freed} байт",
                             {"profile": self.profile, "hard": self.hard,
                              "targets": [t.name for t in sel]})
        msg = (tr("Освобождено {size}").format(size=human(freed))
               + (tr("ошибок: {n}").format(n=result["errors"])
                  if result["errors"] else "")
               + (tr("пропущено (нет прав): {n}").format(n=result["skipped"])
                  if result["skipped"] else ""))
        self.app.say(msg, "ok" if not result["errors"] else "warn")
        self.app.alert(tr("Готово"), [msg, "", tr("Корзина: ") +
                                      (tr("очищается отдельно") if not self.hard
                                       else tr("не использовалась"))])
        self.scanned = False
        self.targets = []
        self.list = ListView(multi=True)


def _profile_desc(name: str) -> str:
    return {
        "basic": "кэши пользователя и системы, логи, crash-отчёты",
        "dev": "+ Xcode, симуляторы, brew, pip/npm/go/cargo/gradle, IDE, Docker, "
               "веса ИИ-моделей (⚠ отдельно)",
        "aggressive": "+ кэши браузеров, мессенджеров, облачных клиентов",
    }.get(name, "")


# --------------------------------------------------------------------------- #
#  Глубокий скан
# --------------------------------------------------------------------------- #

class DeepScreen(Screen):
    title = "глубокий скан хлама"
    hints = (("s", "скан"), ("Пробел", "отметить"), ("a", "всё"),
             ("x", "удалить"), ("i", "фильтр риска"))

    def on_lang_change(self, ctx: RenderContext) -> None:
        if self.scanned:
            self.rebuild()

    def __init__(self, app: App):
        super().__init__(app)
        self.items: List[junk.DeepItem] = []
        self.list = ListView(multi=True)
        self.risk_max = junk.RISK_ASK
        self.older_than: Optional[float] = None
        self.scanned = False
        self.columns = [(9, "right"), (-27, "left"), (-45, "left"), (10, "right")]

    def do_scan(self) -> None:
        def work(tick):
            self.app.begin_scan()
            self.items = junk.deep_scan(self.app.paths, max_depth=7,
                                        risk_max=self.risk_max,
                                        older_than_days=self.older_than,
                                        progress=tick)
        self.app.task("Глубокий скан домашнего каталога", work)
        self.scanned = True
        self.rebuild()
        safe = sum(i.size for i in self.items if i.risk == junk.RISK_SAFE)
        warns = permission_warnings(self.app.paths)
        if warns:
            self.app.say(tr("Нет прав на сканирование {n} каталогов: {ex}. "
                            "Выдайте терминалу Полный доступ к диску (FDA)")
                         .format(n=len(warns), ex=", ".join(warns[:2])), "warn")
        else:
            self.app.say(tr("Найдено {n} объектов; безопасного мусора на {size}")
                         .format(n=len(self.items), size=human(safe)), "info")

    def rebuild(self) -> None:
        p, t = self.app.p, self.app.theme
        rows: List[Row] = []
        by_cat: Dict[str, List[junk.DeepItem]] = {}
        for it in self.items:
            by_cat.setdefault(it.category, []).append(it)
        for cat in sorted(by_cat):
            group = sorted(by_cat[cat], key=lambda x: -x.size)
            total = sum(i.size for i in group)
            rows.append(Row(cells=[f"── {tr(cat)} • {len(group)} • {human(total)}"],
                            selectable=False, dim=True))
            for it in group[:200]:
                risk = {junk.RISK_SAFE: p.color(tr("безопасно"), t.green),
                        junk.RISK_ASK: p.color(tr("спросить"), t.yellow),
                        junk.RISK_ADVICE: p.color(tr("совет"), t.dim)}.get(
                            it.risk, str(it.risk))
                rows.append(Row(cells=[human(it.size), tr(it.rule),
                                       p.color(self.app.paths.short(it.path), t.dim),
                                       risk],
                                checked=it.selected, meta=it))
        self.list = ListView(rows, multi=True)
        self._sync()

    def _sync(self) -> None:
        for r in self.list.rows:
            if isinstance(r.meta, junk.DeepItem):
                r.meta.selected = r.checked

    def render(self, ctx: RenderContext) -> List[str]:
        p, t = self.app.p, self.app.theme
        w = ctx.width
        risk_name = tr({junk.RISK_SAFE: "только безопасное",
                        junk.RISK_ASK: "безопасное + спорное",
                        junk.RISK_ADVICE: "всё, включая советы"}[self.risk_max])
        out = [p.hline(w, t.tl, t.tr, tr(
            " уровень: {risk} • глубина {depth} • старше {days} дн. ").format(
                risk=risk_name, depth=7, days=self.older_than or "—"))]
        if not self.scanned:
            out += ["",
                    "  " + tr("Ищет то, что программы раскидали по домашнему каталогу:"),
                    "  " + p.color(tr(".DS_Store • __pycache__ • *.pyc • кэши линтеров"), t.dim),
                    "  " + p.color(tr("логи • краш-дампы • .dmg/.pkg • кэши сборки"), t.dim),
                    "",
                    "  " + p.color("s", t.bold) + tr(" — начать сканирование ")
                    + tr("(занимает от 10 секунд до пары минут)"),
                    "",
                    "  " + p.color(tr("Не трогает: node_modules, .venv, .git, Library, "
                                      "ваши документы и проекты."), t.dim)]
            return out
        body_h = max(4, ctx.height - len(out) - 9)
        out.extend(self.list.render(p, w - 2, body_h, columns=self.columns))
        self._sync()
        sel = [i for i in self.items if i.selected]
        out.append(p.sep(w))
        out.append("  " + tr("отмечено: {n} объектов на {size}").format(
            n=p.color(str(len(sel)), t.bold),
            size=p.color(human(sum(i.size for i in sel)), t.green)))
        return out

    def on_key(self, key: str, ctx: RenderContext) -> Optional[Screen]:
        if key == "s":
            self.do_scan(); return None
        if key == "i":
            self.risk_max = (self.risk_max + 1) % 3
            self.scanned = False
            self.app.say(tr("Уровень изменён — нажмите «s» для нового скана"), "info")
            return None
        if key == "o":
            self.older_than = {None: 30, 30: 90, 90: None}[self.older_than]
            self.scanned = False
            return None
        if key in (Key.UP, "k"):
            self.list.move(-1); return None
        if key in (Key.DOWN, "j"):
            self.list.move(1); return None
        if key == Key.PAGEUP:
            self.list.page(ctx.body_height, up=True); return None
        if key == Key.PAGEDOWN:
            self.list.page(ctx.body_height); return None
        if key == Key.SPACE:
            self.list.toggle(); self._sync(); return None
        if key == "a":
            self.list.toggle_all(); self._sync(); return None
        if key in ("x", Key.ENTER):
            self._do_delete(); return None
        return super().on_key(key, ctx)

    def _do_delete(self) -> None:
        self._sync()
        sel = [i for i in self.items if i.selected]
        if not sel:
            self.app.say("Ничего не отмечено", "warn"); return
        total = sum(i.size for i in sel)
        risky = [i for i in sel if i.risk != junk.RISK_SAFE]

        def act(res: str) -> None:
            if res != "y":
                self.app.say("Отменено", "warn"); return
            freed, failed = self.app.delete_paths([i.path for i in sel],
                                                  label="Удаление хлама")
            self.app.journal.add("deep-clean", f"{len(sel)} объектов",
                                 {"freed": freed,
                                  "paths": [str(i.path) for i in sel[:200]]})
            self.app.say(f"Освобождено {human(freed)}"
                         + (f", не удалось: {len(failed)}" if failed else ""),
                         "ok" if not failed else "warn")
            self.items = [i for i in self.items if i not in sel]
            self.rebuild()

        lines = [tr("Объектов: {n}   Объём: {size}").format(n=len(sel), size=human(total)),
                 "", tr("Всё будет перемещено в Корзину (обратимо).")]
        if risky:
            lines.append(tr("Спорных элементов: {n} — проверьте список!").format(n=len(risky)))
        self.app.confirm(tr("Удаление хлама"), lines, yes_label=tr("удалить"),
                         no_label=tr("Отмена"), kind="warn" if risky else "info",
                         callback=act)


# --------------------------------------------------------------------------- #
#  Остатки удалённых программ
# --------------------------------------------------------------------------- #

class OrphansScreen(Screen):
    title = "остатки удалённых программ"
    hints = (("s", "скан"), ("Пробел", "отметить"), ("a", "всё"),
             ("x", "удалить"), ("i", "фильтр"))

    FILTERS = ("только сироты", "сироты + неясные и устаревшие",
               "всё, включая системные")   # переводится через tr() при отрисовке

    def on_lang_change(self, ctx: RenderContext) -> None:
        if self.scanned:
            self.rebuild()

    def __init__(self, app: App):
        super().__init__(app)
        self.items: List[leftovers.Leftover] = []
        self.list = ListView(multi=True)
        self.filter_idx = 0
        self.scanned = False
        self.registry = None
        self.columns = [(9, "right"), (9, "left"), (-30, "left"), (-28, "left")]

    def do_scan(self) -> None:
        def work(tick):
            self.app.begin_scan()
            tick(0, 3, "читаю реестр установленных программ…")
            reg = leftovers.AppRegistry.build(self.app.paths)
            self.app.registry = reg
            self.registry = reg
            tick(1, 3, f"найдено программ: {len(reg.apps)}")
            tick(2, 3, "сканирую каталоги данных…")
            self.items = leftovers.scan_leftovers(
                self.app.paths, registry=reg,
                include_unknown=self.filter_idx >= 1,
                include_system=self.filter_idx >= 2,
                progress=lambda d, t, l: tick(2, 3, l))
        self.app.task("Поиск остатков удалённых программ", work)
        self.scanned = True
        self.rebuild()
        orph = [i for i in self.items if i.verdict == leftovers.VERDICT_ORPHAN]
        self.app.report_denials()
        if not permission_warnings(self.app.paths):
            self.app.say(tr("Установлено программ: {n} • сирот: {orph} на {size}")
                         .format(n=len(self.registry.apps) if self.registry else 0,
                                 orph=len(orph),
                                 size=human(sum(i.size for i in orph))), "info")

    def rebuild(self) -> None:
        p, t = self.app.p, self.app.theme
        rows: List[Row] = []
        groups = leftovers.group_leftovers(self.items)
        order = sorted(groups, key=lambda g: -sum(i.size for i in groups[g]))
        for src in order:
            group = sorted(groups[src], key=lambda x: -x.size)
            total = sum(i.size for i in group)
            rows.append(Row(cells=[f"── {tr(src)} • {len(group)} • {human(total)}"],
                            selectable=False, dim=True))
            for it in group[:120]:
                verdict = {
                    leftovers.VERDICT_ORPHAN: p.color(tr("СИРОТА"), t.b_red),
                    leftovers.VERDICT_UNKNOWN: p.color(tr("неясно"), t.yellow),
                    leftovers.VERDICT_STALE: p.color(tr("устарело"), t.yellow),
                    leftovers.VERDICT_SYSTEM: p.color(tr("система"), t.dim),
                    leftovers.VERDICT_TOOL: p.color(tr("утилита"), t.dim),
                }.get(it.verdict, it.verdict)
                name = it.path.name
                rows.append(Row(cells=[human(it.size), verdict, name,
                                       p.color(truncate(it.evidence, 46), t.dim)],
                                checked=it.selected, meta=it))
        self.list = ListView(rows, multi=True)
        self._sync()

    def _sync(self) -> None:
        for r in self.list.rows:
            if isinstance(r.meta, leftovers.Leftover):
                r.meta.selected = r.checked

    def render(self, ctx: RenderContext) -> List[str]:
        p, t = self.app.p, self.app.theme
        w = ctx.width
        out = [p.hline(w, t.tl, t.tr, tr(" фильтр: {name} ").format(
            name=tr(self.FILTERS[self.filter_idx])))]
        if not self.scanned:
            out += ["",
                    "  " + tr("Ищет данные программ, которых на этом Mac уже нет."),
                    "",
                    "  " + tr("Проверяются: Application Support, Caches, Preferences,"),
                    "  " + tr("Containers, Group Containers, HTTPStorages, WebKit,"),
                    "  " + tr("Application Scripts, Cookies, Logs, Saved Application State,"),
                    "  " + tr("Internet Plug-Ins, ~/.config, ~/.cache, ~/.local/share,"),
                    "  " + tr("а также те же каталоги в /Library."),
                    "",
                    "  " + tr("Реестр живых программ: /Applications, ~/Applications,"),
                    "  " + tr("/System/Applications, Spotlight (mdfind) и запущенные процессы."),
                    "",
                    "  " + p.color("s", t.bold) + tr(" — сканировать   ") +
                    p.color("i", t.bold) + tr(" — фильтр"),
                    "",
                    "  " + p.color(tr("Элементы «неясно» по умолчанию не отмечаются: "
                                      "решение за вами."), t.dim)]
            return out
        body_h = max(4, ctx.height - len(out) - 9)
        out.extend(self.list.render(p, w - 2, body_h, columns=self.columns))
        self._sync()
        sel = [i for i in self.items if i.selected]
        out.append(p.hline(w, t.lt, t.rt))
        out.append("  " + tr("отмечено: {n} на {size}").format(
            n=p.color(str(len(sel)), t.bold),
            size=p.color(human(sum(i.size for i in sel)), t.green)))
        return out

    def on_key(self, key: str, ctx: RenderContext) -> Optional[Screen]:
        if key == "s":
            self.do_scan(); return None
        if key == "i":
            self.filter_idx = (self.filter_idx + 1) % len(self.FILTERS)
            self.scanned = False
            self.app.say(tr("Фильтр: {name} — нажмите «s»").format(
                name=tr(self.FILTERS[self.filter_idx])), "info")
            return None
        if key in (Key.UP, "k"):
            self.list.move(-1); return None
        if key in (Key.DOWN, "j"):
            self.list.move(1); return None
        if key == Key.PAGEUP:
            self.list.page(ctx.body_height, up=True); return None
        if key == Key.PAGEDOWN:
            self.list.page(ctx.body_height); return None
        if key == Key.SPACE:
            self.list.toggle(); self._sync(); return None
        if key == "a":
            self.list.toggle_all(); self._sync(); return None
        if key in ("x", Key.ENTER):
            self._do_delete(); return None
        return super().on_key(key, ctx)

    def _do_delete(self) -> None:
        self._sync()
        sel = [i for i in self.items if i.selected]
        if not sel:
            self.app.say("Ничего не отмечено", "warn"); return
        total = sum(i.size for i in sel)
        unknown = [i for i in sel if i.verdict != leftovers.VERDICT_ORPHAN]

        def act(res: str) -> None:
            if res != "y":
                self.app.say("Отменено", "warn"); return
            freed, failed = self.app.delete_paths([i.path for i in sel],
                                                  label="Удаление остатков")
            self.app.journal.add("orphans-clean", f"{len(sel)} объектов",
                                 {"freed": freed,
                                  "paths": [str(i.path) for i in sel[:200]]})
            self.app.say(f"Освобождено {human(freed)}"
                         + (f", не удалось: {len(failed)}" if failed else ""),
                         "ok" if not failed else "warn")
            self.items = [i for i in self.items if i not in sel]
            self.rebuild()

        lines = [tr("Объектов: {n}   Объём: {size}").format(n=len(sel), size=human(total)),
                 "", tr("Всё перемещается в Корзину — можно вернуть.")]
        if unknown:
            lines.append(tr("Из них «неясных»: {n} — убедитесь, что это действительно мусор!")
                         .format(n=len(unknown)))
        self.app.confirm(tr("Удаление остатков программ"), lines,
                         yes_label=tr("удалить"), no_label=tr("Отмена"),
                         kind="danger" if unknown else "warn", callback=act)


# --------------------------------------------------------------------------- #
#  Автозагрузка
# --------------------------------------------------------------------------- #

class StartupScreen(Screen):
    title = "автозагрузка"
    hints = (("s", "обновить"), ("Пробел", "отметить"), ("d", "отключить"),
             ("e", "включить"), ("f", "фильтр"))

    FILTERS = ("все", "только проблемные", "отключённые", "агенты пользователя")  # tr() при отрисовке

    def on_lang_change(self, ctx: RenderContext) -> None:
        if self.scanned:
            self.rebuild()

    def __init__(self, app: App):
        super().__init__(app)
        self.items: List[startup.LaunchItem] = []
        self.list = ListView(multi=True)
        self.filter_idx = 0
        self.scanned = False
        self.columns = [(-38, "left"), (15, "left"), (-40, "left")]

    def do_scan(self) -> None:
        def work(tick):
            tick(0, 2, "читаю plist-файлы автозагрузки…")
            self.items = startup.collect(self.app.paths, include_system=False,
                                         include_login_items=True,
                                         registry=self.app.registry,
                                         progress=lambda d, t, l: tick(0, 2, l))
            tick(1, 2, "проверяю подписи и состояния…")
            tick(2, 2, "")
        self.app.task("Сбор элементов автозагрузки", work)
        self.scanned = True
        self.rebuild()
        dead = startup.dead_weight(self.items)
        self.app.say(tr("Элементов: {n} • подозрительных: {bad}")
                     .format(n=len(self.items), bad=len(dead)), "info")

    def visible(self) -> List[startup.LaunchItem]:
        f = self.filter_idx
        if f == 1:
            return startup.dead_weight(self.items)
        if f == 2:
            return [i for i in self.items if i.state == startup.STATE_DISABLED]
        if f == 3:
            return [i for i in self.items if i.domain == startup.DOMAIN_USER]
        return self.items

    def rebuild(self) -> None:
        p, t = self.app.p, self.app.theme
        rows: List[Row] = []
        grouped = startup.group_by_domain(self.visible())
        for domain, group in grouped.items():
            running = sum(1 for i in group if i.state == startup.STATE_RUNNING)
            rows.append(Row(cells=[
                f"── {tr(startup.DOMAIN_LABEL.get(domain, domain))}"
                f" • {len(group)} • {tr('▶ работает') if False else ''}"
                f"{'running: ' if get_lang() == 'en' else 'работает: '}{running}"],
                selectable=False, dim=True))
            for it in sorted(group, key=lambda x: (x.critical, x.label.lower())):
                label = it.label
                if it.critical:
                    label = p.color(label, t.dim)
                elif it.missing_binary or it.state == startup.STATE_FAILED:
                    label = p.color(label, t.b_red)
                info_bits = []
                if it.developer:
                    info_bits.append(it.developer)
                if it.app_name and it.app_name != it.label:
                    info_bits.append(it.app_name)
                if it.notes:
                    info_bits.append(it.note_texts()[0])
                info_s = p.color(truncate(" • ".join(info_bits), 44), t.dim)
                lock = p.color(" *", t.dim) if not it.disable_allowed else ""
                rows.append(Row(cells=[label + lock, tr(it.state_mark), info_s],
                                checked=it.selected, meta=it,
                                selectable=True))
        self.list = ListView(rows, multi=True)
        self._sync()

    def _sync(self) -> None:
        for r in self.list.rows:
            if isinstance(r.meta, startup.LaunchItem):
                r.meta.selected = r.checked

    def render(self, ctx: RenderContext) -> List[str]:
        p, t = self.app.p, self.app.theme
        w = ctx.width
        out = [p.hline(w, t.tl, t.tr, tr(" фильтр: {name} ").format(
            name=tr(self.FILTERS[self.filter_idx])))]
        if not self.scanned:
            out += ["",
                    "  " + tr("Показывает всё, что запускается само:"),
                    "  " + p.color("~/Library/LaunchAgents      — " + tr("агенты пользователя"), t.dim),
                    "  " + p.color("/Library/LaunchAgents       — " + tr("агент (все пользователи)"), t.dim),
                    "  " + p.color("/Library/LaunchDaemons      — " + tr("демон (root)"), t.dim),
                    "  " + p.color("Login Items                 — " + tr("элемент входа"), t.dim),
                    "",
                    "  " + tr("Помечены состояния: ▶ работает  ● загружен  ✗ падает"),
                    "  " + tr("⚠ битый (программа удалена)  ⛔ отключён вами"),
                    "",
                    "  " + p.color("s", t.bold) + tr(" — собрать список   ") +
                    p.color("f", t.bold) + tr(" — фильтр «проблемные»"),
                    "",
                    "  " + p.color(tr("Отключение обратимо: plist сохраняется в "
                                      "~/.mac_tweaker/disabled/"), t.dim)]
            return out
        body_h = max(4, ctx.height - len(out) - 9)
        out.extend(self.list.render(p, w - 2, body_h, columns=self.columns))
        self._sync()
        sel = [i for i in self.items if i.selected]
        out.append(p.sep(w))
        cur = self.list.current
        extra = ""
        if cur and isinstance(cur.meta, startup.LaunchItem):
            it = cur.meta
            extra = f"  |  {truncate(it.command, max(10, w - 40))}"
        out.append(truncate(f"  отмечено: {len(sel)}{extra}", w - 2))
        return out

    def on_key(self, key: str, ctx: RenderContext) -> Optional[Screen]:
        if key == "s" or key == "r":
            self.do_scan(); return None
        if key == "f":
            self.filter_idx = (self.filter_idx + 1) % len(self.FILTERS)
            self.rebuild(); return None
        if key in (Key.UP, "k"):
            self.list.move(-1); return None
        if key in (Key.DOWN, "j"):
            self.list.move(1); return None
        if key == Key.PAGEUP:
            self.list.page(ctx.body_height, up=True); return None
        if key == Key.PAGEDOWN:
            self.list.page(ctx.body_height); return None
        if key == Key.SPACE:
            self.list.toggle(); self._sync(); return None
        if key == "a":
            self.list.toggle_all(); self._sync(); return None
        if key == Key.ENTER:
            cur = self.list.current
            if cur and isinstance(cur.meta, startup.LaunchItem):
                return ItemDetails(self.app, cur.meta)
            return None
        if key == "d":
            self._disable(); return None
        if key == "e":
            self._enable(); return None
        return super().on_key(key, ctx)

    def _selected(self) -> List[startup.LaunchItem]:
        self._sync()
        return [i for i in self.items if i.selected]

    def _disable(self) -> None:
        sel = self._selected()
        if not sel:
            self.app.say(tr("Отметьте элементы пробелом"), "warn"); return
        blocked = [i for i in sel if not i.disable_allowed]
        work_items = [i for i in sel if i.disable_allowed]
        if not work_items:
            self.app.alert(tr("Нельзя отключить"),
                           [tr("Все отмеченные элементы защищены системой (SIP) "
                               "или являются критическими.")])
            return

        def act(res: str) -> None:
            if res != "y":
                self.app.say("Отменено", "warn"); return
            need_root = any(i.domain == startup.DOMAIN_DAEMON for i in work_items)
            use_sudo = need_root and self.app.sudo_or_skip()
            results = startup.disable(work_items, self.app.paths, use_sudo)
            okc = sum(1 for _, ok, _m in results if ok)
            fails = [f"{i.label}: {m}" for i, ok, m in results if not ok]
            self.app.journal.add("startup-disable", f"{okc} элементов",
                                 {"labels": [i.label for i in work_items]})
            msg = [tr("Отключено: {ok} из {total}").format(ok=okc, total=len(work_items))]
            if blocked:
                msg.append(tr("Пропущено защищённых: {n}").format(n=len(blocked)))
            msg += fails[:6]
            msg.append("")
            msg.append(tr("Вернуть: отметьте и нажмите «e»"))
            self.app.alert(tr("Автозагрузка"), msg,
                           kind="ok" if not fails else "warn")
            self.do_scan()

        lines = [tr("Отключить элементов: {n}").format(n=len(work_items)), "",
                 tr("Они будут сняты с launchd, а их plist-файлы перенесены в"),
                 tr("~/.mac_tweaker/disabled/ — включение восстанавливает всё обратно."),
                 ""]
        if any(i.domain == startup.DOMAIN_DAEMON for i in work_items):
            lines.append(tr("Есть демоны root — потребуется пароль sudo."))
        if blocked:
            lines.append(tr("Защищённых пропущено: {n}").format(n=len(blocked)))
        self.app.confirm(tr("Отключение автозагрузки"), lines,
                         yes_label=tr("отключить"), no_label=tr("Отмена"),
                         kind="warn", callback=act)

    def _enable(self) -> None:
        sel = self._selected() or [i for i in self.items
                                   if i.state == startup.STATE_DISABLED]
        if not sel:
            self.app.say(tr("Нет отключённых элементов"), "warn"); return
        need_root = any(i.domain == startup.DOMAIN_DAEMON for i in sel)
        use_sudo = need_root and self.app.sudo_or_skip()
        results = startup.enable(sel, self.app.paths, use_sudo)
        okc = sum(1 for _, ok, _m in results if ok)
        self.app.journal.add("startup-enable", f"{okc} элементов",
                             {"labels": [i.label for i in sel]})
        fails = [f"{i.label}: {m}" for i, ok, m in results if not ok]
        self.app.alert(tr("Включение"),
                       [tr("Включено: {ok} из {total}").format(ok=okc, total=len(sel))]
                       + fails[:6])
        self.do_scan()


class ItemDetails(Screen):
    title = "элемент автозагрузки"
    hints = (("d", "отключить"), ("e", "включить"), ("o", "показать в Finder"))

    def __init__(self, app: App, item: startup.LaunchItem):
        super().__init__(app)
        self.it = item

    def render(self, ctx: RenderContext) -> List[str]:
        p, t = self.app.p, self.app.theme
        w = ctx.width
        it = self.it
        out = [p.hline(w, t.tl, t.tr, f" {it.label} ")]
        yesno = lambda b: tr("Да") if b else tr("Нет")  # noqa: E731
        rows = [
            (tr("Тип"), tr(it.domain_label) + (f" / {it.kind}" if it.kind else "")),
            (tr("Состояние"), f"{tr(it.state_mark)}  (pid {it.pid}, {it.last_exit})"),
            (tr("Путь"), self.app.paths.short(it.path) if it.path else "—"),
            (tr("Команда"), it.command or "—"),
            (tr("Разработчик"), it.developer or tr("не подписан / неизвестно")),
            (tr("Приложение"), it.app_name or "—"),
            ("RunAtLoad", yesno(it.run_at_load)),
            ("KeepAlive", yesno(it.keep_alive)),
            (tr("Размер plist"), human(it.size)),
            (tr("Изменён"), ago(it.mtime)),
            (tr("Защита"), tr("нельзя отключать (системный)") if not it.disable_allowed
             else tr("можно отключать")),
        ]
        for k, v in rows:
            out.append("  " + pad(p.color(k, t.dim), 16) + truncate(v, w - 18))
        if it.notes:
            out.append(p.hline(w, t.lt, t.rt, tr(" Заметки ")))
            for n in it.note_texts():
                out.append("  " + p.color("• " + n, t.yellow))
        out.append(p.hline(w, t.lt, t.rt))
        out.append("  " + p.color(tr("Отключение сохраняет plist в "
                                     "~/.mac_tweaker/disabled/ — это обратимо."), t.dim))
        return out

    def on_key(self, key: str, ctx: RenderContext) -> Optional[Screen]:
        if key == "o" and self.it.path:
            run(["open", "-R", str(self.it.path)], timeout=20)
            self.app.say(tr("Открыто в Finder"), "ok")
            return None
        if key == "d" and self.it.disable_allowed:
            res = startup.disable([self.it], self.app.paths, self.app.use_sudo)
            ok, msg = res[0][1], res[0][2]
            self.app.say(msg, "ok" if ok else "bad")
            return None
        if key == "e":
            res = startup.enable([self.it], self.app.paths, self.app.use_sudo)
            self.app.say(res[0][2], "ok" if res[0][1] else "bad")
            return None
        return super().on_key(key, ctx)


# --------------------------------------------------------------------------- #
#  Настройки (defaults)
# --------------------------------------------------------------------------- #

class TweaksScreen(Screen):
    title = "настройки системы"
    hints = (("Пробел", "отметить"), ("a", "всё"), ("Enter", "включить"),
             ("Backspace", "откатить"), ("x", "экспорт"))

    def on_lang_change(self, ctx: RenderContext) -> None:
        if self.loaded:
            self.rebuild()

    def __init__(self, app: App):
        super().__init__(app)
        self.tweaks = tweaks.all_tweaks()
        self.list = ListView(multi=True)
        self.loaded = False
        self.columns = [(6, "left"), (-36, "left"), (-44, "left")]

    def do_load(self) -> None:
        def work(tick):
            tweaks.refresh(self.tweaks, progress=tick)
        self.app.task("Чтение текущих настроек", work)
        self.loaded = True
        self.rebuild()
        on = sum(1 for t in self.tweaks if t.state)
        self.app.say(tr("Твиков: {n} • уже включено: {on}")
                     .format(n=len(self.tweaks), on=on), "info")

    def rebuild(self) -> None:
        p, t = self.app.p, self.app.theme
        rows: List[Row] = []
        for sec in tweaks.sections(self.tweaks):
            group = [x for x in self.tweaks if x.section == sec]
            rows.append(Row(cells=[f"── {tr(sec)} • {len(group)}"], selectable=False,
                            dim=True))
            for tw in group:
                state = p.color("ON " if get_lang() == "en" else "ВКЛ ", t.green) \
                    if tw.state else p.color("off" if get_lang() == "en" else "выкл", t.dim)
                name = tr(tw.name) + (p.color(" !", t.yellow) if tw.risky else "")
                desc = truncate(tr(tw.description), 52)
                rows.append(Row(cells=[state, name, p.color(desc, t.dim)],
                                checked=False, meta=tw))
        self.list = ListView(rows, multi=True)

    def _sync(self) -> List[tweaks.Tweak]:
        out = []
        for r in self.list.rows:
            if isinstance(r.meta, tweaks.Tweak) and r.checked:
                out.append(r.meta)
        return out

    def render(self, ctx: RenderContext) -> List[str]:
        p, t = self.app.p, self.app.theme
        w = ctx.width
        out = [p.hline(w, t.tl, t.tr, " обратимые настройки через defaults ")]
        if not self.loaded:
            out += ["",
                    "  Finder, Dock, screenshots, interface, privacy,",
                    "  performance — " if get_lang() == "en" else
                    "  Finder, Dock, скриншоты, интерфейс, приватность,",
                    "  performance — " if get_lang() == "en" else
                    "  производительность — всего "
                    f"{len(self.tweaks)} " + ("switches." if get_lang() == "en"
                                              else "переключателей."),
                    "",
                    "  Every change is reversible: apply / revert." if get_lang() == "en"
                    else "  Каждое изменение обратимо: «включить» / «откатить».",
                    "  Export current settings first (key “x”)." if get_lang() == "en"
                    else "  Перед массовым применением рекомендуется экспорт",
                    "  " + ("of current settings (key “x”)." if get_lang() == "en"
                            else "текущих настроек (клавиша «x»)."),
                    "",
                    "  " + p.color("Enter", t.bold) +
                    (" — read current states" if get_lang() == "en"
                     else " — прочитать текущие состояния")]
            return out
        body_h = max(4, ctx.height - len(out) - 9)
        out.extend(self.list.render(p, w - 2, body_h, columns=self.columns))
        sel = self._sync()
        out.append(p.sep(w))
        out.append("  " + tr("отмечено: {n}   ").format(n=p.color(str(len(sel)), t.bold))
                   + p.color(tr("Enter — включить"), t.dim) + "   "
                   + p.color(tr("Backspace — вернуть как было"), t.dim))
        return out

    def on_key(self, key: str, ctx: RenderContext) -> Optional[Screen]:
        if not self.loaded:
            if key in (Key.ENTER, "s", "r"):
                self.do_load()
                return None
            return super().on_key(key, ctx)
        if key in (Key.UP, "k"):
            self.list.move(-1); return None
        if key in (Key.DOWN, "j"):
            self.list.move(1); return None
        if key == Key.PAGEUP:
            self.list.page(ctx.body_height, up=True); return None
        if key == Key.PAGEDOWN:
            self.list.page(ctx.body_height); return None
        if key == Key.SPACE:
            self.list.toggle(); return None
        if key == "a":
            self.list.toggle_all(); return None
        if key == Key.ENTER:
            self._apply(on=True); return None
        if key == Key.BACKSPACE:
            self._apply(on=False); return None
        if key == "x":
            self._export(); return None
        if key == "i":
            self._import(); return None
        return super().on_key(key, ctx)

    def _apply(self, on: bool) -> None:
        sel = self._sync()
        if not sel:
            cur = self.list.current
            if cur and isinstance(cur.meta, tweaks.Tweak):
                sel = [cur.meta]
        if not sel:
            self.app.say(tr("Отметьте твики пробелом"), "warn"); return
        risky = [t for t in sel if t.risky]
        logout = [t for t in sel if t.need_logout]

        def act(res: str) -> None:
            if res != "y":
                self.app.say("Отменено", "warn"); return
            results = tweaks.apply(sel, on=on, progress=None)
            okc = sum(1 for _, ok, _m in results if ok)
            self.app.journal.add("tweaks", f"{okc}/{len(sel)}",
                                 {"on": on, "ids": [t.tid for t in sel]})
            msgs = [(tr("Применено: {ok} из {total}") if on
                     else tr("Откачено: {ok} из {total}")).format(ok=okc, total=len(sel))]
            msgs += [f"{t.name}: {m}" for t, ok, m in results if not ok][:6]
            if logout:
                msgs.append("")
                msgs.append(tr("Часть изменений заработает после выхода из системы."))
            self.app.alert(tr("Настройки системы"), msgs)
            self.do_load()

        action = tr("включить") if on else tr("вернуть в исходное")
        lines = [tr("Твиков: {n} → {action}").format(n=len(sel), action=action), ""]
        lines += [f"• {tr(t.name)}" for t in sel[:8]]
        if len(sel) > 8:
            lines.append(f"… +{len(sel) - 8}")
        if risky:
            lines += ["", tr("Есть рискованные: {n} — прочитайте описания!").format(n=len(risky))]
        if logout:
            lines.append(tr("Потребуется выход из системы: {n}").format(n=len(logout)))
        self.app.confirm(tr("Настройки системы"), lines,
                         yes_label=tr("Применить"), no_label=tr("Отмена"),
                         kind="warn" if risky else "info", callback=act)

    def _export(self) -> None:
        def work(tick):
            tick(0, 1, tr("экспортирую defaults…"))
            ok, msg = tweaks.export_defaults(self.app.paths)
            tick(1, 1, "")
            self._export_result = (ok, msg)
        self._export_result = (False, "")
        self.app.task("Экспорт настроек", work)
        ok, msg = self._export_result
        self.app.alert(tr("Экспорт"), [msg], kind="ok" if ok else "warn")

    def _import(self) -> None:
        backups = tweaks.list_backups(self.app.paths)
        if not backups:
            self.app.alert(tr("Импорт"), [tr("Резервных копий настроек не найдено."),
                                           tr("Сначала нажмите «x» (экспорт).")])
            return

        def act(res: str) -> None:
            if res != "y":
                return
            ok, msg = tweaks.import_defaults(self.app.paths, backups[0])
            self.app.journal.add("tweaks-import", backups[0].name)
            self.app.alert("Импорт", [msg], kind="ok" if ok else "warn")

        self.app.confirm(tr("Импорт"),
                         [tr("Восстановить из {name}?").format(name=backups[0].name),
                          f"{ago(backups[0].stat().st_mtime)}", "",
                          tr("Текущие настройки будут перезаписаны.")],
                         yes_label=tr("Восстановить"), no_label=tr("Отмена"),
                         kind="warn", callback=act)


# --------------------------------------------------------------------------- #
#  Анализ диска
# --------------------------------------------------------------------------- #

class DiskScreen(Screen):
    title = "анализ диска"
    hints = (("Enter", "внутрь"), ("Backspace", "наверх"), ("r", "обновить"),
             ("b", "крупные файлы"))

    def __init__(self, app: App):
        super().__init__(app)
        self.root = app.paths.home
        self.rows_data: List[Tuple[Path, int, bool]] = []
        self.list = ListView(multi=False)
        self.bigs: List[leftovers.BigFile] = []
        self.show_big = False

    def on_enter(self, ctx: RenderContext) -> None:
        if not self.rows_data:
            self.refresh()

    def refresh(self) -> None:
        def work(tick):
            tick(0, 0, tr("считаю {path}…").format(
                path=self.app.paths.short(self.root)))
            self.rows_data = _dir_sizes(self.root, tick=tick)
            tick(1, 1, "")
        self.app.task("Анализ каталога", work)
        rows = []
        for pth, size, isdir in self.rows_data:
            name = pth.name + ("/" if isdir else "")
            cell = pad(human(size), 9, "right") + "  " + (
                self.app.p.color(name, self.app.theme.bold) if isdir
                else self.app.p.color(name, self.app.theme.dim))
            rows.append(Row(cells=[cell], meta=(pth, isdir)))
        self.list = ListView(rows, multi=False)

    def render(self, ctx: RenderContext) -> List[str]:
        p, t = self.app.p, self.app.theme
        w = ctx.width
        si = self.app.refresh_sysinfo()
        head = f" {self.app.paths.short(self.root)} "
        out = [p.hline(w, t.tl, t.tr, head)]
        if si.disks:
            d = si.disks[0]
            out.append("  " + p.color(
                f"{tr('свободно')} {human(d.free)} / {human(d.total)}"
                f"  ({100 - d.percent:.0f}%)", t.dim))
        if self.show_big and self.bigs:
            out.append(p.hline(w, t.lt, t.rt, tr(" Крупные файлы ")))
            for f in self.bigs[:ctx.height - 8]:
                out.append("  " + pad(human(f.size), 9, "right") + "  " +
                           p.color(self.app.paths.short(f.path), t.dim))
            return out
        body_h = max(4, ctx.height - len(out) - 6)
        out.extend(self.list.render(p, w - 2, body_h))
        return out

    def on_key(self, key: str, ctx: RenderContext) -> Optional[Screen]:
        if key == "r":
            self.refresh(); return None
        if key == "b":
            if not self.bigs:
                def work(tick):
                    self.bigs = leftovers.big_files(self.app.paths, min_mb=300,
                                                    limit=40, progress=tick)
                self.app.task("Поиск крупных файлов", work)
            self.show_big = not self.show_big
            return None
        if key in (Key.UP, "k"):
            self.list.move(-1); return None
        if key in (Key.DOWN, "j"):
            self.list.move(1); return None
        if key == Key.PAGEDOWN:
            self.list.page(ctx.body_height); return None
        if key == Key.PAGEUP:
            self.list.page(ctx.body_height, up=True); return None
        if key == Key.ENTER and not self.show_big:
            cur = self.list.current
            if cur and cur.meta:
                path, isdir = cur.meta
                if isdir:
                    self.root = path
                    self.refresh()
            return None
        if key == Key.BACKSPACE:
            if self.show_big:
                self.show_big = False
            elif self.root != self.app.paths.home and self.root.parent != self.root:
                self.root = self.root.parent
                self.refresh()
            return None
        return super().on_key(key, ctx)


def _dir_sizes(root: Path, limit: int = 200,
               tick=None) -> List[Tuple[Path, int, bool]]:
    out: List[Tuple[Path, int, bool]] = []
    entries = safe_scandir(root)
    for i, e in enumerate(entries):
        if tick:
            tick(i, len(entries), e.name)
        try:
            p = Path(e.path)
            if e.is_symlink():
                continue
            isdir = e.is_dir(follow_symlinks=False)
            size = dir_size(p)[0] if isdir else e.stat().st_size
            out.append((p, size, isdir))
        except OSError:
            continue
    out.sort(key=lambda x: -x[1])
    return out[:limit]


# --------------------------------------------------------------------------- #
#  Журнал и откат
# --------------------------------------------------------------------------- #

class LogScreen(Screen):
    title = "журнал и откат"
    hints = (("u", "откат последней сессии"), ("r", "обновить"),
             ("Backspace", "откат автозагрузки"))

    def on_lang_change(self, ctx: RenderContext) -> None:
        self.load()

    def __init__(self, app: App):
        super().__init__(app)
        self.entries: List[Dict] = []
        self.disabled: List[startup.LaunchItem] = []
        self.list = ListView(multi=False)
        self.load()

    def load(self) -> None:
        self.entries = Journal.load(self.app.paths)[-400:]
        self.disabled = startup.disabled_items(self.app.paths)
        rows: List[Row] = []
        p, t = self.app.p, self.app.theme
        if self.disabled:
            rows.append(Row(cells=[tr("── Отключённая автозагрузка • {n}")
                                    .format(n=len(self.disabled))],
                            selectable=False, dim=True))
            for it in self.disabled:
                rows.append(Row(cells=[f"{it.label}  " +
                                       p.color(ago(it.mtime), t.dim)], meta=it))
        rows.append(Row(cells=[tr("── Журнал действий • {n} записей")
                                .format(n=len(self.entries))],
                        selectable=False, dim=True))
        for e in reversed(self.entries):
            rows.append(Row(cells=[p.color(e.get("ts", "")[11:], t.dim) + "  " +
                                   pad(e.get("kind", ""), 18) +
                                   truncate(e.get("target", ""), 60)],
                            meta=e, dim=True))
        self.list = ListView(rows, multi=False)

    def render(self, ctx: RenderContext) -> List[str]:
        p, t = self.app.p, self.app.theme
        w = ctx.width
        out = [p.hline(w, t.tl, t.tr, tr(" журнал: {path} ").format(
            path=self.app.paths.short(self.app.paths.state_dir)))]
        body_h = max(4, ctx.height - len(out) - 6)
        out.extend(self.list.render(p, w - 2, body_h))
        return out

    def on_key(self, key: str, ctx: RenderContext) -> Optional[Screen]:
        if key == "r":
            self.load(); self.app.say(tr("Журнал обновлён"), "ok"); return None
        if key in (Key.UP, "k"):
            self.list.move(-1); return None
        if key in (Key.DOWN, "j"):
            self.list.move(1); return None
        if key == Key.PAGEDOWN:
            self.list.page(ctx.body_height); return None
        if key == Key.PAGEUP:
            self.list.page(ctx.body_height, up=True); return None
        if key == "u":
            self._undo_trash(); return None
        if key == Key.BACKSPACE:
            self._restore_startup(); return None
        if key == Key.ENTER:
            cur = self.list.current
            if cur and isinstance(cur.meta, startup.LaunchItem):
                return ItemDetails(self.app, cur.meta)
            return None
        return super().on_key(key, ctx)

    def _undo_trash(self) -> None:
        def act(res: str) -> None:
            if res != "y":
                return
            restored, problems = self.app.journal.undo_last_session()
            self.app.say(tr("Восстановлено из Корзины: {n}").format(n=restored)
                         + (tr("проблем: {n}").format(n=len(problems)) if problems else ""),
                         "ok" if not problems else "warn")
            self.load()
        self.app.confirm(tr("Откат удаления"),
                         [tr("Вернуть из Корзины всё, что удалял Mac Crap Cleaner"),
                          tr("в этой сессии?"), "",
                          tr("Работает только для удаления в Корзину.")],
                         yes_label=tr("Вернуть"), no_label=tr("Отмена"), callback=act)

    def _restore_startup(self) -> None:
        if not self.disabled:
            self.app.say(tr("Нет отключённых элементов автозагрузки"), "warn")
            return

        def act(res: str) -> None:
            if res != "y":
                return
            results = startup.restore_all(self.app.paths, self.app.use_sudo)
            okc = sum(1 for _, ok, _m in results if ok)
            self.app.journal.add("startup-restore", f"{okc} элементов")
            self.app.alert(tr("Восстановление автозагрузки"),
                           [tr("Включено обратно: {ok} из {total}").format(ok=okc, total=len(results))] +
                           [f"{i.label}: {m}" for i, ok, m in results if not ok][:5])
            self.load()
        self.app.confirm(tr("Восстановление автозагрузки"),
                         [tr("Вернуть {n} отключённых элементов?")
                          .format(n=len(self.disabled))],
                         yes_label=tr("Вернуть"), no_label=tr("Отмена"), callback=act)


# --------------------------------------------------------------------------- #
#  APFS-снапшоты (иллюзия свободного места)
# --------------------------------------------------------------------------- #

class SnapshotsScreen(Screen):
    title = "APFS-снапшоты"
    hints = (("r", "обновить"), ("Пробел", "отметить"), ("d", "удалить отмеченные"),
             ("x", "удалить все"))

    def __init__(self, app: App):
        super().__init__(app)
        self.dates: List[str] = []
        self.loaded = False
        self.list = ListView(multi=True)
        self.feats = osprofile.get_os_features()

    def on_enter(self, ctx: RenderContext) -> None:
        if not self.loaded:
            self.refresh()

    def refresh(self) -> None:
        def work(tick):
            tick(0, 1, tr("читаю локальные снапшоты APFS…"))
            self.dates = osprofile.list_local_snapshots("/")
            tick(1, 1, "")
        self.app.task("APFS-снапшоты", work)
        self.loaded = True
        rows = [Row(cells=["  " + d], meta=d) for d in self.dates]
        self.list = ListView(rows, multi=True)

    def render(self, ctx: RenderContext) -> List[str]:
        p, t = self.app.p, self.app.theme
        w = ctx.width
        out = [p.hline(w, t.tl, t.tr, tr(" локальные снапшоты тома / "))]
        if not osprofile.snapshots_supported():
            out += ["", "  " + p.color(tr("Доступно только на macOS (tmutil)."), t.dim)]
            return out
        out += [
            "  " + tr("Почистили кэши, а Finder показывает то же свободное место?"),
            "  " + p.color(tr("Виноваты локальные снапшоты APFS: они удерживают "
                              "удалённые блоки данных."), t.dim),
            "",
        ]
        if not self.loaded:
            out.append("  " + p.color(tr("нажмите «r», чтобы прочитать список"), t.dim))
            return out
        if not self.dates:
            out.append("  " + p.color(tr("Локальных снапшотов нет — место не «зависло»."),
                                      t.green))
            return out
        out.append("  " + tr("Найдено снапшотов: {n}").format(
            n=p.color(str(len(self.dates)), t.bold)))
        body_h = max(4, ctx.height - len(out) - 8)
        out.extend(self.list.render(p, w - 2, body_h))
        out.append(p.sep(w))
        out.append("  " + p.color(tr("Удаление снапшотов требует sudo и необратимо: "
                                     "это точки восстановления Time Machine."),
                                  t.yellow))
        return out

    def _selected_dates(self) -> List[str]:
        return [r.meta for r in self.list.rows if r.checked and isinstance(r.meta, str)]

    def on_key(self, key: str, ctx: RenderContext) -> Optional[Screen]:
        if key == "r":
            self.refresh()
            self.app.say(tr("Снапшотов: {n}").format(n=len(self.dates)), "info")
            return None
        if key in (Key.UP, "k"):
            self.list.move(-1); return None
        if key in (Key.DOWN, "j"):
            self.list.move(1); return None
        if key == Key.PAGEDOWN:
            self.list.page(ctx.body_height); return None
        if key == Key.PAGEUP:
            self.list.page(ctx.body_height, up=True); return None
        if key == Key.SPACE:
            self.list.toggle(); return None
        if key == "a":
            self.list.toggle_all(); return None
        if key == "d":
            self._delete(self._selected_dates()); return None
        if key == "x":
            self._delete(list(self.dates)); return None
        return super().on_key(key, ctx)

    def _delete(self, dates: List[str]) -> None:
        if not dates:
            self.app.say(tr("Ничего не отмечено"), "warn")
            return
        if not self.app.sudo_or_skip():
            self.app.say(tr("sudo недоступен — снапшоты не удалить"), "warn")
            return

        def act(res: str) -> None:
            if res != "y":
                self.app.say(tr("Отменено"), "warn")
                return

            def work(tick):
                ok = 0
                errs = 0
                for i, d in enumerate(dates):
                    tick(i, len(dates), d)
                    good, _msg = osprofile.delete_local_snapshot(
                        d, use_sudo=self.app.use_sudo)
                    ok += 1 if good else 0
                    errs += 0 if good else 1
                tick(len(dates), len(dates), "")
                self._result = (ok, errs)
            self._result = (0, 0)
            self.app.task("Удаление снапшотов", work)
            ok, errs = self._result
            self.app.journal.add("snapshots", f"{ok}/{len(dates)}")
            self.app.say(tr("Удалено снапшотов: {ok} из {n}").format(
                ok=ok, n=len(dates)) + (f", {tr('ошибок')}: {errs}" if errs else ""),
                "ok" if not errs else "warn")
            self.refresh()

        self.app.confirm(tr("APFS-снапшоты"),
                         [tr("Удалить снапшотов: {n}?").format(n=len(dates)), "",
                          tr("Это НЕОБРАТИМО: снапшоты — точки восстановления "
                             "Time Machine на этом томе."),
                          tr("Место освободится сразу после удаления.")],
                         yes_label=tr("удалить"), no_label=tr("Отмена"),
                         kind="danger", callback=act)


# --------------------------------------------------------------------------- #
#  Автоочистка по расписанию (launchd)
# --------------------------------------------------------------------------- #

class ScheduleScreen(Screen):
    title = "автоочистка по расписанию"
    hints = (("Enter", "установить"), ("d", "удалить агент"), ("r", "обновить"),
             ("w", "день"), ("h", "час"), ("p", "профиль"))

    def __init__(self, app: App):
        super().__init__(app)
        self.weekday = 0
        self.hour = 4
        self.minute = 0
        self.profile = "basic"
        self.status: Optional[schedule.AgentStatus] = None

    def on_enter(self, ctx: RenderContext) -> None:
        if self.status is None:
            self.reload()

    def reload(self) -> None:
        self.status = schedule.agent_status(self.app.paths)

    def render(self, ctx: RenderContext) -> List[str]:
        p, t = self.app.p, self.app.theme
        w = ctx.width
        st = self.status or schedule.agent_status(self.app.paths)
        out = [p.hline(w, t.tl, t.tr, tr(" launchd-агент еженедельной очистки "))]
        for ln in st.summary(self.app.paths):
            out.append("  " + ln)
        out.append(p.hline(w, t.lt, t.rt, tr(" Параметры ")))
        wd = p.color(tr(schedule.WEEKDAYS.get(self.weekday, "?")), t.bold)
        out.append("  " + tr("Когда: ") + wd + p.color(
            f"  {self.hour:02d}:{self.minute:02d}", t.bold))
        out.append("  " + tr("Профиль: ") + p.color(self.profile, t.bold))
        out.append("  " + tr("Запуск: ") + p.color(
            truncate(st.runner or "—", max(10, w - 16)), t.dim))
        out += [
            "",
            "  " + p.color(tr("Агент запускает maccc clean --profile {p} -y "
                               "(всё в Корзину, без sudo, без внешних команд).")
                            .format(p=self.profile), t.dim),
            "  " + p.color(tr("Тихий отчёт каждого запуска пишется в "
                               "~/.mac_tweaker/scheduled.log"), t.dim),
            "",
            "  " + p.color("w / h / p", t.bold) + "  "
            + p.color(tr("— день недели / час / профиль"), t.dim),
            "  " + p.color("Enter / d", t.bold) + "  "
            + p.color(tr("— создать или удалить агент"), t.dim),
        ]
        return out

    def on_key(self, key: str, ctx: RenderContext) -> Optional[Screen]:
        if key == "r":
            self.reload()
            self.app.say(tr("Статус обновлён"), "ok")
            return None
        if key == "w":
            self.weekday = (self.weekday + 1) % 7
            return None
        if key == "h":
            self.hour = (self.hour + 1) % 24
            return None
        if key == "p":
            profiles = ("basic", "dev")
            i = profiles.index(self.profile) if self.profile in profiles else 0
            self.profile = profiles[(i + 1) % len(profiles)]
            return None
        if key == Key.ENTER:
            self._install()
            return None
        if key == "d":
            self._uninstall()
            return None
        return super().on_key(key, ctx)

    def _install(self) -> None:
        def act(res: str) -> None:
            if res != "y":
                self.app.say(tr("Отменено"), "warn")
                return
            ok, msg = schedule.install_agent(
                self.app.paths, profile=self.profile, weekday=self.weekday,
                hour=self.hour, minute=self.minute)
            self.app.journal.add("schedule-install", schedule.AGENT_LABEL,
                                 {"ok": ok, "profile": self.profile})
            self.reload()
            self.app.alert(tr("Автоочистка по расписанию"), [msg],
                           kind="ok" if ok else "warn")

        wd = tr(schedule.WEEKDAYS.get(self.weekday, "?"))
        self.app.confirm(
            tr("Автоочистка по расписанию"),
            [tr("Создать агент {label}?").format(label=schedule.AGENT_LABEL), "",
             tr("Каждый {weekday} в {hour:02d}:{minute:02d}: очистка профиля "
                "«{profile}», всё в Корзину, отчёт в ~/.mac_tweaker/").format(
                    weekday=wd, hour=self.hour, minute=self.minute,
                    profile=self.profile),
             tr("Файл: ~/Library/LaunchAgents/{label}.plist").format(
                    label=schedule.AGENT_LABEL)],
            yes_label=tr("создать"), no_label=tr("Отмена"), kind="info",
            callback=act)

    def _uninstall(self) -> None:
        def act(res: str) -> None:
            if res != "y":
                return
            ok, msg = schedule.uninstall_agent(self.app.paths)
            self.app.journal.add("schedule-uninstall", schedule.AGENT_LABEL,
                                 {"ok": ok})
            self.reload()
            self.app.alert(tr("Автоочистка по расписанию"), [msg],
                           kind="ok" if ok else "warn")

        self.app.confirm(tr("Автоочистка по расписанию"),
                         [tr("Удалить агент и снять его с launchd?")],
                         yes_label=tr("удалить"), no_label=tr("Отмена"),
                         kind="warn", callback=act)


# --------------------------------------------------------------------------- #
#  Справка
# --------------------------------------------------------------------------- #

class HelpScreen(Screen):
    title = "справка"
    hints = (("↑↓", "прокрутка"),)

    def __init__(self, app: App):
        super().__init__(app)
        self.offset = 0
        self._lang = None
        self.lines: List[str] = []

    def _ensure(self) -> None:
        lang = get_lang()
        if lang != self._lang:
            self._lang = lang
            self.offset = 0
            self.lines = (HELP_TEXT_EN if lang == "en" else HELP_TEXT).splitlines()

    def render(self, ctx: RenderContext) -> List[str]:
        self._ensure()
        p, t = self.app.p, self.app.theme
        w = ctx.width
        body_h = max(4, ctx.height - 6)
        view = self.lines[self.offset:self.offset + body_h]
        out = []
        import re as _re
        for ln in view:
            stripped = ln.strip()
            if not stripped:
                out.append("")
            elif _re.fullmatch(r"[-─]{3,}", stripped):
                continue                      # декоративные линейки пропускаем
            elif ln.startswith(("Управление", "Безопасность", "Профили очистки",
                                "Экран «Остатки", "Автоочистка", "APFS-снапшоты")):
                out.append(p.hline(w, t.lt, t.rt, f" {stripped} "))
            else:
                parts = [x for x in _re.split(r" {2,}", stripped, maxsplit=1)]
                if len(parts) == 2 and len(parts[0]) <= 20:
                    out.append("  " + pad(p.color(parts[0].upper(), t.bold), 21) +
                               truncate(parts[1], max(8, w - 24)))
                else:
                    out.append("  " + truncate(stripped, w - 2))
        return out

    def on_key(self, key: str, ctx: RenderContext) -> Optional[Screen]:
        if key in (Key.UP, "k"):
            self.offset = max(0, self.offset - 1); return None
        if key in (Key.DOWN, "j"):
            self.offset = min(max(0, len(self.lines) - ctx.body_height),
                              self.offset + 1); return None
        if key == Key.PAGEDOWN:
            self.offset = min(max(0, len(self.lines) - ctx.body_height),
                              self.offset + ctx.body_height); return None
        if key == Key.PAGEUP:
            self.offset = max(0, self.offset - ctx.body_height); return None
        return super().on_key(key, ctx)
