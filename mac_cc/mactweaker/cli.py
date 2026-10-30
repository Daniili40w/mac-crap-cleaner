"""
mactweaker.cli — субкоманды для работы без псевдографики (cron, ssh, пайпы).

    mac_tweaker.py info
    mac_tweaker.py scan    [--profile dev] [--older-than-days 30] [--report x.json]
    mac_tweaker.py clean   [--profile dev] [-y] [--hard] [--empty-trash]
    mac_tweaker.py deep    [--scan|--clean] [--older-than-days N] [-y]
    mac_tweaker.py orphans [--scan|--clean] [--include-unknown] [-y]
    mac_tweaker.py startup [list|disable|enable|restore|dead] [--label X]
    mac_tweaker.py tweaks  [list|apply|revert|export|import] [--id X]
    mac_tweaker.py disk    [--min-mb 500]
    mac_tweaker.py snapshots [--delete-all] [-y] [--sudo]
    mac_tweaker.py schedule [status|install|uninstall] [--weekday 0 --hour 4]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from . import junk, leftovers, osprofile, schedule, startup, system, tweaks
from .i18n import resolve_lang, tr
from .safety import (Deleter, Journal, Paths, ago, human, is_root,
                     permission_warnings, reset_denied, run, safe_exists,
                     sudo_ok)
from .i18n import get_lang
from .ui import Theme, detect_theme


# --------------------------------------------------------------------------- #
#  общий вывод
# --------------------------------------------------------------------------- #

def _print_head(title: str, th: Theme) -> None:
    print()
    print(th.bold + th.b_cyan + f"── {tr(title)} " + th.reset +
          th.dim + "─" * max(0, 62 - len(title)) + th.reset)


def _warn_denied(paths: Paths) -> None:
    """Если сканер упёрся в TCC — явно сказать, что нужен Full Disk Access."""
    warns = permission_warnings(paths)
    if not warns:
        return
    print("\n  ! " + tr("Нет прав на сканирование {n} каталогов: {ex}").format(
        n=len(warns), ex=", ".join(warns)), file=sys.stderr)
    print("    " + osprofile.fda_hint(), file=sys.stderr)


def _confirm(question: str, assume_yes: bool, default: bool = False) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return default
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        ans = input(th_bold() + question + th_reset() + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return ans in ("y", "yes", "д", "да") if ans else default


def th_bold() -> str:
    return "\033[1m" if sys.stdout.isatty() else ""


def th_reset() -> str:
    return "\033[0m" if sys.stdout.isatty() else ""


def _get_paths(args) -> Paths:
    home = Path(args.home) if getattr(args, "home", None) else None
    sysroot = Path(args.sysroot) if getattr(args, "sysroot", None) else None
    return Paths.detect(home=home, sysroot=sysroot)


def _deleter(paths: Paths, args, hard: bool = False) -> Deleter:
    mode = "dry" if getattr(args, "dry_run", False) else ("hard" if hard else "trash")
    use_sudo = bool(getattr(args, "sudo", False))
    if use_sudo and not sudo_ok(non_interactive=True):
        run(["sudo", "-v"], timeout=120)
        use_sudo = sudo_ok(non_interactive=True)
    return Deleter(paths, mode=mode, use_sudo=use_sudo, journal=Journal(paths))


# --------------------------------------------------------------------------- #
#  команды
# --------------------------------------------------------------------------- #

def cmd_info(args) -> int:
    paths = _get_paths(args)
    si = system.collect(paths)
    _print_head(tr(" Система ").strip(), detect_theme(args.ascii, args.no_color))
    for ln in si.summary_lines():
        print("  " + ln)
    feats = osprofile.get_os_features(arch=si.arch)
    import os as _os
    if feats.major and (si.is_darwin or _os.environ.get("MACTWEAKER_MACOS_MAJOR")):
        extra = ""
        if not feats.supports_intel:
            extra = "  •  " + tr("только Apple Silicon")
        if feats.needs_snapshot_check:
            extra += "  •  " + tr("проверьте APFS-снапшоты (maccc snapshots)")
        print("  " + tr("Профиль ОС: {name} ({major})").format(
            name=feats.name, major=feats.major) + extra)
    if si.full_disk_access is False:
        print("  ! " + tr("Нет Full Disk Access: ") + osprofile.fda_hint())
    _print_head(tr(" Крупнейшие каталоги дома ").strip(),
                detect_theme(args.ascii, args.no_color))
    for p, size in system.top_level_sizes(paths.home, 12):
        print(f"  {human(size).rjust(9)}  {paths.short(p)}")
    return 0


def cmd_scan(args) -> int:
    paths = _get_paths(args)
    th = detect_theme(args.ascii, args.no_color)
    reset_denied()
    targets = junk.scan_junk(paths, profile=args.profile,
                             older_than_days=args.older_than_days,
                             include_dirs=args.include_dir or [],
                             excludes=args.exclude or [])
    by_cat = junk.group_by_category(targets)
    grand = 0
    for cat in sorted(by_cat):
        _print_head(cat, th)
        for t in by_cat[cat]:
            grand += t.size
            size_s = human(t.size) if t.kind != "command" else tr("команда")
            mark = th.b_red + "⚠ " + th.reset if t.dangerous else ""
            print(f"  {size_s.rjust(9)}  {mark}{tr(t.name)}")
            if t.paths:
                print(th.dim + f"             {t.preview(paths, 2)}" + th.reset)
            if t.dangerous:
                print(th.dim + "             " +
                      tr("это данные, а не кэш — clean пропустит их без --dangerous")
                      + th.reset)
    trash = junk.trash_size(paths)
    _print_head(tr("Корзина"), th)
    print(f"  {human(trash).rjust(9)}  ~/.Trash")
    grand += trash
    _print_head(tr("ИТОГО можно освободить"), th)
    print(f"  {th.bold}{th.green}{human(grand)}{th.reset}")
    if args.report:
        payload = {
            "profile": args.profile, "total_bytes": grand, "trash_bytes": trash,
            "targets": [{"category": t.category, "name": t.name, "bytes": t.size,
                         "files": t.files, "root_required": t.root_required,
                         "dangerous": t.dangerous,
                         "kind": t.kind, "command": t.command,
                         "paths": [str(p) for p in t.paths[:300]]} for t in targets],
        }
        Path(args.report).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
        print(f"\n  JSON: {args.report}")
    _warn_denied(paths)
    return 0


def cmd_clean(args) -> int:
    paths = _get_paths(args)
    th = detect_theme(args.ascii, args.no_color)
    journal = Journal(paths)
    reset_denied()
    targets = junk.scan_junk(paths, profile=args.profile,
                             older_than_days=args.older_than_days,
                             include_dirs=args.include_dir or [],
                             excludes=args.exclude or [])
    if args.no_commands:
        targets = [t for t in targets if t.kind != "command"]
    if args.only:
        targets = [t for t in targets
                   if any(o.lower() in t.name.lower() for o in args.only)]
    # опасные цели (веса ИИ-моделей, диски виртуалок) чистятся ТОЛЬКО
    # с явным флагом --dangerous: это не кэш, а данные пользователя
    dangerous = [t for t in targets if t.dangerous]
    if dangerous and not getattr(args, "dangerous", False):
        print("  ! " + tr("Пропущены опасные цели (веса моделей, диски VM): {n}. "
                           "Флаг --dangerous включит их в очистку.")
              .format(n=len(dangerous)))
    if getattr(args, "dangerous", False):
        for t in dangerous:
            t.selected = True
    total = sum(t.size for t in targets if t.selected)
    _print_head(tr("Будет очищено"), th)
    for t in targets:
        if not t.selected:
            continue
        mark = th.b_red + "⚠ " + th.reset if t.dangerous else ""
        print(f"  {human(t.size).rjust(9)}  {mark}{tr(t.name)}")
    if dangerous and getattr(args, "dangerous", False):
        print("  " + th.b_red + tr("⚠ Среди целей есть данные (не кэш): веса "
                                    "моделей и диски контейнеров будут удалены!")
              + th.reset)
    print(f"\n  {tr('Итого')}: {th.bold}{human(total)}{th.reset}  "
          f"({len([t for t in targets if t.selected])})  "
          f"{tr('Способ: ').strip().rstrip(':')}: "
          f"{tr('жёсткое (rm)') if args.hard else tr('в Корзину')}"
          f"{'  DRY-RUN' if args.dry_run else ''}")
    if not _confirm(tr("Продолжить?"), args.yes):
        print(tr("Отменено"))
        _warn_denied(paths)
        return 1
    targets = [t for t in targets if t.selected]

    need_root = any(t.root_required for t in targets)
    use_sudo = bool(args.sudo)
    if need_root and not use_sudo:
        if args.yes:
            print("  ! " + tr("системные кэши пропущены (нужен --sudo)"))
            targets = [t for t in targets if not t.root_required]
        else:
            use_sudo = _confirm(tr("Использовать sudo для системных кэшей?"), False)
            if use_sudo:
                run(["sudo", "-v"], timeout=120)
                use_sudo = sudo_ok(True)

    deleter = Deleter(paths, mode="dry" if args.dry_run else
                      ("hard" if args.hard else "trash"),
                      use_sudo=use_sudo, journal=journal)
    freed, errors, skipped = junk.clean_targets(targets, deleter)

    if args.empty_trash:
        before = junk.trash_size(paths)
        _ok = junk.empty_trash(paths, deleter)[1]
        freed += before if _ok else 0
        print(f"  {tr('Корзина')}: −{human(before) if _ok else tr('не очищена')}")

    _print_head(tr("Готово"), th)
    print(f"  {tr('освобождено: {size}').format(size=th.green + human(freed) + th.reset)}")
    print(f"  {tr('ошибок: {n}').format(n=errors)}   "
          f"{tr('пропущено (нет прав): {n}').format(n=skipped)}")
    if not args.hard and not args.dry_run and freed:
        print("  " + tr("всё в Корзине — можно вернуть или очистить её"))
    journal.add("clean", f"{freed} байт",
                {"profile": args.profile, "hard": args.hard,
                 "targets": [t.name for t in targets]})
    _warn_denied(paths)
    return 0 if errors == 0 else 1


def cmd_deep(args) -> int:
    paths = _get_paths(args)
    th = detect_theme(args.ascii, args.no_color)
    reset_denied()
    roots = [Path(r).expanduser() for r in (args.root or [])] or [paths.home]
    items = junk.deep_scan(paths, roots=roots, max_depth=args.depth,
                           older_than_days=args.older_than_days,
                           risk_max=args.risk, excludes=args.exclude or [])
    by_rule: dict = {}
    for it in items:
        by_rule.setdefault((it.category, it.rule), []).append(it)
    grand = 0
    for (cat, rule), group in sorted(by_rule.items(),
                                     key=lambda kv: -sum(i.size for i in kv[1])):
        size = sum(i.size for i in group)
        grand += size
        _print_head(f"{tr(cat)}: {tr(rule)} — {len(group)}, {human(size)}", th)
        for it in group[:args.limit]:
            risk = tr({0: "безопасно", 1: "спросить", 2: "совет"}[it.risk])
            print(f"  {human(it.size).rjust(9)}  {paths.short(it.path)}"
                  f"   {th.dim}[{risk}, {ago(it.mtime)}]{th.reset}")
        if len(group) > args.limit:
            print(th.dim + f"  … ещё {len(group) - args.limit}" + th.reset)
    _print_head(tr("ИТОГО найдено"), th)
    print(f"  {th.bold}{human(grand)}{th.reset} / {len(items)}")
    _warn_denied(paths)

    if not args.clean:
        return 0
    to_delete = [i for i in items if (i.risk == junk.RISK_SAFE or args.all_risks)]
    if not to_delete:
        print("  " + tr("Нечего удалять (безопасных объектов нет)."))
        return 0
    total = sum(i.size for i in to_delete)
    if not _confirm(tr("Удалить {n} объектов ({size}) {mode}?").format(
            n=len(to_delete), size=human(total),
            mode=tr("жёсткое (rm)") if args.hard else tr("в Корзину")), args.yes):
        print(tr("Отменено"))
        return 1
    deleter = _deleter(paths, args, hard=args.hard)
    freed, failed = deleter.delete([i.path for i in to_delete])
    print(f"  {tr('освобождено: {size}').format(size=human(freed))}   "
          f"{tr('не удалось: {n}').format(n=len(failed))}")
    return 0


def cmd_orphans(args) -> int:
    paths = _get_paths(args)
    th = detect_theme(args.ascii, args.no_color)
    reset_denied()
    print("  " + tr("читаю реестр установленных программ…"), end="", flush=True)
    reg = leftovers.AppRegistry.build(paths, use_spotlight=not args.no_spotlight)
    print("\r  " + tr("Установлено программ: {n}").split("•")[0].strip()
          .format(n=len(reg.apps)) + " " * 20)
    items = leftovers.scan_leftovers(paths, registry=reg,
                                     include_unknown=args.include_unknown,
                                     include_system=args.include_system,
                                     min_size=args.min_size,
                                     min_age_days=args.min_age_days,
                                     excludes=args.exclude or [])
    by_src = leftovers.group_leftovers(items)
    grand = 0
    for src in sorted(by_src, key=lambda s: -sum(i.size for i in by_src[s])):
        group = sorted(by_src[src], key=lambda x: -x.size)
        size = sum(i.size for i in group)
        grand += size
        _print_head(f"{tr(src)} — {len(group)}, {human(size)}", th)
        for it in group[:args.limit]:
            v = tr(leftovers.VERDICT_LABEL.get(it.verdict, it.verdict))
            color = th.b_red if it.verdict == leftovers.VERDICT_ORPHAN else th.yellow
            print(f"  {human(it.size).rjust(9)}  {color}{v:<8}{th.reset} "
                  f"{paths.short(it.path)}")
            print(th.dim + f"             {it.evidence} • {ago(it.mtime)}" + th.reset)
    _print_head(tr("ИТОГО"), th)
    stat = leftovers.summarize(items)
    for v, d in sorted(stat.items(), key=lambda kv: -kv[1]["bytes"]):
        print(f"  {human(d['bytes']).rjust(9)}  "
              f"{tr(leftovers.VERDICT_LABEL.get(v, v))}: {d['count']}")
    print(f"  {th.bold}{human(grand)}{th.reset} {tr('всего найдено')}")

    if not args.clean:
        return 0
    to_delete = [i for i in items if i.selected]
    if args.include_unknown:
        to_delete = [i for i in items if i.verdict == leftovers.VERDICT_ORPHAN]
    if not to_delete:
        print("  " + tr("Сирот не найдено."))
        return 0
    total = sum(i.size for i in to_delete)
    if not _confirm(tr("Удалить {n} остатков удалённых программ ({size})?").format(
            n=len(to_delete), size=human(total)), args.yes):
        print(tr("Отменено"))
        return 1
    deleter = _deleter(paths, args, hard=args.hard)
    freed, failed = deleter.delete([i.path for i in to_delete])
    print(f"  освобождено: {human(freed)}   не удалось: {len(failed)}")
    return 0


def cmd_startup(args) -> int:
    paths = _get_paths(args)
    th = detect_theme(args.ascii, args.no_color)
    action = args.action

    if action == "restore":
        items = startup.disabled_items(paths)
        if not items:
            print("  " + tr("Нет отключённых элементов"))
            return 0
        results = startup.restore_all(paths, use_sudo=args.sudo)
        for it, ok, msg in results:
            print(("  " + th.green + "✓ " if ok else "  " + th.red + "✗ ")
                  + th.reset + f"{it.label}: {msg}")
        return 0

    items = startup.collect(paths, include_system=args.include_system,
                            include_login_items=not args.no_login_items,
                            include_btm=args.btm)
    if args.label:
        items = [i for i in items
                 if any(pat.lower() in i.label.lower() for pat in args.label)]
    if action == "dead":
        items = startup.dead_weight(items)

    if action == "dead":
        dead = startup.dead_weight(items)
        _print_head(tr("Подозрительные (мёртвый груз)"), th)
        if not dead:
            print("  " + tr("не найдено — автозагрузка выглядит чистой"))
        for it in dead:
            mark = (th.b_red + "⚠ " + th.reset) if (it.missing_binary or
                    it.state == startup.STATE_BROKEN or
                    it.state == startup.STATE_FAILED) else (th.yellow + "? " + th.reset)
            print(f"  {mark}{it.label}   {th.dim}{it.state_mark}"
                  f"{' • ' + startup.DOMAIN_LABEL.get(it.domain, '') if it.domain else ''}{th.reset}")
            if it.command:
                print(th.dim + f"      {it.command[:78]}" + th.reset)
            if it.developer:
                print(th.dim + f"      подписан: {it.developer}" + th.reset)
            for n in it.notes:
                print(th.dim + f"      • {n}" + th.reset)
        print(f"\n  {len(dead)} / {len(items)}")
        print("  maccc startup disable --label <name> -y")
        return 0

    by_domain = startup.group_by_domain(items)
    for domain, group in by_domain.items():
        _print_head(tr(startup.DOMAIN_LABEL.get(domain, domain)), th)
        for it in group:
            mark = {startup.STATE_RUNNING: th.green + "▶",
                    startup.STATE_LOADED: th.cyan + "●",
                    startup.STATE_FAILED: th.red + "✗",
                    startup.STATE_BROKEN: th.b_red + "⚠",
                    startup.STATE_DISABLED: th.dim + "⛔",
                    startup.STATE_UNLOADED: th.dim + "○"}.get(it.state, "?")
            lock = "" if it.disable_allowed else th.dim + " 🔒" + th.reset
            print(f"  {mark}{th.reset} {it.label}{lock}")
            det = []
            if it.developer:
                det.append(it.developer)
            if it.command:
                det.append(it.command[:70])
            if it.notes:
                det.append(it.note_texts()[0])
            if det:
                print(th.dim + f"      {' • '.join(det)}" + th.reset)
        print(th.dim + f"      всего: {len(group)}" + th.reset)

    if action == "disable":
        if not args.label:
            print("\n  " + tr("Укажите --label <часть имени> для отключения."))
            return 2
        work = [i for i in items if i.disable_allowed]
        if not work:
            print("  " + tr("Нечего отключать (все защищены)."))
            return 1
        if not _confirm(tr("Отключить элементов: {n}").format(n=len(work)) +
                        " (~/.mac_tweaker/disabled/)", args.yes):
            print(tr("Отменено"))
            return 1
        use_sudo = args.sudo or any(i.domain == startup.DOMAIN_DAEMON for i in work)
        if use_sudo and not sudo_ok(True):
            run(["sudo", "-v"], timeout=120)
            use_sudo = sudo_ok(True)
        for it, ok, msg in startup.disable(work, paths, use_sudo):
            print(("  " + th.green + "✓ " if ok else "  " + th.red + "✗ ")
                  + th.reset + f"{it.label}: {msg}")
        return 0

    if action == "enable":
        work = [i for i in items if i.state == startup.STATE_DISABLED] or items
        for it, ok, msg in startup.enable(work, paths, args.sudo):
            print(("  " + th.green + "✓ " if ok else "  " + th.red + "✗ ")
                  + th.reset + f"{it.label}: {msg}")
        return 0

    dead = startup.dead_weight(items)
    _print_head(tr("Подозрительные (мёртвый груз)"), th)
    if not dead:
        print("  " + tr("не найдено — автозагрузка выглядит чистой"))
    for it in dead:
        print(f"  {th.b_red}⚠{th.reset} {it.label}  "
              + th.dim + f"{tr(it.state_mark)} • {'; '.join(it.note_texts()[:2])}"
              + th.reset)
    print(th.dim + "  maccc startup disable --label <name> -y" + th.reset)
    return 0


def cmd_tweaks(args) -> int:
    paths = _get_paths(args)
    th = detect_theme(args.ascii, args.no_color)
    action = args.action
    all_tw = tweaks.all_tweaks()
    if args.id:
        all_tw = [t for t in all_tw if any(i in t.tid for i in args.id)]

    if action == "export":
        ok, msg = tweaks.export_defaults(paths)
        print(("  " + th.green + "✓ " if ok else "  " + th.red + "✗ ")
              + th.reset + msg)
        return 0 if ok else 1
    if action == "import":
        ok, msg = tweaks.import_defaults(paths)
        print(("  " + th.green + "✓ " if ok else "  " + th.red + "✗ ")
              + th.reset + msg)
        return 0 if ok else 1

    tweaks.refresh(all_tw)
    if action == "list":
        cur = None
        for t in all_tw:
            if t.section != cur:
                cur = t.section
                _print_head(tr(cur), th)
            on_s = "ON" if get_lang() == "en" else "ВКЛ"
            off_s = "off" if get_lang() == "en" else "выкл"
            mark = th.green + on_s + th.reset if t.state else th.dim + off_s + th.reset
            risk = th.yellow + " !" + th.reset if t.risky else ""
            print(f"  {mark}  {t.tid:<26} {tr(t.name)}{risk}")
            print(th.dim + f"        {tr(t.description)}  [{t.domain} {t.key} = "
                           f"{t.raw}]" + th.reset)
        return 0

    if action in ("apply", "revert"):
        on = action == "apply"
        if not all_tw:
            print("  --id: no match / совпадений нет")
            return 2
        lines = ["  " + (tr("включить") if on else tr("вернуть в исходное"))
                 + f": {len(all_tw)}"]
        for t in all_tw:
            lines.append(f"    • {tr(t.name)}")
        print("\n".join(lines))
        if any(t.risky for t in all_tw):
            print(th.yellow + "  " +
                  tr("Есть рискованные: {n} — прочитайте описания!").format(
                      n=sum(1 for t in all_tw if t.risky)) + th.reset)
        if not _confirm(tr("Продолжить?"), args.yes):
            print(tr("Отменено"))
            return 1
        results = tweaks.apply(all_tw, on=on, dry_run=args.dry_run)
        okc = sum(1 for _, ok, _m in results if ok)
        for t, ok, msg in results:
            if not ok:
                print(f"  {th.red}✗{th.reset} {t.name}: {msg}")
        print("  " + (tr("Применено: {ok} из {total}") if on
                        else tr("Откачено: {ok} из {total}")).format(
            ok=okc, total=len(results)))
        return 0
    return 0


def cmd_disk(args) -> int:
    paths = _get_paths(args)
    th = detect_theme(args.ascii, args.no_color)
    root = Path(args.root).expanduser() if args.root else paths.home
    _print_head(f"{tr('Каталоги')}: {paths.short(root)}", th)
    for p, size, isdir in _dir_sizes_cli(root, args.limit):
        print(f"  {human(size).rjust(9)}  {paths.short(p)}"
              + ("" if isdir else th.dim + "  (file)" + th.reset))
    _print_head(tr(" Крупные файлы ").strip() + f" > {args.min_mb} MB", th)
    big = leftovers.big_files(paths, min_mb=args.min_mb, limit=args.limit,
                              roots=[root])
    if not big:
        print("  " + tr("не найдено"))
    for f in big:
        print(f"  {human(f.size).rjust(9)}  {paths.short(f.path)}"
              + th.dim + f"  {ago(f.mtime)}" + th.reset)
    return 0


def _dir_sizes_cli(root: Path, limit: int) -> List[Tuple[Path, int, bool]]:
    from concurrent.futures import ThreadPoolExecutor
    from .safety import dir_size, safe_scandir, workers
    tasks: List[Tuple[Path, bool]] = []
    for e in safe_scandir(root):
        try:
            p = Path(e.path)
            if e.is_symlink():
                continue
            tasks.append((p, e.is_dir(follow_symlinks=False)))
        except OSError:
            continue

    def measure(item: Tuple[Path, bool]) -> Tuple[Path, int, bool]:
        p, isdir = item
        try:
            size = dir_size(p)[0] if isdir else p.stat().st_size
        except OSError:
            size = 0
        return (p, size, isdir)

    out: List[Tuple[Path, int, bool]] = []
    n = max(1, min(workers(), len(tasks) or 1))
    if n == 1 or not tasks:
        out = [measure(t) for t in tasks]
    else:
        with ThreadPoolExecutor(max_workers=n) as ex:
            out = list(ex.map(measure, tasks))
    out.sort(key=lambda x: -x[1])
    return out[:limit]


def cmd_snapshots(args) -> int:
    paths = _get_paths(args)
    th = detect_theme(args.ascii, args.no_color)
    _print_head(tr("Локальные снапшоты APFS"), th)
    if not osprofile.snapshots_supported():
        print("  " + tr("Доступно только на macOS (tmutil)."))
        return 0
    dates = osprofile.list_local_snapshots(args.volume)
    if not dates:
        print("  " + tr("Локальных снапшотов нет — место не «зависло»."))
        return 0
    feats = osprofile.get_os_features()
    print(f"  {tr('Найдено снапшотов: {n}').format(n=len(dates))}")
    for d in dates:
        print(f"    com.apple.TimeMachine.{d}.local")
    print("  " + th.dim + tr("Снапшоты удерживают удалённые блоки: очистка кэшей "
                              "без их удаления может «не освободить» место.")
          + th.reset)
    if feats.needs_snapshot_check:
        print("  " + th.dim + tr("На {name} это частая причина «иллюзии "
                                 "свободного места».").format(name=feats.name)
              + th.reset)
    if not args.delete_all:
        return 0
    if not args.yes and not _confirm(
            tr("Удалить ВСЕ локальные снапшоты? Это необратимо."), False):
        print(tr("Отменено"))
        return 1
    use_sudo = bool(args.sudo)
    if use_sudo and not sudo_ok(non_interactive=True):
        run(["sudo", "-v"], timeout=120)
        use_sudo = sudo_ok(non_interactive=True)
    ok = errs = 0
    for d in dates:
        good, msg = osprofile.delete_local_snapshot(d, use_sudo=use_sudo)
        print(("  " + th.green + "✓ " if good else "  " + th.red + "✗ ")
              + th.reset + f"{d}: {msg}")
        ok += 1 if good else 0
        errs += 0 if good else 1
    print(f"  {tr('Удалено снапшотов: {ok} из {n}').format(ok=ok, n=len(dates))}")
    return 0 if errs == 0 else 1


def cmd_schedule(args) -> int:
    paths = _get_paths(args)
    th = detect_theme(args.ascii, args.no_color)
    action = args.action
    if action == "status":
        _print_head(tr("Автоочистка по расписанию"), th)
        st = schedule.agent_status(paths)
        for ln in st.summary(paths):
            print("  " + ln)
        print("  " + th.dim + tr("Запуск: ") + (st.runner or "—") + th.reset)
        return 0
    if action == "install":
        ok, msg = schedule.install_agent(paths, profile=args.profile,
                                         weekday=args.weekday, hour=args.hour,
                                         minute=args.minute)
        print(("  " + th.green + "✓ " if ok else "  " + th.red + "✗ ")
              + th.reset + msg)
        if ok:
            print("  " + th.dim + tr("Отчёт: {path}").format(
                path=paths.short(schedule.report_path(paths))) + th.reset)
        return 0 if ok else 1
    if action == "uninstall":
        if not args.yes and not _confirm(
                tr("Удалить агент и снять его с launchd?"), False):
            print(tr("Отменено"))
            return 1
        ok, msg = schedule.uninstall_agent(paths)
        print(("  " + th.green + "✓ " if ok else "  " + th.red + "✗ ")
              + th.reset + msg)
        return 0 if ok else 1
    return 2


def cmd_undo(args) -> int:
    paths = _get_paths(args)
    th = detect_theme(args.ascii, args.no_color)
    journal = Journal(paths)
    journal.entries = Journal.load(paths)
    entries = journal.entries[-500:]
    if args.list:
        for e in entries[-args.limit:]:
            print(f"  {e.get('ts', '')}  {e.get('kind', ''):<16} {e.get('target', '')}")
        return 0
    if not _confirm(tr("Вернуть из Корзины всё, что удалял Mac Crap Cleaner") + "?",
                    args.yes):
        print("Отменено.")
        return 1
    restored, problems = journal.undo_last_session()
    print(f"  {th.green}✓{th.reset} " +
          tr("Восстановлено из Корзины: {n}").format(n=restored))
    for p in problems[:10]:
        print(f"  {th.red}✗{th.reset} {p}")
    return 0


# --------------------------------------------------------------------------- #
#  парсер
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    prog_name = Path(sys.argv[0]).name if sys.argv else "mac_tweaker.py"
    if prog_name.endswith(".py"):
        prog_name = prog_name[:-3]
    ap = argparse.ArgumentParser(
        prog=prog_name,
        description="Mac Crap Cleaner (MacCC) — псевдографический инструмент "
                    "обслуживания macOS.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Без субкоманды запускается псевдографическое меню (нужен терминал).
Примеры:
  mac_tweaker.py                                  # TUI
  mac_tweaker.py scan --profile dev               # что можно очистить
  mac_tweaker.py clean --profile aggressive -y    # очистить в Корзину
  mac_tweaker.py orphans --clean -y               # остатки удалённых программ
  mac_tweaker.py deep --clean --risk 0 -y         # только безопасный хлам
  mac_tweaker.py startup dead                     # что грузится зря
  mac_tweaker.py startup disable --label adobe -y
  mac_tweaker.py tweaks list | grep ВКЛ
  mac_tweaker.py disk --min-mb 1000
  mac_tweaker.py snapshots                    # куда «пропало» свободное место
  mac_tweaker.py schedule install --hour 4    # еженедельная автоочистка
""")
    from . import __version__ as _version
    ap.add_argument("--version", action="version",
                    version=f"%(prog)s {_version}")
    ap.add_argument("--ascii", action="store_true", help="ASCII-псевдографика")
    ap.add_argument("--no-color", action="store_true", help="без цвета")
    ap.add_argument("--no-tui", action="store_true",
                    help="не запускать псевдографику (текстовое меню)")
    ap.add_argument("--lang", choices=("ru", "en"), default=None,
                    help="язык интерфейса: ru | en (сохраняется в конфиг)")
    ap.add_argument("--home", help="подменить домашкий каталог (для тестов)")
    ap.add_argument("--sysroot", help="подменить корень ФС (для тестов)")

    sub = ap.add_subparsers(dest="cmd")

    def common(sp, sudo=True, hard=True, yes=True):
        if yes:
            sp.add_argument("-y", "--yes", action="store_true",
                            help="не спрашивать подтверждение")
        if hard:
            sp.add_argument("--hard", action="store_true",
                            help="удалять навсегда (rm) вместо Корзины")
        if sudo:
            sp.add_argument("--sudo", action="store_true",
                            help="использовать sudo для системных объектов")
        sp.add_argument("--dry-run", action="store_true", help="ничего не менять")
        sp.add_argument("--exclude", action="append", default=[],
                        help="glob-маска исключения")

    sp = sub.add_parser("info", help="сведения о системе")
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("scan", help="показать, что можно очистить")
    sp.add_argument("-p", "--profile", choices=junk.PROFILES, default="basic")
    sp.add_argument("--older-than-days", type=float, default=None)
    sp.add_argument("--include-dir", action="append", default=[])
    sp.add_argument("--report", help="сохранить JSON-отчёт")
    common(sp, sudo=False, hard=False, yes=False)
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("clean", help="очистить кэши")
    sp.add_argument("-p", "--profile", choices=junk.PROFILES, default="basic")
    sp.add_argument("--older-than-days", type=float, default=None)
    sp.add_argument("--include-dir", action="append", default=[])
    sp.add_argument("--only", action="append", default=[],
                    help="только цели, чьё имя содержит подстроку")
    sp.add_argument("--no-commands", action="store_true",
                    help="не вызывать brew/docker/npm")
    sp.add_argument("--empty-trash", action="store_true", help="очистить Корзину")
    sp.add_argument("--dangerous", action="store_true",
                    help="включить опасные цели: веса ИИ-моделей, диски "
                         "Docker/OrbStack (не кэш — данные!)")
    common(sp)
    sp.set_defaults(func=cmd_clean)

    sp = sub.add_parser("deep", help="глубокий скан хлама")
    sp.add_argument("--root", action="append", default=[], help="каталог для скана")
    sp.add_argument("--depth", type=int, default=7)
    sp.add_argument("--risk", type=int, default=1, choices=(0, 1, 2),
                    help="0=только безопасное, 1=+спорное, 2=+советы")
    sp.add_argument("--older-than-days", type=float, default=None)
    sp.add_argument("--limit", type=int, default=25)
    sp.add_argument("--clean", action="store_true", help="удалять найденное")
    sp.add_argument("--all-risks", action="store_true",
                    help="удалять и спорное (не только безопасное)")
    common(sp)
    sp.set_defaults(func=cmd_deep)

    sp = sub.add_parser("orphans", help="остатки удалённых программ")
    sp.add_argument("--include-unknown", action="store_true",
                    help="показывать элементы с неопределённым владельцем")
    sp.add_argument("--include-system", action="store_true",
                    help="показывать компоненты Apple")
    sp.add_argument("--no-spotlight", action="store_true",
                    help="не использовать mdfind (быстрее)")
    sp.add_argument("--min-size", type=int, default=0, help="минимум байт")
    sp.add_argument("--min-age-days", type=float, default=0.0)
    sp.add_argument("--limit", type=int, default=15)
    sp.add_argument("--clean", action="store_true", help="удалять найденное")
    common(sp)
    sp.set_defaults(func=cmd_orphans)

    sp = sub.add_parser("startup", help="автозагрузка")
    sp.add_argument("action", nargs="?", default="list",
                    choices=("list", "disable", "enable", "restore", "dead"))
    sp.add_argument("--label", action="append", default=[],
                    help="фильтр по подстроке в метке")
    sp.add_argument("--include-system", action="store_true",
                    help="показывать системные (SIP) элементы")
    sp.add_argument("--no-login-items", action="store_true",
                    help="не опрашивать System Events")
    sp.add_argument("--btm", action="store_true",
                    help="показать фоновые элементы (sfltool dumpbtm, нужен sudo)")
    common(sp)
    sp.set_defaults(func=cmd_startup)

    sp = sub.add_parser("tweaks", help="настройки системы")
    sp.add_argument("action", nargs="?", default="list",
                    choices=("list", "apply", "revert", "export", "import"))
    sp.add_argument("--id", action="append", default=[],
                    help="только твики, чей id содержит подстроку")
    common(sp, sudo=False, hard=False)
    sp.set_defaults(func=cmd_tweaks)

    sp = sub.add_parser("disk", help="анализ занятого места")
    sp.add_argument("--root", help="каталог (по умолчанию ~)")
    sp.add_argument("--min-mb", type=int, default=500)
    sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(func=cmd_disk)

    sp = sub.add_parser("undo", help="журнал и откат")
    sp.add_argument("--list", action="store_true", help="только показать журнал")
    sp.add_argument("--limit", type=int, default=60)
    common(sp, sudo=False, hard=False)
    sp.set_defaults(func=cmd_undo)

    sp = sub.add_parser("snapshots",
                        help="локальные снапшоты APFS (иллюзия свободного места)")
    sp.add_argument("--volume", default="/", help="том (по умолчанию /)")
    sp.add_argument("--delete-all", action="store_true",
                    help="удалить все локальные снапшоты (необратимо)")
    sp.add_argument("-y", "--yes", action="store_true",
                    help="не спрашивать подтверждение")
    sp.add_argument("--sudo", action="store_true",
                    help="использовать sudo (обычно требуется)")
    sp.set_defaults(func=cmd_snapshots)

    sp = sub.add_parser("schedule",
                        help="launchd-агент еженедельной автоочистки")
    sp.add_argument("action", nargs="?", default="status",
                    choices=("status", "install", "uninstall"))
    sp.add_argument("--profile", choices=junk.PROFILES, default="basic")
    sp.add_argument("--weekday", type=int, default=0,
                    help="день недели: 0=воскресенье … 6=суббота")
    sp.add_argument("--hour", type=int, default=4, help="час запуска (0-23)")
    sp.add_argument("--minute", type=int, default=0, help="минута запуска (0-59)")
    sp.add_argument("-y", "--yes", action="store_true",
                    help="не спрашивать подтверждение")
    sp.set_defaults(func=cmd_schedule)

    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # язык: --lang → MACC_LANG/конфиг → интерактивный вопрос → ru
    paths0 = _get_paths(args)
    resolve_lang(getattr(args, "lang", None), paths=paths0,
                 interactive=sys.stdin.isatty() and sys.stdout.isatty())

    if getattr(args, "func", None) is not None:
        paths = _get_paths(args)
        if is_root() and getattr(args, "cmd", "") not in ("info", "scan", "disk"):
            print("  ! Запуск от root не рекомендуется — используйте --sudo "
                  "для системных объектов.", file=sys.stderr)
        return args.func(args)

    # запуск TUI
    paths = _get_paths(args)
    if is_root():
        if sys.stdout.isatty() and sys.stdin.isatty() and not args.no_tui:
            print("Mac Crap Cleaner не запускает псевдографику от root: выйдите из "
                  "sudo и используйте флаг --sudo там, где нужны системные права.",
                  file=sys.stderr)
            return 2
        print("  ! " + tr("запуск от root: псевдографика отключена, "
                          "доступен текстовый режим"), file=sys.stderr)
    if not sys.stdout.isatty() or not sys.stdin.isatty() or args.no_tui:
        return plain_menu(args, paths)

    from .app import App, MainMenu
    from .ui import detect_theme
    theme = detect_theme(args.ascii, args.no_color)
    app = App(theme, paths)
    try:
        return app.start(MainMenu(app))
    finally:
        app.term.exit()


