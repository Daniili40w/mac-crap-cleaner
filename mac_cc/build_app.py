#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Собирает macOS-обёртку «Mac Crap Cleaner.app» вокруг single-file бандла.

Структура (ровно та, что задумана):

    Mac Crap Cleaner.app/
    └── Contents/
        ├── Info.plist          метаданные + иконка + LSUIElement
        ├── MacOS/
        │   └── launcher        bash: открывает Terminal 124×35 и запускает TUI
        └── Resources/
            ├── MacCC.icns      иконка (пакуется из tools/icon_src.png)
            ├── maccc_bundle.py single-file бандл программы
            └── run.command     запасной запуск двойным кликом (без .app)

Дополнительно кладёт рядом dist/Mac-Crap-Cleaner-app.zip (с правами +x внутри).

Иконка пакуется чистым Python (decode PNG → nearest-resize → encode PNG →
icns-контейнер с типами ic10/ic09/ic08/ic07), поэтому сборка работает и без
iconutil/sips, т.е. не только на macOS.

    python3 build_app.py
"""

from __future__ import annotations

import plistlib
import shutil
import struct
import sys
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
APP_NAME = "Mac Crap Cleaner"
APP_DIR = DIST / f"{APP_NAME}.app"
ZIP_PATH = DIST / "Mac-Crap-Cleaner-app.zip"
ICON_SRC = ROOT / "tools" / "icon_src.png"
BUNDLE = DIST / "maccc_bundle.py"
VERSION = "2.1.0"

COLS, ROWS = 124, 35          # размер окна Terminal, как задумано

# --------------------------------------------------------------------------- #
#  PNG: минимальный декодер/энкодер (8 bit, color type 2/6)
# --------------------------------------------------------------------------- #


def _png_chunks(data: bytes):
    i = 8
    while i < len(data):
        (length,) = struct.unpack(">I", data[i:i + 4])
        ctype = data[i + 4:i + 8]
        yield ctype, data[i + 8:i + 8 + length]
        i += 12 + length


def png_decode(path: Path):
    """Возвращает (width, height, pixels) где pixels — список строк RGBA."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("не PNG")
    w = h = depth = ctype = None
    idat = b""
    for ctype_, payload in _png_chunks(data):
        if ctype_ == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", payload[:10])
        elif ctype_ == b"IDAT":
            idat += payload
    if depth != 8 or ctype not in (2, 6):
        raise ValueError(f"нужен PNG 8-bit RGB/RGBA, got depth={depth} type={ctype}")
    ch = 4 if ctype == 6 else 3
    raw = zlib.decompress(idat)
    stride = w * ch
    out = bytearray(h * stride)
    pos = 0
    prev = bytearray(stride)
    for y in range(h):
        filt = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if filt == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 0xFF
        elif filt == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filt == 3:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif filt == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        out[y * stride:(y + 1) * stride] = line
        prev = line
    # приводим к RGBA
    pixels = []
    for y in range(h):
        row = out[y * stride:(y + 1) * stride]
        if ch == 4:
            pixels.append(bytes(row))
        else:
            rgba = bytearray()
            for x in range(w):
                rgba += row[x * 3:x * 3 + 3] + b"\xff"
            pixels.append(bytes(rgba))
    return w, h, pixels


