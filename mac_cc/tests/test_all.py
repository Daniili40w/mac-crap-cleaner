#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты Mac Crap Cleaner (MacCC). Работают на фейковом «маковском» дереве, которое создаёт
tests/make_fake_home.sh, поэтому запускаются и на Linux (в CI/песочнице).

    bash tests/make_fake_home.sh /tmp/fake_mac
    MACTWEAKER_HOME=/tmp/fake_mac/home MACTWEAKER_SYSROOT=/tmp/fake_mac/sys \
        python3 tests/test_all.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from mactweaker import app as appmod          # noqa: E402
from mactweaker.app import WAIT_MESSAGES      # noqa: E402
from mactweaker import junk, leftovers, startup, system, tweaks  # noqa: E402
from mactweaker.safety import (Deleter, Journal, Paths, dir_size, human,  # noqa: E402
                               is_safe, is_traversable, safe_exists)
from mactweaker.ui import (Dialog, Key, ListView, Painter, RenderContext,  # noqa: E402
                           Row, Theme, decode_key, dwidth, pad, truncate)

FAILED: list = []
PASSED = 0


def check(cond: bool, msg: str) -> None:
    global PASSED
    if cond:
        PASSED += 1
        print("  OK   " + msg)
    else:
        FAILED.append(msg)
        print("  FAIL " + msg)


def section(name: str) -> None:
    print("\n== " + name + " " + "=" * max(0, 60 - len(name)))


# --------------------------------------------------------------------------- #

HOME = Path(os.environ.get("MACTWEAKER_HOME", "/tmp/fake_mac/home"))
SYSROOT = Path(os.environ.get("MACTWEAKER_SYSROOT", "/tmp/fake_mac/sys"))

# стенд пересоздаётся сам, если указан фейковый корень (не трогаем реальное окружение)
if "fake_mac" in str(HOME):
    root = HOME.parent.parent if HOME.parent.name == "home" else HOME.parent
    setup = HERE / "make_fake_home.sh"
    subprocess.run(["bash", str(setup), str(root)], check=True,
                   capture_output=True)
    _old = time.time() - 730 * 86400
    for _p in (HOME / "Library/Application Support/RemovedApp",
               HOME / "Library/Application Support/RemovedApp/data.db",
               HOME / ".config/removedtool",
               HOME / ".config/removedtool/state",
               HOME / "Downloads/BigInstaller.dmg"):
        if _p.exists():
            os.utime(_p, (_old, _old))
if not HOME.exists():
    print("Сначала создайте стенд:  bash tests/make_fake_home.sh /tmp/fake_mac")
    sys.exit(2)

P = Paths.detect(home=HOME, sysroot=SYSROOT)


# --------------------------------------------------------------------------- #
section("safety: предохранители")
check(not is_safe(HOME, P), "домашний каталог защищён")
check(not is_safe(HOME / "Documents", P), "~/Documents защищён")
check(not is_safe(HOME / "Library" / "Containers", P), "Containers защищены")
check(not is_safe(HOME / "Library" / "Keychains", P), "Keychains защищены")
check(not is_safe(HOME / ".ssh", P), "~/.ssh защищён")
check(not is_safe(SYSROOT / "System" / "Library", P), "/System защищён")
check(not is_safe(Path("/"), P), "/ защищён")
check(not is_safe(HOME / "Library", P), "~/Library защищён")
check(not is_safe(HOME / ".Trash", P), "~/.Trash как каталог защищён")
check(is_safe(HOME / "Library" / "Caches" / "pip", P), "~/Library/Caches/pip можно")
check(is_safe(HOME / "Library" / "Developer" / "Xcode" / "DerivedData" / "P", P),
      "DerivedData можно")
check(not is_safe(HOME / "Library" / "Application Support" / "ImportantStuff", P),
      "Application Support/ImportantStuff защищён")
check(is_safe(HOME / "Library" / "Application Support" / "Code" / "CachedData" / "x", P),
      "Application Support/Code/CachedData можно")
check(not is_traversable(HOME / "Documents", P), "в Documents сканер не заходит")
check(not is_traversable(HOME / ".Trash", P), "в .Trash сканер не заходит")
check(is_traversable(HOME / "Projects", P), "в Projects сканер заходит")
check(not is_safe(Path("/Library/Caches/x.datavault"), P), "DataVault защищён")
check(not is_safe(Path("/Library/Caches/com.apple.a.classicdatavault"), P),
      "classicdatavault защищён")
check(human(1536) == "1.5 КБ", "human(): " + human(1536))
check(human(0) == "0 Б", "human(0)")
check(dir_size(HOME / "Library" / "Application Support" / "RemovedApp")[0] > 0,
      "dir_size считает размер")
check(dir_size(HOME / "Library" / "Caches" / "com.apple.ams.classicdatavault") == (0, 0),
      "dir_size не падает на недоступном")

# --------------------------------------------------------------------------- #
section("safety: удаление в Корзину и журнал")
victim = HOME / "Library" / "Caches" / "com.removed.app1"
check(safe_exists(victim), "цель существует до удаления")
journal = Journal(P)
deleter = Deleter(P, mode="trash", journal=journal)
before = dir_size(victim)[0]
freed, failed = deleter.delete([victim])
check(not safe_exists(victim), "цель удалена")
check(freed == before, f"освобождено {human(freed)} (ожидали {human(before)})")
check(not failed, f"нет ошибок удаления (failed={failed})")
check(safe_exists(P.trash / victim.name) or any(
    (P.trash / x).exists() for x in os.listdir(P.trash)), "файл попал в Корзину")
