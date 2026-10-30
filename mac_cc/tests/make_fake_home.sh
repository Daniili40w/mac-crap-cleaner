#!/usr/bin/env bash
# Создание фейкового «macOS-дерева» для тестов.
# Использование:  bash tests/make_fake_home.sh [КАТАЛОГ]
set -e
ROOT="${1:-/tmp/fake_mac}"
rm -rf "$ROOT"
H="$ROOT/home"
S="$ROOT/sys"
mkdir -p "$H" "$S"

# --- системная часть ---
mkdir -p "$S/Applications" "$S/System/Applications/Utilities" \
         "$S/Library/Caches" "$S/Library/LaunchDaemons" "$S/Library/LaunchAgents" \
         "$S/private/var/log/asl" "$S/Users"
printf 'junk' > "$S/Library/Caches/com.apple.bird"
dd if=/dev/zero of="$S/Library/Caches/com.thirdparty.helper" bs=1M count=4 status=none
mkdir -p "$S/Library/Caches/com.apple.amsengagementd.classicdatavault"
echo "log" > "$S/private/var/log/system.log.gz"
echo "log" > "$S/private/var/log/system.log"

# --- «установленные» приложения ---
make_app() {  # $1=path  $2=bundle id  $3=name  $4=executable name
  mkdir -p "$1/Contents/MacOS"
  cat > "$1/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>$2</string>
  <key>CFBundleName</key><string>$3</string>
  <key>CFBundleExecutable</key><string>$4</string>
</dict></plist>
PLIST
  echo "#!/bin/sh" > "$1/Contents/MacOS/$4"
  chmod +x "$1/Contents/MacOS/$4"
}
make_app "$S/Applications/Safari.app"        "com.apple.Safari"          "Safari"       "Safari"
make_app "$S/Applications/Notes.app"         "com.apple.Notes"           "Notes"        "Notes"
make_app "$S/Applications/Telegram.app"      "org.telegram.desktop"      "Telegram"     "Telegram"
make_app "$S/Applications/Visual Studio Code.app" "com.microsoft.VSCode" "Code"         "Electron"
make_app "$H/Applications/MyTool.app"        "com.example.mytool"        "MyTool"       "MyTool"

# --- домашняя библиотека ---
mkdir -p "$H/Library/Caches/com.example.mytool" \
         "$H/Library/Caches/org.telegram.desktop" \
         "$H/Library/Caches/com.removed.app1" \
         "$H/Library/Caches/pip/http" \
         "$H/Library/Logs/DiagnosticReports" "$H/Library/Logs/SomeApp" \
         "$H/Library/Saved Application State/com.removed.app1.savedState" \
         "$H/Library/Application Support/RemovedApp" \
         "$H/Library/Application Support/Telegram" \
         "$H/Library/Application Support/Code/CachedData/xyz" \
         "$H/Library/Application Support/ImportantStuff" \
         "$H/Library/Preferences" "$H/Library/HTTPStorages" \
         "$H/Library/Containers" "$H/Library/Group Containers" \
         "$H/Library/LaunchAgents" \
         "$H/Library/Developer/Xcode/DerivedData/Proj-abc" \
         "$H/.config/removedtool" "$H/.cache/someapp" \
         "$H/Documents" "$H/Desktop" "$H/Downloads" "$H/.Trash" \
         "$H/Projects/demo/__pycache__" "$H/Projects/demo/src" \
         "$H/Projects/demo/node_modules/pkg" \
         "$H/.mac_tweaker/disabled"

dd if=/dev/zero of="$H/Library/Caches/com.removed.app1/cache.bin" bs=1M count=15 status=none
dd if=/dev/zero of="$H/Library/Caches/com.example.mytool/x.bin"   bs=1M count=3  status=none
dd if=/dev/zero of="$H/Library/Caches/pip/http/w.whl"             bs=1M count=6  status=none
dd if=/dev/zero of="$H/Library/Application Support/RemovedApp/data.db" bs=1M count=22 status=none
dd if=/dev/zero of="$H/Library/Application Support/Telegram/data" bs=1M count=9 status=none
dd if=/dev/zero of="$H/Library/Application Support/Code/CachedData/xyz/f" bs=1M count=2 status=none
echo "важное" > "$H/Library/Application Support/ImportantStuff/license.key"
echo "важный документ" > "$H/Documents/important.txt"
echo "log" > "$H/Library/Logs/SomeApp/app.log"
echo "log" > "$H/Library/Logs/app.log"
echo "crash" > "$H/Library/Logs/DiagnosticReports/Java_2026.crash"
echo "<plist><dict><key>CFBundleIdentifier</key><string>com.removed.app1</string></dict></plist>" \
    > "$H/Library/Preferences/com.removed.app1.plist"
