#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Рендерит экраны TUI в текст/HTML — для проверки вёрстки без настоящего
терминала и для демонстрации в README.

    python3 tests/render_preview.py /tmp/preview            # текстовые кадры
    python3 tests/render_preview.py /tmp/preview --html      # + preview.html
"""

from __future__ import annotations

import html
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from mactweaker import app as appmod, system                    # noqa: E402
from mactweaker.i18n import set_lang                             # noqa: E402
from mactweaker.safety import Paths                              # noqa: E402
from mactweaker.ui import RenderContext, Theme                   # noqa: E402

W, H = 112, 34


def build_app(color: bool) -> appmod.App:
    paths = Paths.detect()
    set_lang(os.environ.get("PREVIEW_LANG", "ru"), persist=False, paths=paths)
    theme = Theme(enabled=color, ascii_only=False)
    a = appmod.App(theme, paths)
    d = system.disk_usage(str(paths.home))
    a.sysinfo = system.SystemInfo(
        hostname="MacBook-Air.local", user="air", os_name="macOS",
        os_version="15.1", build="24B83", kernel="24.1.0", arch="arm64",
        model="MacBookAir10,1", cpu="Apple M2", cores=8,
        ram_total=16 * 1024 ** 3, ram_free=6 * 1024 ** 3, uptime=93600,
        python="3.9.6", is_darwin=True, has_sudo=False, homebrew=True,
        xcode_cli=True, disks=[d])
    return a


def screens(a: appmod.App):
    yield "01-main-menu", appmod.MainMenu(a), ()
    yield "02-info", appmod.InfoScreen(a), ()

    cs = appmod.CleanerScreen(a)
    yield "03-cleaner-idle", cs, ()
    cs.do_scan()
    yield "04-cleaner-scanned", cs, ()

    ds = appmod.DeepScreen(a)
    ds.do_scan()
    yield "05-deep", ds, ()

    os_ = appmod.OrphansScreen(a)
    os_.do_scan()
    yield "06-orphans", os_, ()

    ss = appmod.StartupScreen(a)
    ss.do_scan()
    yield "07-startup", ss, ()

    tw = appmod.TweaksScreen(a)
    tw.do_load()
    yield "08-tweaks", tw, ()

    yield "09-log", appmod.LogScreen(a), ()
    yield "10-help", appmod.HelpScreen(a), ()


ANSI_RE = re.compile(r"\033\[([0-9;]*)m")
COLOR_MAP = {
    "30": "#000", "31": "#c0392b", "32": "#27ae60", "33": "#d68910",
    "34": "#2471a3", "35": "#8e44ad", "36": "#16a085", "37": "#bdc3c7",
    "91": "#e74c3c", "92": "#2ecc71", "93": "#f1c40f", "94": "#5dade2",
    "95": "#bb8fce", "96": "#48c9b0",
}


def ansi_to_html(line: str) -> str:
    out: list = []
    bold = False
    dim = False
    color = "#d7dce0"
    pos = 0
    for m in ANSI_RE.finditer(line):
        out.append(html.escape(line[pos:m.start()]))
        pos = m.end()
        for code in (m.group(1) or "0").split(";"):
            if code == "0":
                bold, dim, color = False, False, "#d7dce0"
            elif code == "1":
                bold = True
            elif code == "2":
                dim = True
            elif code in COLOR_MAP:
                color = COLOR_MAP[code]
    out.append(html.escape(line[pos:]))
    style = f"color:{color}"
    if bold:
        style += ";font-weight:700"
    if dim:
        style += ";opacity:.62"
    text = "".join(out)
    return f'<span style="{style}">{text}</span>'


def main() -> int:
    outdir = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/preview")
    want_html = "--html" in sys.argv
    outdir.mkdir(parents=True, exist_ok=True)
    lang_tag = "-en" if os.environ.get("PREVIEW_LANG") == "en" else ""

    # текстовые кадры без цвета
    a = build_app(color=False)
    ctx = RenderContext(app=a, painter=a.p, width=W, height=H)
    names = []
    for name, scr, keys in screens(a):
        scr.on_enter(ctx)
        lines = a.frame(scr, ctx)
        (outdir / f"{name}{lang_tag}.txt").write_text("\n".join(lines) + "\n",
                                                      encoding="utf-8")
        names.append(name)
        print(f"  {name}{lang_tag}.txt  ({len(lines)} строк)")

    if want_html:
        a2 = build_app(color=True)
        ctx2 = RenderContext(app=a2, painter=a2.p, width=W, height=H)
        blocks = []
        for name, scr, keys in screens(a2):
            scr.on_enter(ctx2)
            lines = a2.frame(scr, ctx2)
            body = "".join(
                f'<div class="ln">{ansi_to_html(ln) or "&nbsp;"}</div>'
                for ln in lines)
            blocks.append(f'<h2>{name}</h2><div class="term">{body}</div>')
        doc = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>Mac Crap Cleaner — предпросмотр TUI</title>
<style>
 body{{background:#14161a;color:#d7dce0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;
      margin:0;padding:28px}}
 h1{{font-size:20px;margin:0 0 4px}} p.sub{{color:#8b93a1;margin:0 0 26px;font-size:13px}}
 h2{{font-size:13px;color:#48c9b0;text-transform:uppercase;letter-spacing:.08em;
    margin:30px 0 8px}}
 .term{{background:#0b0d10;border:1px solid #262a31;border-radius:10px;padding:14px 16px;
        font-family:"SF Mono",Menlo,Consolas,monospace;font-size:12.5px;line-height:1.34;
        white-space:pre;overflow-x:auto}}
 .ln{{min-height:1.34em}}
</style></head><body>
<h1>Mac Crap Cleaner (MacCC) — preview / предпросмотр псевдографики</h1>
<p class="sub">Так выглядят экраны в терминале {W}×{H}. Реальный интерфейс цветной
и управляется стрелками.</p>
{''.join(blocks)}
</body></html>"""
        (outdir / f"preview{lang_tag}.html").write_text(doc, encoding="utf-8")
        print(f"  preview{lang_tag}.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