check(safe_exists(P.state_dir), "создан каталог состояния ~/.mac_tweaker")
restored, problems = journal.undo_last_session()
check(restored >= 1 and safe_exists(victim), f"откат из Корзины: {restored} объектов")

# dry-режим ничего не трогает
dry = Deleter(P, mode="dry")
f2, _ = dry.delete([victim])
check(f2 == 0 and safe_exists(victim), "режим dry ничего не удаляет")

# --------------------------------------------------------------------------- #
section("junk: сканирование кэшей")
targets = junk.scan_junk(P, profile="dev", with_commands=False)
names = {t.name for t in targets}
check("Кэши пользователя (~/Library/Caches)" in names, "найден пользовательский кэш")
check("Xcode DerivedData" in names, "найден DerivedData")
root_targets = [t for t in targets if t.root_required]
check(bool(root_targets), "есть цели, требующие sudo")
check(all(t.root_required for t in root_targets),
      "root_required — булево, а не текст примечания")
check(not any(isinstance(t.root_required, str) for t in targets),
      "тип root_required корректен у всех целей")
sizes = {t.name: t.size for t in targets}
check(sizes.get("Xcode DerivedData", 0) >= 33 * 1024 ** 2,
      f"DerivedData ≈33 МБ ({human(sizes.get('Xcode DerivedData', 0))})")
basic = junk.scan_junk(P, profile="basic", with_commands=False)
check(not any("Xcode" in t.name for t in basic), "в профиле basic нет Xcode")
agg = junk.scan_junk(P, profile="aggressive", with_commands=False)
check(len(agg) >= len(basic), "aggressive ⊇ basic")

section("junk: очистка выбранных целей")
to_clean = [t for t in targets if t.name == "Xcode DerivedData"]
check(bool(to_clean) and not to_clean[0].root_required,
      "DerivedData не требует sudo")
freed, failed = Deleter(P, mode="trash", journal=Journal(P)).delete(
    [p for t in to_clean for p in t.paths])
check(freed > 30 * 1024 ** 2, f"DerivedData удалён: {human(freed)}")
check(not failed, "без ошибок")
check(not (HOME / "Library" / "Developer" / "Xcode" / "DerivedData" / "Proj-abc").exists(),
      "каталог исчез")

section("junk: глубокий скан")
items = junk.deep_scan(P, max_depth=7, risk_max=junk.RISK_ADVICE)
rules = {i.rule for i in items}
paths_found = {str(i.path) for i in items}
check("Finder .DS_Store" in rules, "найдены .DS_Store")
check(str(HOME / "Desktop" / ".DS_Store") in paths_found,
      ".DS_Store найден даже на защищённом Desktop")
check("__pycache__ / *.pyc" in rules, "найден __pycache__")
check(not any("node_modules" in str(i.path) for i in items),
      "node_modules не трогается")
check(not any("/Documents/" in str(i.path) for i in items
               if i.path.name != ".DS_Store"),
      "в Documents ничего не найдено, кроме .DS_Store")
check(not any(str(i.path).endswith("/.cache") for i in items),
      "~/.cache целиком не помечен как мусор")
check(any(i.path.name == "run.log" for i in items), "найден лог проекта")
check(all(i.risk <= junk.RISK_ADVICE for i in items), "риски в допустимых пределах")
safe_items = [i for i in items if i.risk == junk.RISK_SAFE]
check(all(i.selected for i in safe_items), "безопасное отмечено по умолчанию")
check(all(not i.selected for i in items if i.risk != junk.RISK_SAFE),
      "спорное НЕ отмечено по умолчанию")

section("junk: старые установщики в ~/Downloads")
dl = junk.scan_downloads(P, time.time() - 30 * 86400)
check(any(x.name == "BigInstaller.dmg" for x in dl), "старый .dmg найден")
check(not any(x.name == "notes.txt" for x in dl), "обычные файлы не трогаем")

# --------------------------------------------------------------------------- #
section("leftovers: реестр приложений")
reg = leftovers.AppRegistry.build(P, use_spotlight=False, include_processes=False)
ids = {a.bundle_id.lower() for a in reg.apps}
check("com.apple.safari" in ids, "найден Safari")
check("org.telegram.desktop" in ids, "найден Telegram")
check("com.microsoft.vscode" in ids, "найден VS Code")
check("com.example.mytool" in ids, "найден MyTool из ~/Applications")
check(len(reg.apps) == 5, f"всего приложений: {len(reg.apps)} (ожидали 5)")
check("google" not in reg.vendors, "вендора google нет (Chrome не установлен)")

section("leftovers: классификация")
cases = {
    "com.removed.app1": leftovers.VERDICT_ORPHAN,
    "com.example.mytool": leftovers.VERDICT_ALIVE,
    "com.microsoft.VSCode": leftovers.VERDICT_ALIVE,
    "com.google.Chrome": leftovers.VERDICT_ORPHAN,
    "com.apple.Safari": leftovers.VERDICT_SYSTEM,
    "Telegram": leftovers.VERDICT_ALIVE,
    "pip": leftovers.VERDICT_TOOL,
    "ImportantStuff": leftovers.VERDICT_UNKNOWN,
}
for name, expected in cases.items():
    kind = "bundleid" if "." in name else "name"
    got = leftovers.classify(name, name, kind, reg, P)[0]
    check(got == expected, f"classify({name}) = {got} (ожидали {expected})")

section("leftovers: скан сирот")
orphans = leftovers.scan_leftovers(P, registry=reg)
orph_paths = {str(o.path) for o in orphans}
check(any("com.removed.app1" in p for p in orph_paths),
      "найдены остатки com.removed.app1")
check(any(p.endswith("Caches/com.removed.app1") for p in orph_paths),
      "  …в Caches")