echo "<plist><dict><key>CFBundleIdentifier</key><string>com.example.mytool</string></dict></plist>" \
    > "$H/Library/Preferences/com.example.mytool.plist"
dd if=/dev/zero of="$H/Library/HTTPStorages/com.removed.app1.cookies" bs=1k count=40 status=none
dd if=/dev/zero of="$H/Projects/demo/__pycache__/mod.cpython-39.pyc" bs=1k count=90 status=none
echo "print(1)" > "$H/Projects/demo/src/main.py"
dd if=/dev/zero of="$H/Projects/demo/node_modules/pkg/index.js" bs=1k count=300 status=none
echo "junk" > "$H/Projects/demo/.DS_Store"
echo "junk" > "$H/Desktop/.DS_Store"
echo "log line" > "$H/Projects/demo/run.log"
dd if=/dev/zero of="$H/Downloads/BigInstaller.dmg" bs=1M count=25 status=none
dd if=/dev/zero of="$H/Downloads/notes.txt" bs=1k count=5 status=none
touch -d "120 days ago" "$H/Downloads/BigInstaller.dmg" 2>/dev/null || \
  touch -A -1200000 "$H/Downloads/BigInstaller.dmg" 2>/dev/null || true
dd if=/dev/zero of="$H/.config/removedtool/state" bs=1k count=700 status=none
dd if=/dev/zero of="$H/.cache/someapp/blob" bs=1k count=900 status=none
dd if=/dev/zero of="$H/.Trash/junk.bin" bs=1M count=7 status=none
dd if=/dev/zero of="$H/Library/Developer/Xcode/DerivedData/Proj-abc/o.o" bs=1M count=33 status=none

# --- LaunchAgents ---
make_plist() { # $1=file $2=label $3=program $4=RunAtLoad
cat > "$1" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$2</string>
  <key>ProgramArguments</key><array><string>$3</string><string>--background</string></array>
  <key>RunAtLoad</key><$4/>
</dict></plist>
PLIST
}
make_plist "$H/Library/LaunchAgents/com.removed.app1.helper.plist" \
           "com.removed.app1.helper" "$S/Applications/RemovedApp.app/Contents/MacOS/Helper" "true"
make_plist "$H/Library/LaunchAgents/com.example.mytool.updater.plist" \
           "com.example.mytool.updater" "$H/Applications/MyTool.app/Contents/MacOS/MyTool" "true"
make_plist "$H/Library/LaunchAgents/com.apple.important.plist" \
           "com.apple.important" "/usr/bin/true" "false"
mkdir -p "$S/Library/LaunchDaemons"
make_plist "$S/Library/LaunchDaemons/com.removed.daemon.plist" \
           "com.removed.daemon" "/usr/local/bin/removed-daemon" "true"

# --- v2.2: современные пожиратели места и «сирота» Electron-приложения ---
mkdir -p "$H/.ollama/models/blobs" "$H/.orbstack/data" "$H/.lmstudio/models/m1"
dd if=/dev/zero of="$H/.ollama/models/blobs/sha256-abc" bs=1M count=6 status=none
dd if=/dev/zero of="$H/.orbstack/data/disk.img" bs=1M count=3 status=none
dd if=/dev/zero of="$H/.lmstudio/models/m1/model.gguf" bs=1M count=2 status=none
# профиль Electron-приложения GhostedApp (само приложение удалено)
G="$H/Library/Application Support/GhostedApp"
mkdir -p "$G/GPUCache" "$G/Local Storage/leveldb" "$G/Session Storage"
echo '{}' > "$G/Preferences"
dd if=/dev/zero of="$G/Local Storage/leveldb/x.ldb" bs=1k count=50 status=none
# групповой контейнер ЖИВОГО приложения (не должен попасть в сироты)
mkdir -p "$H/Library/Group Containers/ABCDE12345.com.example.mytool"
echo data > "$H/Library/Group Containers/ABCDE12345.com.example.mytool/store.db"
# кэш внутри песочного контейнера (защищённая зона, но чистить разрешено)
mkdir -p "$H/Library/Containers/com.example.sandboxed/Data/Library/Caches/tmp"
dd if=/dev/zero of="$H/Library/Containers/com.example.sandboxed/Data/Library/Caches/tmp/x" bs=1k count=100 status=none

echo "$ROOT"
