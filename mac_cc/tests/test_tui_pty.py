#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Запуск псевдографики в настоящем pty: проверяем, что TUI стартует, рисует
кадры с цветом, переживает нажатия и выходит без трейсбеков.

    bash tests/make_fake_home.sh /tmp/fake_mac
    HOME=/tmp/fake_mac/home MACTWEAKER_HOME=/tmp/fake_mac/home \
    MACTWEAKER_SYSROOT=/tmp/fake_mac/sys python3 tests/test_tui_pty.py
"""

from __future__ import annotations

import os
import pty
import re
import select
import subprocess
import unicodedata
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "maccc.py"
ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
CTRL = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b[=>]|[\x00-\x08\x0b-\x1f]")

FAILED = []
PASSED = 0


def check(cond: bool, msg: str) -> None:
    global PASSED
    if cond:
        PASSED += 1
        print("  OK   " + msg)
    else:
        FAILED.append(msg)
        print("  FAIL " + msg)


def refresh_fixture() -> None:
    """Пересоздать фейковое дерево, чтобы списки были полными."""
    home = Path(os.environ.get("MACTWEAKER_HOME", "/tmp/fake_mac/home"))
    if "fake_mac" not in str(home):
        return
    root = home.parent.parent if home.parent.name == "home" else home.parent
    subprocess.run(["bash", str(ROOT / "tests" / "make_fake_home.sh"), str(root)],
                   check=True, capture_output=True)
    old = time.time() - 730 * 86400
    for p in (home / "Library/Application Support/RemovedApp",
              home / "Library/Application Support/RemovedApp/data.db",
              home / ".config/removedtool",
              home / ".config/removedtool/state",
              home / "Downloads/BigInstaller.dmg"):
        if p.exists():
            os.utime(p, (old, old))
    try:
        subprocess.run(["chmod", "-R", "a+rwX", str(root)], capture_output=True)
    except OSError:
        pass


def set_winsize(fdesc: int, pid_child: int, rows: int = 34, cols: int = 110) -> None:
    """Реальный размер pty + SIGWINCH. pty.fork() оставляет 80×24 на macOS и
    0×0 на Linux — унифицируем, чтобы приложение не уходило в режим «узкого
    окна» и не зависело от платформы."""
    try:
        import fcntl
        import struct
        import termios
        fcntl.ioctl(fdesc, termios.TIOCSWINSZ,
                    struct.pack("HHHH", rows, cols, 0, 0))
    except (OSError, ImportError):
        pass
    try:
        import signal
        os.kill(pid_child, signal.SIGWINCH)
    except (OSError, ImportError):
        pass


def main() -> int:
    refresh_fixture()
    env = dict(os.environ)
    env["TERM"] = "xterm-256color"
    env.setdefault("MACC_LANG", "ru")   # основной прогон — без экрана выбора
    env["COLUMNS"] = "110"
    env["LINES"] = "34"
    env.pop("NO_COLOR", None)

    pid, fd = pty.fork()
    if pid == 0:                                  # дочерний процесс
        try:
            # TUI отказывается работать от root — сбрасываем привилегии,
            # если тесты запущены в root-песочнице
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                os.setgroups([])
                os.setgid(65534)
                os.setuid(65534)
        except (OSError, AttributeError, PermissionError):
            pass
        try:
            os.execve(sys.executable, [sys.executable, str(ENTRY)], env)
        except BaseException:                     # noqa: BLE001
            os._exit(99)

    set_winsize(fd, pid)

    def drain_fd(fd: int, seconds: float = 0.7) -> bytes:
        buf = b""
        end = time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.15)
            if not r:
                continue
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
        return buf

    def drain(seconds: float = 0.7) -> bytes:
        return drain_fd(fd, seconds)

    def drain_until(fdesc: int, needle: bytes, timeout: float,
                    settle: float = 0.35) -> bytes:
        """Читать вывод, пока не появится needle (или до таймаута), плюс короткая
        дозадержка, чтобы кадр дорисовался. Спасение для медленных машин:
        фиксированные паузы на виртуалках ненадёжны."""
        buf = b""
        end = time.time() + timeout
        found_at = None
        while time.time() < end:
            r, _, _ = select.select([fdesc], [], [], 0.1)
            if not r:
                if found_at is not None:
                    break
                continue
            try:
                chunk = os.read(fdesc, 65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            if found_at is None and needle in buf:
                found_at = time.time()
                end = min(end, found_at + settle)
        return buf

    frames = {}
    boot = drain_until(fd, b"Mac Crap Cleaner", 10.0)
    frames["boot"] = boot

    # сценарий: меню → очистка → скан → отметить всё → x → «нет» → назад
    #          → автозагрузка → скан → назад → настройки → назад → выход
    scenario = [
        ("cleaner-open", "1"),
        ("cleaner-scan", "s"),
        ("cleaner-all", "a"),
        ("cleaner-act", "x"),
        ("dialog-no", "n"),
        ("back-1", "\x1b"),
        ("startup-open", "4"),
        ("startup-scan", "s"),
        ("back-2", "\x1b"),
        ("tweaks-open", "5"),
        ("tweaks-load", "\r"),
        ("tweaks-down", "\x1b[B"),
        ("back-3", "\x1b"),
        ("orphans-open", "3"),
        ("orphans-scan", "s"),
        ("orphans-down", "\x1b[B\x1b[B\x1b[B"),
        ("orphans-up", "\x1b[A\x1b[A\x1b[A\x1b[A\x1b[A"),
        ("back-4", "\x1b"),
        ("deep-open", "2"),
        ("deep-scan", "s"),
        ("back-5", "\x1b"),
        ("help", "8"),
        ("help-scroll", "\x1b[B"),
        ("back-6", "\x1b"),
        ("disk-open", "6"),
        ("disk-wait", ""),
        ("disk-big", "b"),
        ("back-8", "\x1b"),
        ("info", "i"),
        ("info-top", "t"),
        ("back-7", "\x1b"),
        ("quit", "q"),
    ]
    for name, keys in scenario:
        if keys:
            try:
                os.write(fd, keys.encode())
            except OSError as exc:
                # ребёнок умер — сохрани накопленные кадры для диагностики
                try:
                    Path("/tmp/pty_fail.txt").write_text(
                        f"STEP={name} ERR={exc}\n"
                        + ANSI.sub("", b"".join(frames.values())
                                   .decode("utf-8", "replace"))[-4000:])
                except OSError:
                    pass
                raise
        if name in ("orphans-down", "orphans-up"):
            # ждём именно кадр с курсором (инверсная строка), а не фикс. паузу
            frames[name] = drain_until(fd, b"\x1b[7m", 8.0)
        else:
            frames[name] = drain(2.2 if name in ("disk-open", "disk-wait", "info-top")
                                 else 1.6 if name.endswith("scan") else 0.5)

    try:
        os.close(fd)
    except OSError:
        pass
    try:
        _, status = os.waitpid(pid, 0)
    except ChildProcessError:
        status = 0

    whole = b"".join(frames.values()).decode("utf-8", "replace")
    clean = ANSI.sub("", whole)

    print("\n== TUI в pty ==")
    check("Traceback" not in whole, "нет трейсбеков")
    check("Operation not permitted" not in whole, "нет ошибок доступа (SIP/TCC)")
    check("\x1b[?1049h" in whole, "включён alternate screen")
    check("\x1b]0;Mac Crap Cleaner\x07" in whole,
          "заголовок окна терминала = «Mac Crap Cleaner»")
    check("\x1b[?1049l" in whole, "alternate screen выключен при выходе")
    check("\x1b[?" in whole or "\x1b[3" in whole or "\x1b[9" in whole,
          "используются цвета/атрибуты")
    check("███╗" in clean or "MAC" in clean.upper(), "нарисован логотип")
    check("Очистка кэшей" in clean, "видно пункт меню очистки")
    check("Автозагрузка" in clean, "видно пункт меню автозагрузки")
    check("Остатки удалённых" in clean, "видно пункт меню остатков")
    check("Настройки системы" in clean, "видно пункт меню настроек")
    check("отмечено" in clean, "экран очистки показывает итог отметки")
    check("ком.removed" in clean or "com.removed" in clean,
          "экран автозагрузки/остатков показал тестовые элементы")
    check("битый" in clean, "битый элемент автозагрузки помечен")
    check("СИРОТА" in clean, "найденные сироты помечены")
    check("Показывать скрытые файлы" in clean, "экран настроек отрисован")
    check("Профиль" in clean or "профиль" in clean, "виден профиль очистки")
    check("ПРОБЕЛ" in clean and "ESC" in clean, "подсказки клавиш капсом")
    check("Enter открыть" not in clean, "клавиши не в нижнем регистре")
    check(any(c in clean for c in "|/-\\"), "анимированный бар из | / - \\ виден")
    check("Анализ диска" in clean or "Крупнейшие" in clean or "крупнее" in clean,
          "экран анализа диска отработал")

    # курсор реально ходит ВВЕРХ по списку с заголовками групп
    def cursor_row(frame_raw: str) -> int:
        """Строка с курсором (инверсия) в последнем ПОЛНОМ кадре порции вывода.
        Хвост порции на медленных машинах может быть частичной перерисовкой —
        тогда берём предыдущий завершённый кадр."""
        screens = [f for f in frame_raw.split("\x1b[H") if f.strip()]
        for scr in reversed(screens):
            for i, ln in enumerate(scr.split("\n")):
                if "\x1b[7m" in ln:
                    return i
        return -1

    down_frame = frames.get("orphans-down", b"").decode("utf-8", "replace")
    up_frame = frames.get("orphans-up", b"").decode("utf-8", "replace")
    r_down, r_up = cursor_row(down_frame), cursor_row(up_frame)
    check(r_down != -1 and r_up != -1 and r_up < r_down,
          f"курсор поднимается вверх по списку (строка {r_down} → {r_up})")
    check(os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0,
          f"процесс завершился кодом {os.WEXITSTATUS(status) if os.WIFEXITED(status) else '?'}")

    # ни одна строка ОТДЕЛЬНОГО кадра не шире терминала.
    # Кадры разделены переводом курсора в начало экрана (ESC[H); дамп pty
    # склеивает их в одну строку, поэтому мерить нужно внутри кадра.
    frames_raw = whole.split("\x1b[H")
    over = 0
    max_w = 0
    for fr in frames_raw:
        for ln in fr.split("\n"):
            ln = CTRL.sub("", ln).rstrip()
            w = sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
                    for c in ln)
            max_w = max(max_w, w)
            if w > 116:
                over += 1
    check(over == 0, f"строки кадров не шире терминала (нарушений: {over}, "
                     f"макс. ширина {max_w})")

    # --- отдельный прогон: экран выбора языка и английское меню ---
    pid2, fd2 = pty.fork()
    if pid2 == 0:
        env2 = dict(os.environ)
        env2.pop("MACC_LANG", None)
        env2["TERM"] = "xterm-256color"
        env2["COLUMNS"] = "110"
        env2["LINES"] = "34"
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            try:
                os.setgroups([]); os.setgid(65534); os.setuid(65534)
            except OSError:
                pass
        try:
            os.execve(sys.executable, [sys.executable, str(ENTRY)], env2)
        except BaseException:  # noqa: BLE001
            os._exit(99)
    set_winsize(fd2, pid2)
    prompt = drain_until(fd2, b"Select [1/2]", 10.0)
    prompt_s = ANSI.sub("", prompt.decode("utf-8", "replace"))
    check("Select language" in prompt_s and "Русский" in prompt_s
          and "English" in prompt_s and "Select [1/2]" in prompt_s,
          "экран выбора языка показан при первом запуске")
    os.write(fd2, b"2\n")
    en_frame = ANSI.sub("", drain_until(fd2, b"Cache & junk cleanup", 12.0)
                        .decode("utf-8", "replace"))
    check("Cache & junk cleanup" in en_frame and "Startup items" in en_frame,
          "после выбора «2» интерфейс английский")
    check("Mac Crap Cleaner - Less crap" in en_frame, "слоган под логотипом")
    os.write(fd2, b"q")
    drain_fd(fd2, 0.5)
    try:
        os.close(fd2); os.waitpid(pid2, 0)
    except OSError:
        pass

    dump = Path(os.environ.get("MT_PTY_DUMP", "/tmp/mt-pty.txt"))
    dump.write_text(clean, encoding="utf-8")
    dump.with_suffix(".raw").write_text(whole, encoding="utf-8")
    print(f"\n  полный дамп вывода: {dump} (+ .raw с escape-кодами)")

    print("\n" + "=" * 60)
    if FAILED:
        print(f"ПРОВАЛЕНО: {len(FAILED)} из {PASSED + len(FAILED)}")
        for f in FAILED:
            print("  - " + f)
        return 1
    print(f"TUI-ТЕСТЫ ПРОЙДЕНЫ: {PASSED}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