check(any("Preferences/com.removed.app1.plist" in p for p in orph_paths),
      "  …в Preferences")
check(any("HTTPStorages/com.removed.app1" in p for p in orph_paths),
      "  …в HTTPStorages")
check(any("com.thirdparty.helper" in p for p in orph_paths),
      "найден системный кэш чужой программы")
check(not any("Telegram" in p for p in orph_paths), "Telegram (установлен) не помечен")
check(not any("ImportantStuff" in p for p in orph_paths),
      "неизвестный каталог НЕ помечен как сирота")
check(not any("com.example.mytool" in p for p in orph_paths),
      "данные установленного MyTool не помечены")
check(not any("com.apple" in p for p in orph_paths), "компоненты Apple не помечены")
check(all(o.selected for o in orphans), "сироты отмечены по умолчанию")
check(sum(o.size for o in orphans) > 15 * 1024 ** 2,
      f"суммарный объём сирот: {human(sum(o.size for o in orphans))}")

section("leftovers: устаревшие данные (неизвестный владелец)")
aged = leftovers.scan_leftovers(P, registry=reg, include_unknown=True, stale_days=365)
stale = [a for a in aged if a.verdict == leftovers.VERDICT_STALE]
check(bool(stale), "найдены устаревшие каталоги")
check(any("removedtool" in str(s.path) for s in stale),
      "~/.config/removedtool помечен как устаревший")
check(all(not s.selected for s in stale), "устаревшие НЕ отмечены автоматически")

section("leftovers: удаление сирот")
sel = [o for o in orphans if "com.removed.app1" in str(o.path)]
freed, failed = Deleter(P, mode="trash", journal=Journal(P)).delete([o.path for o in sel])
check(freed > 0 and not failed, f"сироты удалены в Корзину: {human(freed)}")
check(not (HOME / "Library" / "Caches" / "com.removed.app1").exists(),
      "кэш сироты исчез")
check((HOME / "Library" / "Application Support" / "ImportantStuff" / "license.key").exists(),
      "важные данные целы")
check((HOME / "Documents" / "important.txt").exists(), "документы целы")

# --------------------------------------------------------------------------- #
section("startup: сбор элементов автозагрузки")
items = startup.collect(P, include_system=True, include_login_items=False)
labels = {i.label for i in items}
check("com.removed.app1.helper" in labels, "найден агент удалённой программы")
check("com.example.mytool.updater" in labels, "найден агент живой программы")
check("com.removed.daemon" in labels, "найден демон")
check("com.apple.important" in labels, "найден элемент Apple")
by_label = {i.label: i for i in items}
helper = by_label["com.removed.app1.helper"]
check(helper.missing_binary, "битый агент помечен (бинарник отсутствует)")
check(helper.state == startup.STATE_BROKEN, f"состояние: {helper.state}")
check(helper.run_at_load, "RunAtLoad прочитан из plist")
check(not helper.critical, "сторонний агент не помечен критическим")
check(by_label["com.apple.important"].critical, "элемент Apple помечен критическим")
check(not by_label["com.apple.important"].disable_allowed,
      "и его нельзя отключить")
dead = startup.dead_weight(items)
check(any(i.label == "com.removed.app1.helper" for i in dead),
      "мёртвый груз определён")
check(not any(i.label.startswith("com.apple") for i in dead),
      "Apple-элементы не в списке мёртвого груза")
check(any("обновлятор" in n for n in by_label["com.example.mytool.updater"].note_texts()),
      "updater помечен как обновлятор")

section("startup: отключение и восстановление")
target = by_label["com.removed.app1.helper"]
res = startup.disable([target], P, use_sudo=False)
ok, msg = res[0][1], res[0][2]
check(ok, f"отключение выполнено: {msg}")
check(not safe_exists(target.path), "plist убран из LaunchAgents")
check(safe_exists(startup.disabled_dir(P) / target.path.name),
      "резервная копия в ~/.mac_tweaker/disabled/")
again = startup.disable([target], P)
check(not again[0][1], "повторное отключение сообщает об ошибке, а не падает")
orig_path = target.path
res = startup.enable(startup.disabled_items(P), P, use_sudo=False)
check(res[0][1], f"включение обратно: {res[0][2]}")
check(safe_exists(orig_path), f"plist вернулся на место: {orig_path.name}")
check(not list(startup.disabled_dir(P).glob("*.plist")),
      "хранилище отключённых пусто после восстановления")
items2 = startup.collect(P, include_system=False, include_login_items=False)
check(any(i.label == "com.removed.app1.helper" for i in items2),
      "элемент снова виден в списке автозагрузки")
blocked = startup.disable([by_label["com.apple.important"]], P)
check(not blocked[0][1], "системный элемент отключить нельзя")

# --------------------------------------------------------------------------- #
section("tweaks: описания и состояние")
all_tw = tweaks.all_tweaks()
check(len(all_tw) >= 25, f"твиков: {len(all_tw)}")
ids = [t.tid for t in all_tw]
check(len(ids) == len(set(ids)), "идентификаторы твиков уникальны")
check(all(t.domain and t.key for t in all_tw), "у всех заданы домен и ключ")
check(all(t.description for t in all_tw), "у всех есть описание")
check(any(t.risky for t in all_tw), "есть помеченные как рискованные")
check(len(tweaks.sections(all_tw)) >= 5, f"разделов: {len(tweaks.sections(all_tw))}")
tweaks.refresh(all_tw[:3])     # на Linux `defaults` нет — не должно падать
check(True, "refresh() не падает без команды defaults")
ok, msg = tweaks.export_defaults(P)
check(isinstance(ok, bool) and msg, f"export_defaults вернул ({ok}, {msg[:40]})")