# --------------------------------------------------------------------------- #
#  Текстовое меню (когда нет TTY)
# --------------------------------------------------------------------------- #

PLAIN_ITEMS = (
    ("1", "Очистка кэшей (scan)", ["scan", "--profile", "basic"]),
    ("2", "Очистка кэшей разработчика", ["scan", "--profile", "dev"]),
    ("3", "Глубокий скан хлама", ["deep"]),
    ("4", "Остатки удалённых программ", ["orphans"]),
    ("5", "Автозагрузка: список", ["startup", "list"]),
    ("6", "Автозагрузка: подозрительные", ["startup", "dead"]),
    ("7", "Настройки: список", ["tweaks", "list"]),
    ("8", "Анализ диска", ["disk"]),
    ("9", "Информация о системе", ["info"]),
    ("0", "Выход", []),
)

def plain_menu(args, paths: Paths) -> int:
    print(tr("Mac Crap Cleaner (MacCC) — текстовый режим (нет TTY)"))
    while True:
        print("\n" + "=" * 56)
        for key, label, _cmd in PLAIN_ITEMS:
            print(f"  {key}. {tr(label)}")
        try:
            choice = input(tr("Выбор: ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice == "0":
            return 0
        match = [c for k, _l, c in PLAIN_ITEMS if k == choice]
        if not match:
            continue
        cmd = match[0]
        sub = build_parser().parse_args(cmd + ["--home", str(paths.home),
                                               "--sysroot", str(paths.sysroot)])
        try:
            sub.func(sub)
        except KeyboardInterrupt:
            print("\nпрервано")