def png_resize(pixels, sw: int, sh: int, dw: int, dh: int):
    out = []
    for y in range(dh):
        sy = min(sh - 1, y * sh // dh)
        row = pixels[sy]
        if dw == sw:
            out.append(row)
            continue
        line = bytearray()
        for x in range(dw):
            sx = min(sw - 1, x * sw // dw)
            line += row[sx * 4:sx * 4 + 4]
        out.append(bytes(line))
    return out


def png_encode(pixels, w: int, h: int) -> bytes:
    raw = b"".join(b"\x00" + row for row in pixels)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def build_icns(src: Path, dest: Path) -> int:
    """Пакует PNG в .icns (ic10 1024, ic09 512, ic08 256, ic07 128)."""
    w, h, pixels = png_decode(src)
    body = b""
    for tag, size in ((b"ic10", 1024), (b"ic09", 512), (b"ic08", 256),
                      (b"ic07", 128)):
        px = png_resize(pixels, w, h, size, size)
        blob = png_encode(px, size, size)
        body += tag + struct.pack(">I", len(blob) + 8) + blob
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)
    return dest.stat().st_size


# --------------------------------------------------------------------------- #
#  launcher и Info.plist
# --------------------------------------------------------------------------- #

LAUNCHER = '''#!/bin/bash
# Mac Crap Cleaner — launcher для .app-обёртки.
# Открывает Terminal размером %(cols)s×%(rows)s и запускает TUI-бандл.
# Если AppleScript недоступен (нет прав автоматизации) — fallback через
# open -a Terminal на run.command.

DIR="$(cd "$(dirname "$0")" && pwd)"
RES="$(cd "$DIR/../Resources" && pwd)"
BUNDLE="$RES/maccc_bundle.py"

# ищем подходящий python3 (3.8+)
PY=""
for cand in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3 python3; do
    if command -v "$cand" >/dev/null 2>&1 && \\
       "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' \\
       >/dev/null 2>&1; then
        PY="$cand"
        break
    fi
done

if [ -z "$PY" ]; then
    osascript -e 'display dialog "Mac Crap Cleaner needs Python 3.8 or newer.\\n\\nInstall Xcode Command Line Tools:\\n    xcode-select --install" buttons {"OK"} default button 1 with title "Mac Crap Cleaner" with icon stop' >/dev/null 2>&1
    exit 1
fi

CMD="$PY '$BUNDLE'; echo; echo '  MacCC session finished — press any key to close this window.'; read -r -n 1 -s"

if osascript >/dev/null 2>&1 <<AS
tell application "Terminal"
    activate
    set t to (do script "$CMD")
    try
        set columns of window of t to %(cols)s
        set rows of window of t to %(rows)s
    end try
    try
        set font name of t to "Menlo"
        set font size of t to 12
    end try
end tell
AS
then
    exit 0
fi

# fallback 1: без AppleScript (размер окна останется из профиля Terminal)
if command -v open >/dev/null 2>&1 && \
   open -a Terminal "$RES/run.command" 2>/dev/null; then
    exit 0
fi

# fallback 2: не-macOS или ssh — запускаем прямо в текущем терминале
exec "$PY" "$BUNDLE"
''' % {"cols": COLS, "rows": ROWS}

RUN_COMMAND = '''#!/bin/bash
# Запасной запуск Mac Crap Cleaner двойным кликом (вне .app).
DIR="$(cd "$(dirname "$0")" && pwd)"
PY=""
for cand in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3 python3; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
clear
"$PY" "$DIR/maccc_bundle.py"
echo
echo "  MacCC session finished — press any key to close this window."
read -r -n 1 -s
'''

INFO_PLIST = {
    "CFBundleDevelopmentRegion": "en",
    "CFBundleDisplayName": APP_NAME,
    "CFBundleExecutable": "launcher",
    "CFBundleIconFile": "MacCC",
    "CFBundleIdentifier": "local.maccc.app",
    "CFBundleInfoDictionaryVersion": "6.0",
    "CFBundleName": APP_NAME,
    "CFBundlePackageType": "APPL",
    "CFBundleShortVersionString": VERSION,
    "CFBundleVersion": VERSION,
    "LSMinimumSystemVersion": "11.0",
    #_stub не светится в Dock и не создаёт меню: всё живёт в Terminal
    "LSUIElement": True,
    "NSHumanReadableCopyright": "MIT, no subscriptions, no bullshit",
    "NSAppleEventsUsageDescription":
        "Mac Crap Cleaner opens a sized Terminal window to run its interface.",
    "CFBundleGetInfoString": f"{APP_NAME} {VERSION} — less crap, zero subscriptions",
}


# --------------------------------------------------------------------------- #
#  сборка
# --------------------------------------------------------------------------- #

def build() -> int:
    if not BUNDLE.exists():
        print("  ! нет бандла — сначала: python3 build_bundle.py")
        return 1

    contents = APP_DIR / "Contents"
    for sub in ("MacOS", "Resources"):
        (contents / sub).mkdir(parents=True, exist_ok=True)

    (contents / "Info.plist").write_bytes(
        plistlib.dumps(INFO_PLIST, fmt=plistlib.FMT_XML))

    launcher = contents / "MacOS" / "launcher"
    launcher.write_text(LAUNCHER, encoding="utf-8")
    launcher.chmod(0o755)

    run_cmd = contents / "Resources" / "run.command"
    run_cmd.write_text(RUN_COMMAND, encoding="utf-8")
    run_cmd.chmod(0o755)

    shutil.copy2(BUNDLE, contents / "Resources" / "maccc_bundle.py")

    if ICON_SRC.exists():
        size = build_icns(ICON_SRC, contents / "Resources" / "MacCC.icns")
        print(f"  иконка MacCC.icns: {size // 1024} КБ (ic10/ic09/ic08/ic07)")
    else:
        print(f"  ! нет {ICON_SRC.relative_to(ROOT)} — иконка пропущена")

    # zip с сохранением прав исполнения
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(APP_DIR.rglob("*")):
            arc = p.relative_to(DIST).as_posix()
            if p.is_dir():
                zi = zipfile.ZipInfo(arc + "/")
                zi.external_attr = (0o40755 << 16) | 0x10
                zf.writestr(zi, b"")
            else:
                zi = zipfile.ZipInfo(arc)
                mode = p.stat().st_mode & 0o7777
                zi.external_attr = (mode << 16)
                zi.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(zi, p.read_bytes())

    print(f"  собрано: {APP_DIR.relative_to(ROOT)}/")
    print(f"           {ZIP_PATH.relative_to(ROOT)} "
          f"({ZIP_PATH.stat().st_size // 1024} КБ)")
    print()
    print("  Установка:")
    print(f"    unzip -o {ZIP_PATH.name} -d /Applications/")
    print("    # при первом запуске Gatekeeper может спросить разрешение:")
    print(f"    xattr -dr com.apple.quarantine '/Applications/{APP_NAME}.app'")
    print("    # (опционально) ad-hoc подпись для своего Mac:")
    print(f"    codesign --force --deep -s - '/Applications/{APP_NAME}.app'")
    return 0


if __name__ == "__main__":
    sys.exit(build())