# --------------------------------------------------------------------------- #
section("ui: движок псевдографики")
th = Theme(enabled=False, ascii_only=True)
pa = Painter(th)
check(dwidth("привет") == 6, f"ширина кириллицы: {dwidth('привет')}")
check(dwidth("\033[31mred\033[0m") == 3, "ANSI-коды не считаются")
check(dwidth("漢字") == 4, "иероглифы считаются как 2")
check(dwidth(truncate("длинная строка", 6)) == 6,
      f"truncate держит ширину: {dwidth(truncate('длинная строка', 6))}")
check(truncate("длинная строка", 6).startswith("длинн"), "truncate режет по символам")
check(dwidth(truncate("\033[31mкрасная строка\033[0m", 8)) <= 8,
      "truncate с ANSI не выходит за ширину")
check(len(pad("abc", 8)) == 8, "pad дополняет до ширины")
check(pad("abc", 8, "right") == "     abc", "pad справа")
bar = pa.bar(0.5, 10)
check(len(bar) == 10, f"bar длина: {len(bar)}")
check(decode_key("\x1b[A") == Key.UP, "стрелка вверх")
check(decode_key("\x1b[B") == Key.DOWN, "стрелка вниз")
check(decode_key("\r") == Key.ENTER, "Enter")
check(decode_key("\x1b") == Key.ESC, "Esc")
check(decode_key(" ") == Key.SPACE, "пробел")
check(decode_key("\x03") == Key.CTRL_C, "Ctrl+C")
check(decode_key("q") == "q", "обычный символ")
check(decode_key("\x1b[<64;10;10M") == "mouse", "прокрутка мыши")
check(decode_key("\x1b[99Z") == "", "неизвестная ESC-последовательность игнорируется")

# навигация сквозь заголовки групп в обе стороны
gl = ListView([
    Row(cells=["── группа A"], selectable=False),
    Row(cells=["a1"], meta="a1"),
    Row(cells=["a2"], meta="a2"),
    Row(cells=["── группа B"], selectable=False),
    Row(cells=["b1"], meta="b1"),
    Row(cells=["b2"], meta="b2"),
], multi=True)
check(gl.rows[gl.cursor].selectable,
      "стартовый курсор стоит на выбираемой строке, не на заголовке")
gl.end()
check(gl.current.meta == "b2", "End → последний выбираемый элемент")
gl.move(-1)
check(gl.current.meta == "b1", "вверх через элемент группы")
gl.move(-1)
check(gl.current.meta == "a2", "вверх ПЕРЕСКАКИВАЕТ заголовок группы")
gl.move(-1)
check(gl.current.meta == "a1", "вверх до первого элемента")
gl.move(-1)
check(gl.current.meta == "a1", "выше первого элемента курсор не уходит")
gl.move(-5)
check(gl.current.meta == "a1", "множественный шаг вверх не застревает")
gl.move(7)
check(gl.current.meta == "b2", "множественный шаг вниз доходит до конца")
gl.home()
check(gl.current.meta == "a1", "Home → первый выбираемый элемент")
gl.cursor = 3                      # принудительно на заголовок
gl.move(-1)
check(gl.current.meta == "a2", "с заголовка вверх уходим на элемент выше")
gl.cursor = 3
gl.move(1)
check(gl.current.meta == "b1", "с заголовка вниз уходим на элемент ниже")
gl.toggle()
check(gl.rows[4].checked and gl.current.meta == "b2",
      "пробел отмечает и перескакивает заголовок вперёд")

lv = ListView([Row(cells=[f"item {i}"], meta=i) for i in range(10)], multi=True)
lv.move(3)
check(lv.cursor == 3, "курсор перемещается")
lv.toggle()
check(lv.rows[3].checked, "пробел отмечает элемент")
lv.toggle_all()
check(all(r.checked for r in lv.rows), "«отметить всё»")
lv.toggle_all()
check(not any(r.checked for r in lv.rows), "повторное «отметить всё» снимает отметки")
lines = lv.render(pa, 60, 5)
check(len(lines) == 5, f"рендер списка: {len(lines)} строк")
check(all(dwidth(x) <= 60 for x in lines), "строки не шире экрана")
lv.end()
check(lv.cursor == 9, "End → последний элемент")
lv.ensure_visible(5)
check(lv.offset > 0, "прокрутка следует за курсором")

dlg = Dialog("Тест", ["строка 1", "строка 2"], options=(("y", "Да"), ("n", "Нет")))
dlines = dlg.render(pa, 80, 24)
check(any("Тест" in x for x in dlines), "диалог рисует заголовок")
check(dlg.on_key(Key.LEFT) is None and dlg.cursor == 0, "стрелка переключает ответ")
check(dlg.on_key(Key.ENTER) == "y", "Enter подтверждает выбранный ответ")
check(dlg.on_key("n") == "n", "горячая клавиша ответа")
check(dlg.on_key(Key.ESC) == "n", "Esc = отказ")

section("ui: анимация и рамки")
th2 = Theme(enabled=False, ascii_only=False)
pa2 = Painter(th2)
for frac in (0.0, 0.37, 1.0):
    b = pa2.anim_bar(frac, 24, 1)
    check(dwidth(b) == 24, f"anim_bar({frac}) держит ширину 24")
    check(all(c in "|/-\\·" for c in b), "anim_bar состоит из | / - \\ и точек")
