"""
mactweaker.ui — псевдографический интерфейс в терминале.

Движок на чистых ANSI-escape последовательностях + termios (без curses и без
сторонних библиотек): рисует рамки, таблицы, меню, диалоги и прогресс-бары,
читает стрелки/пробел/Enter в raw-режиме, корректно переживает ресайз окна.

Важно для тестируемости: всё рисование — чистые функции, возвращающие
список строк. Ввод отделён от рендера, поэтому экраны можно «фотографировать»
в тестах без терминала.

Если stdout не TTY ( pipe, cron, тесты ) — автоматически включается
PlainUI: те же экраны, но текстовые меню с вводом по номерам.
"""

from __future__ import annotations

import os
import shutil
import signal
import sys
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .i18n import APP_TITLE  # заголовок окна терминала (OSC 0)

# --------------------------------------------------------------------------- #
#  Клавиши
# --------------------------------------------------------------------------- #


class Key:
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    HOME = "home"
    END = "end"
    PAGEUP = "pageup"
    PAGEDOWN = "pagedown"
    ENTER = "enter"
    ESC = "esc"
    SPACE = "space"
    TAB = "tab"
    BACKSPACE = "backspace"
    CTRL_C = "ctrl_c"
    CTRL_L = "ctrl_l"
    DELETE = "delete"


_ESC_MAP = {
    "[A": Key.UP, "[B": Key.DOWN, "[C": Key.RIGHT, "[D": Key.LEFT,
    "[H": Key.HOME, "[F": Key.END, "[1~": Key.HOME, "[4~": Key.END,
    "[5~": Key.PAGEUP, "[6~": Key.PAGEDOWN, "[Z": Key.TAB,
    "[2~": "ins", "[3~": Key.DELETE,
    "OA": Key.UP, "OB": Key.DOWN, "OC": Key.RIGHT, "OD": Key.LEFT,
}


def decode_key(seq: str) -> str:
    """Превратить сырую последовательность терминала в имя клавиши/символ."""
    if not seq:
        return ""
    if seq in ("\r", "\n"):
        return Key.ENTER
    if seq == "\x1b":
        return Key.ESC
    if seq == " ":
        return Key.SPACE
    if seq == "\t":
        return Key.TAB
    if seq in ("\x7f", "\x08"):
        return Key.BACKSPACE
    if seq == "\x03":
        return Key.CTRL_C
    if seq == "\x0c":
        return Key.CTRL_L
    if seq.startswith("\x1b"):
        rest = seq[1:]
        if rest in _ESC_MAP:
            return _ESC_MAP[rest]
        if rest.startswith("[<") or rest.startswith("[M"):
            return "mouse"          # прокрутка колесом — обработчики игнорируют
        return ""                   # неизвестная escape-последовательность
    return seq


# --------------------------------------------------------------------------- #
#  Цвета и тема
# --------------------------------------------------------------------------- #

@dataclass
class Theme:
    enabled: bool = True
    ascii_only: bool = False

    reset: str = "\033[0m"
    bold: str = "\033[1m"
    dim: str = "\033[2m"
    rev: str = "\033[7m"

    red: str = "\033[31m"
    green: str = "\033[32m"
    yellow: str = "\033[33m"
    blue: str = "\033[34m"
    magenta: str = "\033[35m"
    cyan: str = "\033[36m"
    white: str = "\033[37m"
    b_red: str = "\033[91m"
    b_green: str = "\033[92m"
    b_yellow: str = "\033[93m"
    b_blue: str = "\033[94m"
    b_magenta: str = "\033[95m"
    b_cyan: str = "\033[96m"

    # псевдографика
    h: str = "─"
    v: str = "│"
    tl: str = "╭"
    tr: str = "╮"
    bl: str = "╰"
    br: str = "╯"
    lt: str = "├"
    rt: str = "┤"
    dt: str = "┬"
    bt: str = "┴"
    cross: str = "┼"
    bullet: str = "•"
    arrow: str = "▸"
    checked: str = "█"
    unchecked: str = "░"
    ok: str = "✓"
    bad: str = "✗"
    warn: str = "!"
    cursor_on: str = "▣"
    cursor_off: str = "▢"

    def __post_init__(self) -> None:
        if self.ascii_only:
            self.h, self.v = "-", "|"
            self.tl = self.tr = self.bl = self.br = "+"
            self.lt = self.rt = self.dt = self.bt = self.cross = "+"
            self.bullet = "*"
            self.arrow = ">"
            self.checked = "#"
            self.unchecked = "."
            self.ok, self.bad, self.warn = "+", "x", "!"
            self.cursor_on, self.cursor_off = "[X]", "[ ]"
        if not self.enabled:
            for f in _COLOR_FIELDS:
                setattr(self, f, "")