b1, b2 = pa2.anim_bar(0.5, 24, 0), pa2.anim_bar(0.5, 24, 2)
check(b1 != b2, "anim_bar меняется со временем (анимация живая)")
bi = pa2.anim_bar(None, 24, 7)
check(dwidth(bi) == 24 and bi.count("·") < 24, "индетерминированный бар бежит")
hl = pa2.hline(140, th2.tl, th2.tr, " уровень: безопасное + спорное ")
check(dwidth(hl) == 140, f"hline с заголовком ровно 140 (было {dwidth(hl)})")
check(dwidth(pa2.hline(80, th2.tl, th2.tr)) == 80, "hline без заголовка ровно 80")
check(dwidth(pa2.sep(120)) == 120, "sep ровно 120")
check(dwidth(pa2.box_top(90, " Тест ")) == 90, "box_top ровно 90")

class FakeTerm:
    """Терминал-заглушка: считаем нарисованные кадры, ничего не пишем."""

    width, height = 100, 32
    drawn = 0

    def draw(self, lines):
        FakeTerm.drawn += 1

    def refresh_size(self):
        pass


section("app: фоновые задачи не блокируют интерфейс")
app2 = appmod.App(Theme(enabled=False), P)
app2.term = FakeTerm()
app2.stack = [appmod.MainMenu(app2)]
before = FakeTerm.drawn
box_calls = []


def slow_fn(tick):
    for i in range(20):
        time.sleep(0.03)
        box_calls.append(i)
        tick(i, 20, f"шаг {i}")


t0 = time.time()
app2.task("долгая операция", slow_fn)
dt = time.time() - t0
check(len(box_calls) == 20, "fn отработала полностью")
check(FakeTerm.drawn > before, f"кадры рисовались во время задачи ({FakeTerm.drawn - before})")
check(app2.progress is None, "progress сброшен после задачи")


# сменные надписи каждые 10 секунд: задача дольше 10 с → увидим ротацию
captured: List[str] = []


class CapTerm(FakeTerm):
    def draw(self, lines):
        FakeTerm.drawn += 1
        captured.append("\n".join(lines))


app3 = appmod.App(Theme(enabled=False), P)
app3.term = CapTerm()
app3.stack = [appmod.MainMenu(app3)]


def long_fn(tick):
    for i in range(115):
        time.sleep(0.1)
        tick(0, 0, "долгий поиск")


app3.task("очень долгая операция", long_fn)
blob = "\n".join(captured)
check(WAIT_MESSAGES[0] in blob,
      "надпись «подождите пару минут, программа не зависла» появляется")
check(WAIT_MESSAGES[1] in blob, "через 10 с надпись сменилась на «просматриваю файлы»")
check(any("долгий поиск" in c for c in captured), "виден текст задачи")
check(any(re.search(r"\[[|/\\-]{4,}", c) for c in captured),
      "бар анимируется символами | / - \\")


def boom_fn(tick):
    raise RuntimeError("бум")


try:
    app2.task("ошибка", boom_fn)
    check(False, "исключение из fn должно пробрасываться")
except RuntimeError:
    check(True, "исключение из fn пробрасывается вызывающему")

check(WAIT_MESSAGES[0] == "подождите пару минут, программа не зависла",
      "надпись 1: «подождите пару минут, программа не зависла»")
check(WAIT_MESSAGES[1] == "просматриваю файлы", "надпись 2: «просматриваю файлы»")
check(WAIT_MESSAGES[2] == "прохожусь по пыльным местам",
      "надпись 3: «прохожусь по пыльным местам»")
check(WAIT_MESSAGES[3] == "я почти закончил искать",
      "надпись 4: «я почти закончил искать»")

# --------------------------------------------------------------------------- #
section("app: рендер экранов (без терминала)")
theme = Theme(enabled=False, ascii_only=True)
application = appmod.App(theme, P)
application.term = FakeTerm()
application.sysinfo = system.SystemInfo(
    hostname="test", user="test", os_name="macOS", os_version="14.0",
    model="MacBookAir", cpu="M2", cores=8, ram_total=16 * 1024 ** 3,
    ram_free=8 * 1024 ** 3, uptime=3600, python="3.9.6", is_darwin=True,
    disks=[system.DiskInfo(path="/", total=500 * 1024 ** 3,
                           used=300 * 1024 ** 3, free=200 * 1024 ** 3)])
ctx = RenderContext(app=application, painter=application.p, width=100, height=32)


def render_ok(screen: appmod.Screen, label: str, keys: tuple = ()) -> None:
    try:
        screen.on_enter(ctx)
        lines = application.frame(screen, ctx)
        assert isinstance(lines, list) and lines, "пустой кадр"
        assert all(isinstance(x, str) for x in lines), "не-строка в кадре"
        assert len(lines) <= ctx.height, f"кадр выше экрана: {len(lines)}"
        wide = [x for x in lines if dwidth(x) > ctx.width]
        assert not wide, f"строки шире экрана: {[w[:60] for w in wide][:1]}"
        hint = lines[-1]
        # клавиши (первый токен пары) должны быть КАПСОМ: никаких "Enter"/"Esc"
        assert "ESC" in hint and "Enter" not in hint and "Esc " not in hint, \
            f"клавиши в подсказках не капсом: {hint[:70]}"
        for k in keys:
            screen.on_key(k, ctx)
        application.frame(screen, ctx)
        check(True, f"{label}: рендер и клавиши без ошибок")
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        check(False, f"{label}: {type(exc).__name__}: {exc}")


render_ok(appmod.MainMenu(application), "MainMenu", keys=(Key.DOWN, Key.DOWN, Key.UP, "2"))
render_ok(appmod.InfoScreen(application), "InfoScreen", keys=("r",))
hs = appmod.HelpScreen(application)
render_ok(hs, "HelpScreen", keys=(Key.DOWN, Key.PAGEDOWN, Key.PAGEUP))
help_lines = hs.render(ctx)
check(any("ПРОБЕЛ" in x for x in help_lines), "в справке клавиши капсом")
check(any("ENTER" in x for x in help_lines), "в справке ENTER капсом")
render_ok(appmod.CleanerScreen(application), "CleanerScreen (до скана)",
          keys=("p", "i", Key.TAB))
render_ok(appmod.DeepScreen(application), "DeepScreen (до скана)", keys=("i", "o"))
render_ok(appmod.OrphansScreen(application), "OrphansScreen (до скана)", keys=("i",))
render_ok(appmod.StartupScreen(application), "StartupScreen (до скана)", keys=("f",))
render_ok(appmod.TweaksScreen(application), "TweaksScreen (до загрузки)", keys=())
render_ok(appmod.DiskScreen(application), "DiskScreen", keys=(Key.DOWN, "b"))
render_ok(appmod.LogScreen(application), "LogScreen", keys=(Key.DOWN,))

section("app: скан через экран (симуляция нажатий)")
cs = appmod.CleanerScreen(application)
cs.profile = "basic"
cs.do_scan()
lines = application.frame(cs, ctx)
check(any("Кэши пользователя" in x for x in lines), "CleanerScreen показал результаты")
check(len(cs.selected_targets()) == len(cs.targets),
      "после скана все цели отмечены по умолчанию")
check(any("отмечено" in x for x in application.frame(cs, ctx)),
      "внизу видна строка итога")
cs.on_key("a", ctx)
check(len(cs.selected_targets()) == 0, "первое «a» снимает все отметки")
cs.on_key("a", ctx)
check(len(cs.selected_targets()) == len(cs.targets), "второе «a» отмечает всё снова")
cs.list.cursor = next(i for i, r in enumerate(cs.list.rows) if r.selectable)
cs.on_key(Key.SPACE, ctx)
cs._sync_selection()
check(any(not t.selected for t in cs.targets), "пробел снимает отметку с элемента")
check(all(r.selectable or not r.checked for r in cs.list.rows),
      "заголовки разделов не отмечаются")
check(sum(t.size for t in cs.targets) > 0,
      f"суммарный объём целей: {human(sum(t.size for t in cs.targets))}")

ss = appmod.StartupScreen(application)
ss.do_scan()
lines = application.frame(ss, ctx)
check(any("com.removed.app1.helper" in x for x in lines),
      "StartupScreen показал элемент автозагрузки")
check(any("битый" in x or "⚠" in x for x in lines), "битый элемент помечен")

os_ = appmod.OrphansScreen(application)
os_.do_scan()
lines = application.frame(os_, ctx)
check(True, f"OrphansScreen отрисовал {len(lines)} строк")

# --------------------------------------------------------------------------- #
section("cli: end-to-end")
env = dict(os.environ)
env.update({
    "HOME": str(HOME), "MACTWEAKER_HOME": str(HOME),
    "MACTWEAKER_SYSROOT": str(SYSROOT), "NO_COLOR": "1", "TERM": "dumb",
    "MACC_LANG": "ru",
})


def cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "maccc.py"),
                           "--no-color", *args],
                          capture_output=True, text=True, env=env, timeout=300,
                          cwd=str(ROOT))


r = cli("--version")
check(r.returncode == 0 and "2." in r.stdout, f"--version: {r.stdout.strip()}")
r = cli("info")
check(r.returncode == 0 and "Система" in r.stdout, "info работает")
r = cli("scan", "--profile", "basic")
check(r.returncode == 0 and "ИТОГО" in r.stdout, "scan basic работает")
r = cli("orphans", "--no-spotlight")
check(r.returncode == 0, "orphans работает")
r = cli("startup", "dead")
check(r.returncode == 0 and "мёртвый груз" in r.stdout, "startup dead работает")
r = cli("tweaks", "list")
check(r.returncode == 0, f"tweaks list: rc={r.returncode} {r.stderr[-200:]}")
r = cli("deep", "--risk", "0")
check(r.returncode == 0, "deep работает")
r = cli("disk", "--min-mb", "20")
check(r.returncode == 0, "disk работает")
r = cli("undo", "--list")
check(r.returncode == 0, "undo --list работает")
r = cli("scan", "--profile", "dev", "--report", "/tmp/mt-report.json")
check(r.returncode == 0 and Path("/tmp/mt-report.json").exists(),
      "scan --report создаёт JSON")

# текстовое меню при отсутствии TTY (pipe)
r = subprocess.run([sys.executable, str(ROOT / "maccc.py"), "--no-color"],
                   input="0\n", capture_output=True, text=True, env=env,
                   timeout=60, cwd=str(ROOT))
check(r.returncode == 0 and "текстовый режим" in r.stdout,
      "без TTY запускается текстовое меню")

section("bundle: single-file сборка")
bundle = ROOT / "dist" / "maccc_bundle.py"
if not bundle.exists():
    print("  SKIP dist/mac_tweaker_bundle.py отсутствует — запустите build_bundle.py")
else:
    rb = subprocess.run([sys.executable, str(bundle), "--version"],
                        capture_output=True, text=True, env=env, timeout=120)
    check(rb.returncode == 0 and "2." in rb.stdout,
          f"бандл запускается: {rb.stdout.strip() or rb.stderr[-120:]}")
    rb = subprocess.run([sys.executable, str(bundle), "--no-color", "startup", "dead"],
                        capture_output=True, text=True, env=env, timeout=180,
                        cwd="/tmp")
    check(rb.returncode == 0 and "мёртвый груз" in rb.stdout,
          "бандл работает из произвольной директории")
    rb = subprocess.run([sys.executable, str(bundle), "--no-color", "orphans",
                         "--no-spotlight"],
                        capture_output=True, text=True, env=env, timeout=180,
                        cwd="/tmp")
    check(rb.returncode == 0, f"бандл: orphans rc={rb.returncode}")