_COLOR_FIELDS = ("reset", "bold", "dim", "rev", "red", "green", "yellow",
                 "blue", "magenta", "cyan", "white", "b_red", "b_green",
                 "b_yellow", "b_blue", "b_magenta", "b_cyan")


def field_names_of(cls) -> Iterable[str]:
    import dataclasses
    return [f.name for f in dataclasses.fields(cls)]


def detect_theme(force_ascii: bool = False, no_color: bool = False) -> Theme:
    color = (sys.stdout.isatty() and not no_color
             and os.environ.get("NO_COLOR") is None
             and os.environ.get("TERM") not in (None, "dumb"))
    ascii_only = force_ascii or os.environ.get("LC_ALL", "").lower() in ("c", "posix")
    if not ascii_only:
        try:
            enc = (getattr(sys.stdout, "encoding", "") or "").lower()
            ascii_only = enc not in ("", "utf-8", "utf8")
        except Exception:  # noqa: BLE001
            ascii_only = False
    return Theme(enabled=color, ascii_only=ascii_only)


# --------------------------------------------------------------------------- #
#  Работа с шириной строк (ANSI + юникод)
# --------------------------------------------------------------------------- #

_ANSI_RE = re.compile(r"\033\[[0-9;:?]*[a-zA-Z]")


def strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def dwidth(s: str) -> int:
    """Видимая ширина строки в колонках терминала."""
    s = strip_ansi(s)
    w = 0
    for ch in s:
        if unicodedata.combining(ch):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def truncate(s: str, width: int, ellipsis: str = "…") -> str:
    """Обрезать по видимой ширине, сохранив ANSI-коды."""
    if width <= 0:
        return ""
    if dwidth(s) <= width:
        return s
    out: List[str] = []
    w = 0
    limit = width - dwidth(ellipsis)
    i = 0
    while i < len(s):
        if s[i] == "\033":
            j = s.find("m", i)
            if j == -1:
                break
            out.append(s[i:j + 1])
            i = j + 1
            continue
        ch = s[i]
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if unicodedata.combining(ch):
            cw = 0
        if w + cw > limit:
            break
        out.append(ch)
        w += cw
        i += 1
    out.append(ellipsis)
    # закрывающий сброс только если цвет действительно включён
    if "\033[" in s:
        out.append("\033[0m")
    return "".join(out)


def pad(s: str, width: int, align: str = "left", fill: str = " ") -> str:
    gap = width - dwidth(s)
    if gap <= 0:
        return truncate(s, width)
    if align == "right":
        return fill * gap + s
    if align == "center":
        left = gap // 2
        return fill * left + s + fill * (gap - left)
    return s + fill * gap


# --------------------------------------------------------------------------- #
#  Элементы рисования
# --------------------------------------------------------------------------- #