section("render: предпросмотр экранов")
pv = subprocess.run([sys.executable, str(HERE / "render_preview.py"),
                     "/tmp/mt-preview"],
                    capture_output=True, text=True, env=env, timeout=600,
                    cwd=str(ROOT))
check(pv.returncode == 0, f"render_preview.py rc={pv.returncode} {pv.stderr[-200:]}")
frames = sorted(Path("/tmp/mt-preview").glob("*.txt")) if Path("/tmp/mt-preview").exists() else []
check(len(frames) >= 10, f"отрендерено экранов: {len(frames)}")
check(all(f.stat().st_size > 200 for f in frames), "все кадры непустые")

section("i18n: двуязычный интерфейс")
import ast as _ast
from mactweaker import i18n as i18nmod
from mactweaker.i18n import CATALOG, set_lang, tr, get_lang

# 1) все tr("литералы") в коде имеют перевод
missing = set()
for f in sorted((ROOT / "mactweaker").glob("*.py")):
    tree = _ast.parse(f.read_text(encoding="utf-8"))
    for n in _ast.walk(tree):
        if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name) \
                and n.func.id == "tr" and n.args \
                and isinstance(n.args[0], _ast.Constant) \
                and isinstance(n.args[0].value, str):
            if n.args[0].value not in CATALOG:
                missing.add((f.name, n.args[0].value))
check(not missing, f"все tr()-литералы есть в каталоге ({len(missing)} пропущено)")

# 2) данные покрыты переводом
data_miss = []
for sp in junk.JUNK_SPECS:
    for x in (sp.name, sp.note, sp.category):
        if x and x not in CATALOG:
            data_miss.append(x)
for tw in tweaks.all_tweaks():
    for x in (tw.name, tw.description, tw.section):
        if x not in CATALOG:
            data_miss.append(x)
for v in startup.DOMAIN_LABEL.values():
    if v not in CATALOG:
        data_miss.append(v)
for v in startup.STATE_MARK.values():
    if v not in CATALOG:
        data_miss.append(v)
for v in leftovers.VERDICT_LABEL.values():
    if v not in CATALOG:
        data_miss.append(v)
check(not data_miss, f"имена целей/твиков/статусов покрыты ({len(data_miss)} пропущено)")

# 3) переключение работает
check(get_lang() == "ru" and tr("Автозагрузка") == "Автозагрузка", "ru по умолчанию")
set_lang("en", persist=False)
check(tr("Автозагрузка") == "Startup items", "tr() переводит при lang=en")
check(human(1536) == "1.5 KB", f"единицы EN: {human(1536)}")
set_lang("ru", persist=False)
check(human(1536) == "1.5 КБ", "единицы RU")

# 4) EN-рендер главного меню и очистки
set_lang("en", persist=False)
app_en = appmod.App(Theme(enabled=False, ascii_only=True), P)
app_en.term = FakeTerm()
app_en.sysinfo = application.sysinfo
ctx_en = RenderContext(app=app_en, painter=app_en.p, width=110, height=34)
mm = appmod.MainMenu(app_en)
lines_en = app_en.frame(mm, ctx_en)
blob_en = "\n".join(lines_en)
check("Cache & junk cleanup" in blob_en, "EN: пункт меню очистки")
check("Startup items" in blob_en, "EN: пункт автозагрузки")
check("Очистка кэшей" not in blob_en, "EN: русской строки в меню нет")
cs_en = appmod.CleanerScreen(app_en)
cs_en.do_scan()
blob2 = "\n".join(app_en.frame(cs_en, ctx_en))
check("selected:" in blob2 or "mark what you need" in blob2, "EN: экран очистки")
set_lang("ru", persist=False)
blob_ru = "\n".join(app_en.frame(appmod.MainMenu(app_en), ctx_en))
check("Очистка кэшей и мусора" in blob_ru, "возврат в RU работает")

# 5) регрессии по багам пользователей
set_lang("en", persist=False)
check(tr(WAIT_MESSAGES[0]) != WAIT_MESSAGES[0]
      and "frozen" in tr(WAIT_MESSAGES[0]),
      f"сменная надпись переведена: {tr(WAIT_MESSAGES[0])}")
cs_idle = appmod.CleanerScreen(app_en)
idle_lines = "\n".join(app_en.frame(cs_idle, ctx_en))
check("+ Xcode, simulators" in idle_lines,
      "EN: описания профилей на экране очистки переведены")
check("кэши браузеров" not in idle_lines, "EN: русских описаний профилей нет")
cs_sw = appmod.CleanerScreen(app_en)
set_lang("ru", persist=False)
cs_sw.do_scan()
ru_blob = "\n".join(app_en.frame(cs_sw, ctx_en))
check("Кэши пользователя" in ru_blob, "RU после скана: имена целей русские")
set_lang("en", persist=False)
en_blob = "\n".join(app_en.frame(cs_sw, ctx_en))
check("User caches" in en_blob and "Кэши пользователя (~/Library/Caches)" not in en_blob,
      "смена языка ПОСЛЕ скана пересобирает список (баг смешанных языков)")
set_lang("ru", persist=False)

# 6) конфиг языка сохраняется
cfg_file = P.state_dir / "config.json"
set_lang("en", persist=True, paths=P)
check(cfg_file.exists() and json.loads(cfg_file.read_text(encoding="utf-8"))["lang"] == "en",
      "выбор языка сохраняется в ~/.mac_tweaker/config.json")
check(i18nmod.saved_lang(paths=P) == "en", "saved_lang читает конфиг")
set_lang("ru", persist=True, paths=P)

section("startup: регрессия краша note_texts (баг релиз-кандидата)")
mixed = startup.LaunchItem(label="x.y", path=None, domain=startup.DOMAIN_USER)
mixed.notes = ["простая строка",                       # старый формат
               ("загружен, но завершился с кодом {code}", {"code": 7}),
               ("возможное назначение: {what}", {"what": "обновлятор"})]
texts = mixed.note_texts()
check(texts[0] == "простая строка", "строка-заметка не роняет note_texts")
check(texts[1] == "загружен, но завершился с кодом 7", "шаблон с аргументом работает")
check("обновлятор" in texts[2], "шаблон назначения работает")
set_lang("en", persist=False)
check("exited with code 7" in mixed.note_texts()[1], "заметки переводятся на лету")
check("updater" in mixed.note_texts()[2], "аргумент заметки переводится")
set_lang("ru", persist=False)

# полный цикл: отключённый элемент (строковые заметки старого типа) + скан экрана
ddir = startup.disabled_dir(P)
old = ddir / "com.old.string.notes.plist"
old.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.old.string.notes</string>
  <key>ProgramArguments</key><array><string>/bin/true</string></array>
</dict></plist>
''', encoding="utf-8")
items_old = startup.collect(P, include_system=False, include_login_items=False)
check(any(i.label == "com.old.string.notes" for i in items_old),
      "отключённый элемент подхватывается из хранилища")
for i in items_old:
    i.note_texts()          # не должно бросать ValueError
check(True, "note_texts не падает на элементах collect()")
ss2 = appmod.StartupScreen(application)
ss2.items = items_old
ss2.scanned = True
ss2.rebuild()               # ровно место краша из трейсбека пользователя
check(True, "StartupScreen.rebuild() с отключёнными элементами не крашится")
old.unlink(missing_ok=True)

section("ui: авто-ресайз окна")
from mactweaker.ui import fit_terminal, FIT_COLS, FIT_ROWS
check((FIT_COLS, FIT_ROWS) == (124, 35), "целевой размер окна 124×35")
check(fit_terminal() == "", "вне tty fit_terminal ничего не делает")

section("app: обёртка .app для двойного клика")
import plistlib as _plist
import zipfile as _zip
ba = subprocess.run([sys.executable, str(ROOT / "build_app.py")],
                    capture_output=True, text=True, env=env, timeout=600,
                    cwd=str(ROOT))
check(ba.returncode == 0, f"build_app.py rc={ba.returncode} {ba.stderr[-200:]}")
app_dir = ROOT / "dist" / "Mac Crap Cleaner.app"
check((app_dir / "Contents" / "Info.plist").exists(), "Info.plist на месте")
check((app_dir / "Contents" / "MacOS" / "launcher").exists(), "launcher на месте")
check((app_dir / "Contents" / "Resources" / "MacCC.icns").exists(), "MacCC.icns на месте")
check((app_dir / "Contents" / "Resources" / "maccc_bundle.py").exists(),
      "бандл внутри Resources")
if (app_dir / "Contents" / "Info.plist").exists():
    info = _plist.loads((app_dir / "Contents" / "Info.plist").read_bytes())
    check(info["CFBundleName"] == "Mac Crap Cleaner", "CFBundleName")
    check(info["CFBundleExecutable"] == "launcher", "CFBundleExecutable=launcher")
    check(info["CFBundleIconFile"] == "MacCC", "CFBundleIconFile=MacCC")
    check(info.get("LSUIElement") is True, "LSUIElement: stub не светится в Dock")
lc = app_dir / "Contents" / "MacOS" / "launcher"
check(lc.stat().st_mode & 0o111 != 0, "launcher исполняемый")
check(subprocess.run(["bash", "-n", str(lc)]).returncode == 0,
      "launcher: bash-синтаксис без ошибок")
lc_text = lc.read_text(encoding="utf-8")
check("read -r -n 1 -s" in lc_text and "read -rn1" not in lc_text,
      "launcher совместим с bash 3.2 (read -r -n 1 -s)")
check("set columns of window of t to 124" in lc_text
      and "set rows of window of t to 35" in lc_text,
      "launcher задаёт окну Terminal 124×35")
icns = (app_dir / "Contents" / "Resources" / "MacCC.icns").read_bytes()
check(icns[:4] == b"icns" and b"ic10" in icns[:40], "icns: магия и размер 1024 присутствуют")
zp = ROOT / "dist" / "Mac-Crap-Cleaner-app.zip"
check(zp.exists(), "zip-архив собран")
if zp.exists():
    with _zip.ZipFile(zp) as zf:
        names = zf.namelist()
        check(any(n.endswith("MacOS/launcher") for n in names), "zip содержит launcher")
        zi = zf.getinfo("Mac Crap Cleaner.app/Contents/MacOS/launcher")
        check((zi.external_attr >> 16) & 0o111 != 0, "zip сохраняет права +x")
# launcher: fallback-цепочка доводит до программы даже без osascript/open
lr = subprocess.run([str(lc)], input="0\n", capture_output=True, text=True,
                    env=env, timeout=120, cwd="/tmp")
check(lr.returncode == 0 and ("текстовый режим" in lr.stdout or "text mode" in lr.stdout),
      "launcher доводит до программы (fallback без macOS)")

# --------------------------------------------------------------------------- #
print("\n" + "=" * 62)
if FAILED:
    print(f"ПРОВАЛЕНО: {len(FAILED)} из {PASSED + len(FAILED)}")
    for f in FAILED:
        print("  - " + f)
    sys.exit(1)
print(f"ВСЕ ТЕСТЫ ПРОЙДЕНЫ: {PASSED}")
sys.exit(0)