class Painter:
    """Набор примитивов, которые возвращают готовые строки."""

    def __init__(self, theme: Theme):
        self.t = theme

    def color(self, s: str, *codes: str) -> str:
        if not codes:
            return s
        return "".join(codes) + s + self.t.reset

    #: символы «вертушки» и barber-pole заполнения прогресс-бара
    SPINNER: Tuple[str, ...] = ("|", "/", "-", "\\")

    def spin(self, tick: int) -> str:
        return self.SPINNER[tick % len(self.SPINNER)]

    def anim_bar(self, frac: Optional[float], width: int, tick: int,
                 empty: str = "·") -> str:
        """Прогресс-бар из циклических символов | / - \\ (barber-pole).

        frac=None — индетерминированный режим: бегущее окно символов,
        пока неизвестен общий объём работы.
        """
        width = max(4, width)
        if frac is None:
            span = max(4, width // 3)
            pos = tick % max(1, width - span + 1)
            return "".join(
                self.SPINNER[(tick + i) % len(self.SPINNER)]
                if pos <= i < pos + span else empty
                for i in range(width))
        frac = max(0.0, min(1.0, frac))
        n = int(round(frac * width))
        fill = "".join(self.SPINNER[(tick + i) % len(self.SPINNER)]
                       for i in range(n))
        head = self.spin(tick) if 0 < n < width else ""
        rest = width - n - (1 if head else 0)
        return fill + head + empty * max(0, rest)

    def bar(self, value: float, width: int, filled: Optional[str] = None,
            empty: Optional[str] = None) -> str:
        t = self.t
        filled = filled if filled is not None else t.checked
        empty = empty if empty is not None else t.unchecked
        value = max(0.0, min(1.0, value))
        n = int(round(value * width))
        return filled * n + empty * (width - n)

    def sep(self, width: int, title: str = "") -> str:
        """Горизонтальный разделитель ├────┤ (для колонтитулов внутри рамки)."""
        t = self.t
        if title:
            body = f" {title} "
            rest = max(0, width - dwidth(body) - 2)
            return self.color(t.lt + t.h + body + t.h * (rest - 1) + t.rt, t.dim)
        return self.color(t.lt + t.h * max(0, width - 2) + t.rt, t.dim)

    def hline(self, width: int, left: str = "", right: str = "",
              title: str = "") -> str:
        """Линия рамки. ВАЖНО: ровно `width` видимых символов — иначе строка
        переносится терминалом и под переносом остаётся мусор прошлого кадра."""
        t = self.t
        if title:
            body = f" {title} "
            # left(1) + h(1) + body + rest + right(1) == width
            rest = max(0, width - dwidth(body) - 3)
            line = (self.color(left + t.h, t.dim)
                    + self.color(body, t.bold)
                    + self.color(t.h * rest + right, t.dim))
            return truncate(line, width)
        return truncate(self.color(left + t.h * max(0, width - 2) + right,
                                    t.dim), width)

    def box_top(self, width: int, title: str = "") -> str:
        t = self.t
        if title:
            body = f" {title} "
            rest = max(0, width - dwidth(body) - 2)
            left = rest // 2
            return (self.color(t.tl + t.h * left, t.cyan)
                    + self.color(body, t.bold + t.b_cyan)
                    + self.color(t.h * (rest - left) + t.tr, t.cyan))
        return self.color(t.tl + t.h * (width - 2) + t.tr, t.cyan)

    def box_bottom(self, width: int) -> str:
        t = self.t
        return self.color(t.bl + t.h * (width - 2) + t.br, t.cyan)

    def box_row(self, text: str, width: int, align: str = "left") -> str:
        t = self.t
        inner = width - 2
        return (self.color(t.v, t.cyan)
                + pad(truncate(text, inner), inner, align)
                + self.color(t.v, t.cyan))

    def box(self, lines: Sequence[str], width: int, title: str = "") -> List[str]:
        out = [self.box_top(width, title)]
        for ln in lines:
            out.append(self.box_row(ln, width))
        out.append(self.box_bottom(width))
        return out

    def progress(self, done: int, total: int, width: int = 30,
                 label: str = "") -> str:
        t = self.t
        frac = (done / total) if total else 0.0
        bar = self.bar(frac, width, t.checked, t.unchecked)
        pct = f"{frac * 100:3.0f}%"
        text = f"[{bar}] {pct}"
        if label:
            text += f"  {truncate(label, max(4, width))}"
        return self.color(text, t.green if frac >= 1 else t.cyan)

    def kv(self, key: str, value: str, width: int, key_w: int = 0) -> str:
        key_w = key_w or (dwidth(key) + 2)
        return (pad(self.color(key, self.t.dim), key_w)
                + truncate(value, max(1, width - key_w)))

    def badge(self, text: str, kind: str = "info") -> str:
        colors = {"ok": self.t.green, "bad": self.t.red, "warn": self.t.yellow,
                  "info": self.t.cyan, "muted": self.t.dim, "hot": self.t.b_red}
        c = colors.get(kind, self.t.cyan)
        return self.color(f" {text} ", c)


# --------------------------------------------------------------------------- #
#  Списки и таблицы (модель, независимая от терминала)
# --------------------------------------------------------------------------- #

@dataclass
class Row:
    cells: List[str]
    checked: bool = False
    selectable: bool = True
    meta: Any = None
    dim: bool = False
    color: str = ""


class ListView:
    """Список строк с курсором, множественным выбором и прокруткой."""

    def __init__(self, rows: Optional[List[Row]] = None, multi: bool = True):
        self.rows: List[Row] = rows or []
        self.cursor = 0
        self.multi = multi
        self.offset = 0
        self.fill_width = 108      # ширина, под которую тянутся заголовки групп
        self.clamp()               # курсор сразу на выбираемой строке

    # -- данные --
    def set_rows(self, rows: List[Row], keep_selection: bool = True) -> None:
        """Заменить строки, по желанию сохранив отметки (сравнение по значению meta)."""
        old: set = set()
        if keep_selection:
            for r in self.rows:
                if r.checked and r.meta is not None:
                    try:
                        old.add(r.meta)
                    except TypeError:      # нехешируемый meta
                        old.add(id(r.meta))
        self.rows = rows
        for r in self.rows:
            if not keep_selection or r.meta is None:
                continue
            try:
                hit = r.meta in old
            except TypeError:
                hit = id(r.meta) in old
            if hit:
                r.checked = True
        self.clamp()

    @property
    def current(self) -> Optional[Row]:
        if not self.rows:
            return None
        return self.rows[self.cursor]

    def checked(self) -> List[Row]:
        return [r for r in self.rows if r.checked]

    def all_checked(self) -> bool:
        sel = [r for r in self.rows if r.selectable]
        return bool(sel) and all(r.checked for r in sel)

    def clamp(self) -> None:
        if not self.rows:
            self.cursor = 0
            self.offset = 0
            return
        self.cursor = max(0, min(self.cursor, len(self.rows) - 1))
        if not self.rows[self.cursor].selectable:
            i = self._nearest_selectable(self.cursor, 1)
            if i == -1:
                i = self._nearest_selectable(self.cursor, -1)
            if i != -1:
                self.cursor = i

    # -- навигация --
    def _nearest_selectable(self, start: int, step: int) -> int:
        i = start
        while 0 <= i < len(self.rows):
            if self.rows[i].selectable:
                return i
            i += step
        return -1

    def move(self, delta: int) -> None:
        """Сдвиг курсора с ПЕРЕСКОКОМ через неселектабельные строки
        (заголовки групп) в обе стороны — вверх так же свободно, как вниз."""
        if not self.rows:
            return
        step = 1 if delta > 0 else -1
        cur = self.cursor
        for _ in range(abs(delta)):
            nxt = cur + step
            while 0 <= nxt < len(self.rows) and not self.rows[nxt].selectable:
                nxt += step
            if 0 <= nxt < len(self.rows):
                cur = nxt
            else:
                break
        self.cursor = max(0, min(cur, len(self.rows) - 1))

    def page(self, size: int, up: bool = False) -> None:
        self.move(-size if up else size)

    def home(self) -> None:
        if not self.rows:
            self.cursor = 0
            return
        i = self._nearest_selectable(0, 1)
        self.cursor = i if i != -1 else 0

    def end(self) -> None:
        if not self.rows:
            self.cursor = 0
            return
        i = self._nearest_selectable(len(self.rows) - 1, -1)
        self.cursor = i if i != -1 else len(self.rows) - 1

    def toggle(self, row: Optional[Row] = None, advance: bool = True) -> None:
        r = row or self.current
        if r is None or not r.selectable:
            return
        if not self.multi:
            for x in self.rows:
                x.checked = False
        r.checked = not r.checked
        if advance:
            self.move(1)          # move() сам перескочит заголовок

    def toggle_all(self) -> None:
        target = not self.all_checked()
        for r in self.rows:
            if r.selectable:
                r.checked = target

    def ensure_visible(self, height: int) -> None:
        if height <= 0:
            return
        if self.cursor < self.offset:
            self.offset = self.cursor
        elif self.cursor >= self.offset + height:
            self.offset = self.cursor - height + 1

    # -- рендер --
    def render(self, painter: Painter, width: int, height: int,
               columns: Optional[Sequence[Tuple[int, str]]] = None,
               show_index: bool = False) -> List[str]:
        """columns = [(ширина_в_процентах или символах, выравнивание), ...]"""
        t = painter.t
        self.ensure_visible(height)
        out: List[str] = []
        if not self.rows:
            out.append(pad(painter.color("  (пусто)", t.dim), width))
            return out[:max(1, height)]
        view = self.rows[self.offset:self.offset + height]
        for i, r in enumerate(view):
            idx = self.offset + i
            active = idx == self.cursor
            if columns:
                line = self._render_columns(painter, r, width, columns, active,
                                            show_index, idx)
                if not r.selectable:
                    # заголовок группы: во всю ширину, без чекбокса
                    text = r.cells[0] if r.cells else ""
                    line = self._group_header(painter, text, width)
            elif not r.selectable:
                text = r.cells[0] if r.cells else ""
                line = self._group_header(painter, text, width)
            else:
                mark = ""
                if self.multi:
                    mark = (t.cursor_on if r.checked else t.cursor_off) + " "
                ptr = t.arrow if active else " "
                text = f"{ptr}{'' if not show_index else str(idx + 1) + '. '}{mark}{r.cells[0] if r.cells else ''}"
                line = pad(truncate(text, width - 1), width - 1)
            if active:
                line = painter.color(line, t.rev)
            elif r.dim:
                line = painter.color(line, t.dim)
            elif r.color:
                line = painter.color(line, r.color)
            out.append(line)
        while len(out) < height:
            out.append(" " * width)
        return out

    def _group_header(self, painter: Painter, text: str, width: int) -> str:
        """«── Название ─────────» во всю доступную ширину."""
        t = painter.t
        base = strip_ansi(text).rstrip(t.h).rstrip("-").rstrip()
        colored = text[:len(text) - len(text.rstrip(t.h).rstrip("-").rstrip())] \
            if False else text
        # сохраняем исходное оформление текста, но хвост дорисовываем сами
        fill = max(0, width - dwidth(base) - 5)
        return pad(base + " " + t.h * fill, width - 1)

    def _render_columns(self, painter: Painter, r: Row, width: int,
                        columns: Sequence[Tuple[int, str]], active: bool,
                        show_index: bool, idx: int) -> str:
        """Табличная строка.

        columns = [(ширина, выравнивание), ...]; ширина > 0 — фиксированная,
        ширина < 0 — доля в процентах от оставшегося места. Последний столбец
        всегда растягивается на остаток.
        """
        t = painter.t
        prefix = ""
        if show_index:
            prefix = pad(f"{idx + 1}", 3, "right") + " "
        if self.multi:
            prefix += (t.cursor_on if r.checked else t.cursor_off) + " "
        prefix += t.arrow if active else " "
        avail = max(8, width - dwidth(prefix))
        # (ширина префикса считается через dwidth, а не «на глаз»)

        # распределяем ширину: фиксированные как есть, отрицательные — доли
        n = min(len(columns), len(r.cells))
        cols = list(columns[:n])
        flex_total = sum(-cw for cw, _ in cols if cw < 0) or 1
        widths: List[int] = []
        used = 0
        for i, (cw, _al) in enumerate(cols):
            if cw > 0:
                w = cw
            else:
                w = int((avail - (n - 1)) * (-cw) / flex_total)
            w = max(3, w)
            widths.append(w)
            used += w
        # последний столбец забирает остаток
        if widths:
            rest = avail - (sum(widths[:-1]) + (n - 1))
            widths[-1] = max(6, rest)

        parts: List[str] = []
        for i, (w, (_cw, align)) in enumerate(zip(widths, cols)):
            parts.append(pad(truncate(r.cells[i], w), w, align))
        body = " ".join(parts)
        return prefix + pad(truncate(body, avail), avail)


# --------------------------------------------------------------------------- #
#  Терминал
# --------------------------------------------------------------------------- #

class Terminal:
    """Raw-режим, alternate screen, чтение клавиш, реакция на ресайз."""

    def __init__(self, theme: Theme):
        self.theme = theme
        self.width, self.height = shutil.get_terminal_size((100, 30))
        self._fd = None
        self._saved = None
        self._active = False

    # -- размер --
    def refresh_size(self) -> None:
        try:
            size = shutil.get_terminal_size()
            self.width, self.height = max(40, size.columns), max(10, size.lines)
        except (ValueError, OSError):
            pass

    # -- режим --
    def enter(self) -> None:
        fit_terminal()
        self.refresh_size()
        try:
            import termios
            import tty
            self._fd = sys.stdin.fileno()
            self._saved = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        except Exception:  # noqa: BLE001
            self._fd = None
        sys.stdout.write("\033[?1049h\033[?25l\033[2J")
        # заголовок окна терминала (icon + title)
        sys.stdout.write(f"\033]0;{APP_TITLE}\007")
        sys.stdout.flush()
        self._active = True
        try:
            signal.signal(signal.SIGWINCH, self._on_resize)
        except (ValueError, OSError, AttributeError):
            pass

    def exit(self) -> None:
        if not self._active:
            return
        self._active = False
        sys.stdout.write("\033[?25l\033[0m\033[?1049l")
        sys.stdout.flush()
        if self._fd is not None and self._saved is not None:
            try:
                import termios
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
            except Exception:  # noqa: BLE001
                pass
        try:
            signal.signal(signal.SIGWINCH, signal.SIG_DFL)
        except (ValueError, OSError, AttributeError):
            pass

    def _on_resize(self, signum, frame) -> None:  # noqa: ANN001
        self.refresh_size()

    # -- ввод --
    def read_key(self, timeout: float = 0.0) -> str:
        if self._fd is None:
            try:
                line = sys.stdin.readline()
            except KeyboardInterrupt:
                return Key.CTRL_C
            if not line:
                return Key.ESC
            return decode_key(line.rstrip("\n")[:1] or "\r")
        try:
            import select
            r, _, _ = select.select([sys.stdin], [], [], timeout)
            if not r:
                return ""
            ch = os.read(self._fd, 1)
        except (OSError, ValueError):
            return Key.ESC
        if not ch:
            return Key.ESC
        if ch == b"\x1b":
            # соберём escape-последовательность
            seq = "\x1b"
            for _ in range(8):
                try:
                    import select as _sel
                    if not _sel.select([sys.stdin], [], [], 0.02)[0]:
                        break
                    nxt = os.read(self._fd, 1)
                except (OSError, ValueError):
                    break
                if not nxt:
                    break
                seq += nxt.decode("utf-8", "ignore")
                if nxt.isalpha() or nxt in (b"~",):
                    break
            key = decode_key(seq)
            return key or Key.ESC
        # обычный символ (возможно, многобайтовый)
        text = ch.decode("utf-8", "ignore")
        while not text or _incomplete(text):
            try:
                more = os.read(self._fd, 1)
            except OSError:
                break
            if not more:
                break
            text += more.decode("utf-8", "ignore")
            if len(text) >= 4:
                break
        return decode_key(text)

    # -- вывод --
    def draw(self, lines: Sequence[str]) -> None:
        w = self.width
        out = ["\033[H"]
        for i, ln in enumerate(lines[:self.height - 1]):
            # обрезаем ПО ВИДИМОЙ ширине: строка шире терминала переносится
            # и оставляет мусор от прошлого кадра
            out.append("\033[K" + truncate(ln, w))
            if i < len(lines) - 1:
                out.append("\r\n")
        out.append("\033[J")
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    def clear(self) -> None:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()


def _incomplete(text: str) -> bool:
    """True, если UTF-8 последовательность не завершена."""
    try:
        text.encode("utf-8").decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True


# --------------------------------------------------------------------------- #
#  Размер окна терминала
# --------------------------------------------------------------------------- #

#: Целевой размер окна: как в .app-обёртке (launcher ставит тот же).
FIT_COLS, FIT_ROWS = 124, 35

_APPLESCRIPT_RESIZE = """
tell application "Terminal"
    repeat with w in windows
        repeat with tb in tabs of w
            if tty of tb is "%s" then
                set columns of w to %d
                set rows of w to %d
                return "ok"
            end if
        end repeat
    end repeat
    return "not found"
end tell
"""


def fit_terminal(cols: int = FIT_COLS, rows: int = FIT_ROWS) -> str:
    """Попытать Терминал дорасти до cols×rows. Возвращает способ или "".

    1. ESC-последовательность CSI 8;rows;cols t — умеют xterm-совместимые
       терминалы (iTerm2, kitty, alacritty…); Terminal.app её игнорирует.
    2. AppleScript по tty нашего stdout — точный способ для Terminal.app
       (первый раз macOS спросит разрешение на автоматизацию).
    Отключается полностью: MACC_FIT=0.
    """
    import subprocess
    if os.environ.get("MACC_FIT", "1") == "0":
        return ""
    try:
        if not (sys.stdout.isatty() and sys.stdin.isatty()):
            return ""
    except Exception:  # noqa: BLE001
        return ""
    how = ""
    try:
        sys.stdout.write(f"\033[8;{rows};{cols}t")
        sys.stdout.flush()
        how = "esc"
    except Exception:  # noqa: BLE001
        pass
    if os.uname().sysname == "Darwin" and \
            os.environ.get("TERM_PROGRAM") == "Apple_Terminal":
        try:
            tty_name = os.ttyname(sys.stdout.fileno())
        except (OSError, ValueError):
            tty_name = ""
        if tty_name:
            try:
                r = subprocess.run(
                    ["osascript", "-e", _APPLESCRIPT_RESIZE % (tty_name, cols, rows)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)
                if r.returncode == 0:
                    how = "applescript"
            except Exception:  # noqa: BLE001
                pass
    return how


# --------------------------------------------------------------------------- #
#  Экраны
# --------------------------------------------------------------------------- #

class Screen:
    """Базовый экран: title + render() + on_key()."""

    title = ""
    subtitle = ""
    hints: Tuple[Tuple[str, str], ...] = ()

    def __init__(self, app: "Any" = None):
        self.app = app
        self.message: str = ""
        self.message_kind: str = "info"

    def render(self, ctx: "RenderContext") -> List[str]:
        raise NotImplementedError

    def on_key(self, key: str, ctx: "RenderContext") -> Optional["Screen"]:
        if key in (Key.ESC, "q"):
            return ctx.app.back()
        return None

    def notify(self, text: str, kind: str = "info") -> None:
        self.message, self.message_kind = text, kind

    def on_enter(self, ctx: "RenderContext") -> None:
        """Вызывается при показе экрана (ленивые сканы)."""

    def on_leave(self, ctx: "RenderContext") -> None:
        pass


@dataclass
class RenderContext:
    app: Any
    painter: Painter
    width: int
    height: int

    @property
    def body_height(self) -> int:
        return max(3, self.height - 7)


class Dialog:
    """Модальное окно: сообщение + варианты ответа."""

    def __init__(self, title: str, lines: Sequence[str],
                 options: Sequence[Tuple[str, str]] = (("y", "Да"), ("n", "Нет")),
                 kind: str = "warn", default: int = 1):
        self.title = title
        self.lines = list(lines)
        self.options = list(options)
        self.kind = kind
        self.default = default
        self.cursor = default
        self.result: Optional[str] = None

    def render(self, painter: Painter, width: int, height: int) -> List[str]:
        t = painter.t
        w = min(width - 6, max(46, max(dwidth(x) for x in self.lines + [self.title]) + 6))
        inner: List[str] = []
        for ln in self.lines:
            # длинные строки переносим
            words = ln.split(" ")
            cur = ""
            for word in words:
                if dwidth(cur) + dwidth(word) + 1 > w - 4:
                    inner.append(cur)
                    cur = word
                else:
                    cur = (cur + " " + word).strip()
            inner.append(cur)
        inner.append("")
        opts = "   ".join(
            painter.color(f" {label} ", t.rev if i == self.cursor else t.dim)
            for i, (_, label) in enumerate(self.options))
        inner.append(pad(opts, w - 4, "center"))
        color = {"warn": t.yellow, "danger": t.red, "info": t.cyan}.get(self.kind, t.cyan)
        box = [painter.color(t.tl + t.h * (w - 2) + t.tr, color)]
        box.append(painter.box_row(painter.color(pad(self.title, w - 4, "center"),
                                                 t.bold), w))
        box.append(painter.color(t.lt + t.h * (w - 2) + t.rt, color))
        for ln in inner:
            box.append(painter.box_row(ln, w))
        box.append(painter.color(t.bl + t.h * (w - 2) + t.br, color))
        # центрируем по вертикали
        pad_top = max(0, (height - len(box)) // 2)
        out = [""] * pad_top
        for ln in box:
            out.append(pad(ln, width, "center"))
        return out

    def on_key(self, key: str) -> Optional[str]:
        if key in (Key.LEFT, Key.RIGHT, Key.TAB):
            self.cursor = (self.cursor + 1) % len(self.options)
            return None
        if key in (Key.ENTER, "y", "n", "Y", "N"):
            if key in ("y", "Y"):
                idx = 0
            elif key in ("n", "N"):
                idx = len(self.options) - 1
            else:
                idx = self.cursor
            return self.options[idx][0]
        if key == Key.ESC:
            return self.options[-1][0]
        for i, (code, _label) in enumerate(self.options):
            if key.lower() == code.lower():
                return code
        return None
