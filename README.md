# Mac Crap Cleaner (MacCC)

> Mac Crap Cleaner - Less crap. Zero subscriptions. No bullshit.

A terminal-based maintenance tool for macOS with a text user interface: cache cleaning, detection of "orphans" left behind by removed apps, a deep scan for scattered junk, a startup items manager, and reversible system tweaks.

**One language: Python 3.8+, zero third-party dependencies.** Only the standard library is used (`pathlib`, `plistlib`, `argparse`, `termios`, `zipfile`). The interface is drawn with ANSI escape codes and `termios`, with no `curses` and no `pip install`.

```
mac_tweaker/
├── maccc.py              # entry point (TUI + CLI)
├── build_bundle.py       # builds a single file: dist/maccc_bundle.py
├── mactweaker/
│   ├── __init__.py
│   ├── safety.py         # safeguards, stat wrappers, Trash, journal, TCC tracking
│   ├── osprofile.py      # per-version macOS profile: features, paths, FDA, APFS snapshots
│   ├── system.py         # system and disk information
│   ├── junk.py           # caches + deep junk scan (parallel traversal)
│   ├── leftovers.py      # leftovers of removed apps ("orphans", incl. Electron/Tauri)
│   ├── startup.py        # LaunchAgents / LaunchDaemons / Login Items / BTM
│   ├── schedule.py       # launchd agent for weekly automatic cleanup
│   ├── tweaks.py         # settings via defaults (reversible, version-gated)
│   ├── ui.py             # TUI engine (pure render functions)
│   ├── app.py            # screens and the main loop
│   └── cli.py            # subcommands for scripts and cron
└── tests/
    ├── make_fake_home.sh # test bench: a fake macOS home tree
    ├── test_all.py       # 346 checks (logic + CLI + rendering)
    ├── test_tui_pty.py   # 27 checks: the TUI in a real pty
    └── render_preview.py # renders screens to text/HTML
```

## macOS version compatibility

The tool reads the macOS version once at startup (`platform.mac_ver()`) and builds
an `OSFeatures` profile — every scanner takes ready-made paths and flags from it
instead of scattering `if/else` checks around:

| macOS | What the profile changes |
| --- | --- |
| Ventura (13) | startup items are managed through Background Task Management |
| Sonoma (14) | desktop-widget caches; Stage Manager / widget tweaks unlocked |
| Sequoia (15) | iPhone Mirroring control; stricter TCC taken into account |
| Tahoe (26) | Apple Intelligence model caches (⚠ opt-in only); APFS-snapshot check — the usual cause of the "cleaned 10 GB but Finder shows nothing" illusion |
| Golden Gate (27) | Intel is gone: Rosetta/x86 checks are skipped; extra AI-weight storages |

* **Full Disk Access is checked explicitly.** If the terminal has no FDA, the tool
  does not silently skip `~/Library/Mail` & co.: every `PermissionError` is recorded
  and the TUI/CLI prints "No permission to scan X — grant Full Disk Access" with the
  exact System Settings path.
* **APFS snapshots (key `S` / `maccc snapshots`).** Lists local snapshots via
  `tmutil listlocalsnapshots /` and offers to delete stale ones — otherwise cache
  cleaning appears to free nothing.
* **Modern space hogs, opt-in.** Ollama (`~/.ollama/models`), LM Studio, OrbStack,
  Docker Desktop VM disks and HuggingFace hub caches are found by the `dev` profile,
  marked ⚠ **dangerous**, never pre-selected, and require an explicit confirmation:
  these are model weights and container images, not caches.
* **Parallel traversal.** Directory reading and size measurement run in a
  `concurrent.futures.ThreadPoolExecutor` (standard library — still zero
  dependencies), so APFS volumes with millions of small files no longer freeze the UI.
* **Tweaks revised for macOS 14/15.** Dead `defaults write` switches were removed;
  new ones added: Stage Manager, hide desktop widgets, "click wallpaper to reveal
  desktop", disable iPhone Mirroring. Each tweak is version-gated and hidden on
  systems where it does nothing.
* **Smarter orphans.** Electron/Tauri apps often leave profiles with incomplete
  `Info.plist`: a folder in Application Support is now recognized by its structure
  (GPUCache, Local Storage, …) and marked ORPHAN when the app is gone. Group
  Containers are matched by id prefix, so `group.com.docker` is no longer a false
  orphan when `com.docker.docker` is installed.
* **Scheduled cleanup (launchd).** Menu item "9" / `maccc schedule install`
  generates `~/Library/LaunchAgents/com.dan1lazz.maccc.plist`: a weekly run of the
  basic profile, everything to Trash, no sudo, silent report in
  `~/.mac_tweaker/scheduled.log`.

## Table of contents

- [Languages: RU / EN](#languages-ru--en)
- [Quick start](#quick-start)
- [macOS version compatibility](#macos-version-compatibility)
- [Text user interface](#text-user-interface)
- [Screens](#screens)
- [CLI mode](#cli-mode-for-cron-ssh-and-scripts)
- [Safety](#safety)
- [Development and tests](#development-and-tests)
- [The .app wrapper](#the-app-wrapper-double-click-opens-a-12435-terminal)
- [Scheduled cleaning (launchd)](#scheduled-cleaning-launchd)
- [What to clean manually](#what-to-clean-manually-outside-the-tool)
- [License](#license)

## Languages: RU / EN

On the very first launch (while there is no config file) the program asks for a language:

```
Mac Crap Cleaner
Select language / Выберите язык
  1. Русский
  2. English
Select [1/2]:
```

Your choice is saved to `~/.mac_tweaker/config.json` and is not asked again. You can change the language later in three ways:

| Method | How |
|---|---|
| Key in the main menu | `l` switches between RU and EN and saves the choice |
| Flag | `maccc --lang en ...` (works for both TUI and CLI) |
| Environment variable | `MACC_LANG=en maccc` |

Everything is translated: tab headers, menus, key hints, dialogs, statuses, the help screen (a separate English text), cleanup target names, deep scan rules, orphan verdicts, startup item states, tweak names and descriptions, units (`ГБ` becomes `GB`) and durations (`1 дн. 2 ч.` becomes `1 d 2 h`). A string with no translation falls back to Russian, so nothing crashes.

Previews of both language versions: `dist/preview.html` and `dist/preview-en.html`.

## Quick start

### Option 1: single file (recommended)

Download **`dist/maccc_bundle.py`** (109 KB, all modules inside) and run it:

```bash
chmod +x maccc_bundle.py
python3 maccc_bundle.py
```

### Option 2: the whole project

```bash
cd mac_tweaker
python3 maccc.py
```

### Option 3: install into your PATH

```bash
mkdir -p ~/bin
cp dist/maccc_bundle.py ~/bin/maccc
chmod +x ~/bin/maccc
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
maccc
```

To verify the install, run `maccc --version`. Expected output: `maccc 2.1.0`.

---

## Text user interface

Running without arguments opens a full-screen TUI in your terminal:

```
 Mac Crap Cleaner                                        main menu   free 41.2 GB / 465.7 GB
────────────────────────────────────────────────────────────────────────────────────────────────────
    ███╗   ███╗ █████╗  ██████╗   ██████╗  ███╗   ███╗              MacBookAir10,1  •  macOS 15.1
    ████╗ ████║██╔══██╗██╔════╝  ██╔════╝  ████╗ ████║   Apple M2  •  cores: 8  •  RAM: 16.0 GB
    ██╔████╔██║███████║██║       ██║  ███╗ ██╔████╔██║   host: MacBook-Air.local  •  air
    ██║╚██╔╝██║██╔══██║██║       ██║   ██║ ██║╚██╔╝██║        /: 41.2 GB free of 465.7 GB
    ██║ ╚═╝ ██║██║  ██║╚██████╗  ╚██████╔╝ ██║ ╚═╝ ██║             Homebrew  •  Python 3.9.6
    ╚═╝     ╚═╝╚═╝  ╚═╝ ╚═════╝   ╚═════╝  ╚═╝     ╚═╝

  Disk: ████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  91% used

  ▸1  Cache and junk cleanup          system and user caches, logs, crash reports
   2  Deep junk scan                   .DS_Store, __pycache__, logs, crash dumps, installers
   3  Leftovers of removed apps        "orphans" in Application Support, Caches, Preferences...
   4  Startup items                    LaunchAgents/LaunchDaemons and login items
   5  System tweaks                    Finder, Dock, screenshots, privacy (reversible)
   6  Disk analysis                    what takes up space: folders and large files
   7  Journal and undo                 what was done in this and previous sessions
   8  Help                             hotkeys and safety rules
────────────────────────────────────────────────────────────────────────────────────────────────────
Up/Down select  Enter open  i system info  Esc back  ? help
```

Hotkeys:

| Key | Action |
|---|---|
| `Up` `Down` / `j` `k` | move through the list (group headers are skipped in both directions) |
| `PgUp` `PgDn` `Home` `End` | page navigation |
| `Space` | check / uncheck |
| `a` | check all / uncheck all |
| `Enter` | open, confirm, apply |
| `s` `r` | scan / refresh |
| `x` | run the action on checked items |
| `d` / `e` | disable / enable a startup item |
| `u` | undo a deletion (restore from Trash) |
| `i` `p` `Tab` `o` | filters, profile, deletion mode |
| `Esc` `q` | back / quit |
| `?` `F1` | help |

Key hints at the bottom of the screen and the key column in the help screen are shown in UPPERCASE. The case of the key you press does not matter (`S` and `s` are the same key).

The interface adapts to the terminal width, survives window resizing (`SIGWINCH`), and with `--ascii`, or in a terminal without UTF-8, falls back to plain ASCII drawing.

Long operations (disk analysis, deep scan, orphan search) run **in a background thread**. During that time the interface draws an animated progress bar made of the characters `| / - \` (a barber pole that keeps moving even when the amount of work is still unknown), and every 10 seconds the caption changes: "please wait a couple of minutes, the program has not frozen", then "looking through files", then "going through the dusty places", then "almost done searching". The interface no longer appears to hang.

---

## Screens

### 1. Cache and junk cleanup

Three depth profiles (switch with `p`):

| Profile | What it cleans |
|---|---|
| `basic` | `~/Library/Caches`, `/Library/Caches` (sudo), logs, crash reports, savedState, QuickLook/icon cache, `Caches` inside sandbox containers |
| `dev` | Everything in `basic`, plus Xcode DerivedData/Archives/DeviceSupport, simulators, CocoaPods, RubyGems, pip/poetry/mypy/pytest/ruff, npm/yarn/pnpm, Go, Cargo, Gradle/Maven, Composer, JetBrains, VS Code/Cursor, Android SDK, Unity; runs `brew cleanup`, `docker system prune`, `xcrun simctl delete unavailable`, `npm cache verify`, `pip cache purge`, `go clean -cache` |
| `aggressive` | Everything in `dev`, plus caches of Safari, Chrome, Edge, Brave, Arc, Vivaldi, Opera, Firefox, messengers, mail clients, cloud clients, Adobe |

`Tab` switches the deletion mode: **to Trash** (default, reversible) or **hard** (`rm`, with a separate red confirmation).

`i` enables an "older than N days" filter for `~/Downloads`. It only removes `.dmg`, `.pkg`, `.zip`, `.iso` and similar files and does not touch regular files.

### 2. Deep junk scan

Walks the home directory and finds what apps have scattered around:

- **Safe** (checked by default): `.DS_Store`, `._*`, `Thumbs.db`, `desktop.ini`, `__pycache__`, `*.pyc`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.tox`, `.nox`, `.coverage`, `.eslintcache`, `*.log`, `*.crash`, `*.ips`, `*.dmp`, `core.*`, `hs_err_pid*.log`
- **Ask** (checked manually only): `.dmg`/`.pkg`/`.iso`, archives, `node_modules/.cache`, `target/`, `xcuserdata`, `.venv`
- **Advice** (report only): large videos and disk images

The scanner does not descend into `node_modules`, `.git`, `.venv`, `Library` or `.Trash`. `~/Documents` and `~/Desktop` are traversed, but only `.DS_Store` files are removed from them.

### 3. Leftovers of removed apps

This is the main new feature. Third-party apps leave data in dozens of places, and this screen finds the items whose app no longer exists on disk.

**Where it looks:** `Application Support`, `Caches`, `Preferences`, `HTTPStorages`, `WebKit`, `Application Scripts`, `Containers`, `Group Containers`, `Cookies`, `Saved Application State`, `Internet Plug-Ins`, `~/.config`, `~/.cache`, `~/.local/share`, and the same categories under `/Library`.

**How it decides what is still in use:** it builds a registry of installed apps from `/Applications`, `~/Applications` and `/System/Applications` (reading `CFBundleIdentifier` from `Info.plist` via `plistlib`), then adds Spotlight results (`mdfind`, which catches apps on external volumes) and the list of running processes.

**Verdicts:**

| Verdict | Meaning | Checked by default |
|---|---|---|
| `ORPHAN` | the bundle id is not found among installed apps | **yes** |
| `outdated` | owner unknown, and not used for more than 365 days | no |
| `unclear` | an ordinary name with no match, owner unknown | no |
| `utility` | data of a CLI tool (pip, npm, brew, go...) | no |
| `system` | `com.apple.*` and macOS service folders | no |

`CURATED` (in `leftovers.py`) is a dictionary of about 200 "folder name to bundle id" mappings for popular apps: Slack, Docker, Zoom, Telegram, Spotify, Discord, Notion, Figma, Postman, Obsidian, 1Password, Chrome, Firefox, Arc, JetBrains, Adobe, Steam, Parallels, Ledger, CleanShot, and so on.

**Unknown items are never marked as junk**, so there are no false-positive deletions.

> Items under `/Library/...` are owned by root. To delete them, use the CLI with the `--sudo` flag (see below).

### 4. Startup items

Sources: `~/Library/LaunchAgents`, `/Library/LaunchAgents`, `/Library/LaunchDaemons`, Login Items (via System Events) and, optionally, macOS 13+ background items (`sfltool dumpbtm`, requires sudo).

For each item the screen shows: the label, its state, the launch command, the **developer from the code signature** (`codesign -dvv`, the `Authority=` line), the owning app, `RunAtLoad`/`KeepAlive`, and the size and modification date of the plist.

States:

| State | Meaning |
|---|---|
| `running` | has a PID in `launchctl list` |
| `loaded` | registered in launchd but not running |
| `not loaded` | the plist is in the folder but is not loaded |
| `failing` | loaded, but exited with a non-zero code |
| `broken` | **the executable is missing**: the app was removed and the entry is left behind as dead weight |
| `disabled` | disabled by this tool |

The `f` filter, "problem items only", keeps broken, failing and suspicious entries (updaters, telemetry, sync agents).

**Disabling is reversible.** The item is unloaded from launchd (`launchctl bootout` / `unload -w`) and its plist is moved to `~/.mac_tweaker/disabled/`, with the original path stored inside the file (the `MTDisabledFrom` key). "Enable" (`e`) puts the plist **back in its original location** and loads it again. System items (`/System/Library`, `com.apple.*`) are marked `[SIP]` and cannot be disabled at all.

### 5. System tweaks

45+ switches via `defaults`, grouped into sections: Finder, Screenshots, Dock, Interface, Security, Performance, Other. The state of each one is read with the same `defaults read`, so the screen shows honestly what is already enabled.

- `Enter` applies the checked tweaks
- `Backspace` returns the checked tweaks to their original state
- `x` **exports all user settings** to `~/.mac_tweaker/defaults-<date>.plist`
- `i` imports (rolls back) from the latest export

Risky tweaks are marked as such, and tweaks that require logging out tell you so.

### 6. Disk analysis

Shows the largest folders with bar indicators. `Enter` goes into a folder, `Backspace` goes up, and `b` lists files larger than 300 MB.

### 7. Journal and undo

All actions are written to `~/.mac_tweaker/journal-<date>.jsonl`. `u` restores everything deleted in the current session from the Trash, and `Backspace` restores all disabled startup items.

### 8. APFS snapshots (key `S`)

Opens from the main menu or the system info screen. Answers the Tahoe-era question "I cleaned 10 GB of caches, why is the free space the same?": local APFS snapshots hold the deleted blocks. The screen lists snapshots (`tmutil listlocalsnapshots /`) and deletes the selected ones (`d`) or all of them (`x`, requires sudo, irreversible).

### 9. Scheduled cleanup (launchd)

Generates `~/Library/LaunchAgents/com.dan1lazz.maccc.plist`: a weekly run of the chosen profile, everything to the Trash, no sudo, silent report in `~/.mac_tweaker/scheduled.log`. `w`/`h`/`p` pick the weekday, hour and profile; `Enter` installs, `d` removes the agent.

---

## CLI mode (for cron, ssh and scripts)

Global flags (`--ascii`, `--no-color`, `--no-tui`, `--home`, `--sysroot`) go **before** the subcommand.

```bash
# system and disk
python3 maccc.py info
python3 maccc.py disk --min-mb 1000

# caches
python3 maccc.py scan  --profile dev --report ~/Desktop/junk.json
python3 maccc.py clean --profile dev -y
python3 maccc.py clean --profile aggressive --older-than-days 30 --sudo -y
python3 maccc.py clean --profile basic --only "Xcode" -y
python3 maccc.py clean -y --empty-trash --hard        # permanent, bypasses Trash

# deep scan
python3 maccc.py deep --risk 0                        # safe items only
python3 maccc.py deep --clean --risk 0 -y             # and delete right away
python3 maccc.py deep --root ~/Projects --older-than-days 60

# leftovers of removed apps
python3 maccc.py orphans                              # report
python3 maccc.py orphans --include-unknown            # + unclear and outdated
python3 maccc.py orphans --clean -y                   # delete orphans
python3 maccc.py orphans --clean --sudo -y            # including /Library

# startup items
python3 maccc.py startup list
python3 maccc.py startup dead                         # entries that are dead weight
python3 maccc.py startup disable --label adobe -y
python3 maccc.py startup enable  --label adobe -y
python3 maccc.py startup restore                      # restore everything disabled
python3 maccc.py startup list --btm --sudo            # + BTM background items

# tweaks
python3 maccc.py tweaks list
python3 maccc.py tweaks apply --id finder-hidden --id shot-location -y
python3 maccc.py tweaks revert --id dock -y
python3 maccc.py tweaks export

# journal
python3 maccc.py undo --list
python3 maccc.py undo -y                              # restore from Trash

# APFS snapshots ("cleaned caches but no free space?" — this is why)
python3 maccc.py snapshots                            # list local snapshots
python3 maccc.py snapshots --delete-all --sudo -y     # delete them (irreversible)

# scheduled cleanup via launchd
python3 maccc.py schedule status
python3 maccc.py schedule install --weekday 0 --hour 4   # Sundays 04:00, basic profile
python3 maccc.py schedule install --profile dev --weekday 3 --hour 5
python3 maccc.py schedule uninstall -y

# dangerous targets (AI model weights, Docker/OrbStack VM disks) are skipped
# by default; opt in explicitly:
python3 maccc.py clean --profile dev --dangerous -y
```

Without a TTY (pipe, cron) a plain text menu is used automatically instead of the TUI.

---

## Safety

### Deletion is reversible

By default everything is moved **to the Trash**, through Finder AppleScript, or through `mv` to `~/.Trash` if Finder is unavailable. Hard deletion (`--hard` or `Tab` in the TUI) asks for a separate red confirmation. The journal `~/.mac_tweaker/journal-*.jsonl` lets you restore deleted items with a single command.

### Safeguards

`is_safe()` checks every path before deletion. **The following are never deleted:**

`~/Documents`, `~/Desktop`, `~/Pictures`, `~/Music`, `~/Movies`, `~/Public`, `~/Library/Application Support` (except cache subfolders of whitelisted apps), `~/Library/Containers`, `Group Containers`, `Keychains`, `Mail`, `Messages`, `Calendars`, `Contacts`, `Photos`, `Mobile Documents`, `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.config`, `~/.kube`, `~/.docker`, `/System`, `/usr`, `/bin`, `/sbin`, `/etc`, `/private/etc`, `/private/var/db`, `/Users/Shared`, `/Library/Keychains`, the home directory itself, `~/Library`, `/`, and all **DataVault** directories (protected by SIP/TCC: `lstat` on them returns `Operation not permitted`, and the script skips them instead of crashing).

Passwords, bookmarks, browser history, messages, licenses, projects and app settings are not touched. Scanners do not follow symbolic links.

### Startup items

System items (`/System/Library/...`, `com.apple.*`) are marked `critical`/`protected` and cannot be disabled even through the CLI. Before an item is disabled, its plist is copied to the storage with the original path preserved, so restoring puts the file exactly where it was.

### Root

The TUI does not run as root, because accidental system damage costs too much. For system objects use the `--sudo` flag, which calls `sudo` only where it cannot be avoided.

---

## Development and tests

```bash
cd mac_tweaker

# 1. create the test bench (a fake macOS tree)
bash tests/make_fake_home.sh /tmp/fake_mac

# 2. "age" the files so the age filter gets tested
python3 - <<'PY'
import os, time
old = time.time() - 730 * 86400
for p in ("/tmp/fake_mac/home/Library/Application Support/RemovedApp",
          "/tmp/fake_mac/home/.config/removedtool",
          "/tmp/fake_mac/home/Downloads/BigInstaller.dmg"):
    os.path.exists(p) and os.utime(p, (old, old))
PY

# 3. run the 346 checks
HOME=/tmp/fake_mac/home \
MACTWEAKER_HOME=/tmp/fake_mac/home \
MACTWEAKER_SYSROOT=/tmp/fake_mac/sys \
  python3 tests/test_all.py

# 4. render all screens to text and HTML (layout check)
HOME=/tmp/fake_mac/home MACTWEAKER_HOME=/tmp/fake_mac/home \
MACTWEAKER_SYSROOT=/tmp/fake_mac/sys \
  python3 tests/render_preview.py /tmp/preview --html
open /tmp/preview/preview.html

# 5. build the single-file bundle
python3 build_bundle.py && python3 dist/maccc_bundle.py --version

# 6. run the TUI in a real pseudo-terminal (27 checks)
chmod -R a+rwX /tmp/fake_mac
HOME=/tmp/fake_mac/home MACTWEAKER_HOME=/tmp/fake_mac/home \
MACTWEAKER_SYSROOT=/tmp/fake_mac/sys \
  python3 tests/test_tui_pty.py
```

`tests/test_tui_pty.py` starts the interface through `pty.fork()` and "presses" 25 keys (menu, scan, checkboxes, dialog, startup items, tweaks, leftovers, deep scan, help, exit). It verifies that the alternate screen is enabled, that color is present, that there are no tracebacks or `Operation not permitted` messages, that no frame line is wider than the terminal, and that the process exits with code 0. If the tests run in a root sandbox, the child process drops its uid to nobody on its own, because the TUI does not run as root.

In total there are 284 automated checks (257 unit + 27 pty), including checks of translation catalog completeness and rendering of both language versions. The tests cover:

- the `is_safe` and `is_traversable` safeguards
- DataVault and `Operation not permitted` handling
- deleting to Trash and restoring from it, and dry-run mode
- cleanup profiles
- the deep scan (including "does not touch node_modules and Documents")
- the app registry and all orphan classifier verdicts
- collecting, disabling and restoring startup items
- the TUI engine (line width, ANSI, truncate, ListView, Dialog)
- rendering of all 10 screens without leaving terminal bounds
- all CLI subcommands end to end

The environment variables `MACTWEAKER_HOME` and `MACTWEAKER_SYSROOT` override the home directory and the filesystem root, so the tests also work on Linux.

---

## The .app wrapper: double-click opens a 124x35 terminal

For those who do not like launching things from a terminal, there is a ready-made wrapper:

```
Mac Crap Cleaner.app/
└── Contents/
    ├── Info.plist          name, version, icon, LSUIElement (the stub is hidden from the Dock)
    ├── MacOS/
    │   └── launcher        bash: opens a 124x35 Terminal and starts the TUI
    └── Resources/
        ├── MacCC.icns      icon (ic10/ic09/ic08/ic07, packed from tools/icon_src.png)
        ├── maccc_bundle.py single-file bundle of the program
        └── run.command     fallback launcher via double click
```

Build and install:

```bash
python3 build_bundle.py && python3 build_app.py
unzip -o dist/Mac-Crap-Cleaner-app.zip -d /Applications/

# first launch: Gatekeeper may ask for confirmation
xattr -dr com.apple.quarantine '/Applications/Mac Crap Cleaner.app'
# (optional) ad-hoc signature for your own Mac
codesign --force --deep -s - '/Applications/Mac Crap Cleaner.app'
```

What happens on a double click:

1. `launcher` finds Python 3.8+ (Homebrew, then /usr/local, then the system one).
2. Through AppleScript it opens a **new 124x35 Terminal window** (Menlo 12 pt) and starts the TUI in it. When the session ends, the window waits for a key and closes.
3. If Terminal automation is not permitted, it falls back to `open -a Terminal run.command`.
4. If Python 3 is missing, a dialog suggests running `xcode-select --install`.
5. Outside macOS (ssh, Linux), the launcher runs the program directly in the current terminal.

The stub itself shows no Dock icon (`LSUIElement`), so visually only the Terminal window with the MacCC interface exists.

### Automatic window resize when started from a regular terminal

If you run `maccc_bundle.py` manually in a small window (80x24), the program tries to grow the window to 124x35 in two ways: with the escape sequence `CSI 8;35;124t` (iTerm2, kitty, alacritty), and with AppleScript via the window's tty (Terminal.app; the first time, macOS asks for automation permission). You can turn this off with `MACC_FIT=0`. If the window is still narrower than 100 columns, a hint appears in the status line.

---

## Scheduled cleaning (launchd)

Since 2.2 the agent is generated by the tool itself — in the TUI use menu item
**"9. Scheduled cleanup"** (Enter to install, `w`/`h`/`p` for weekday/hour/profile,
`d` to remove), or from the CLI:

```bash
python3 maccc.py schedule install --weekday 0 --hour 4   # Sundays at 04:00
python3 maccc.py schedule status
python3 maccc.py schedule uninstall -y
```

The generator writes `~/Library/LaunchAgents/com.dan1lazz.maccc.plist` and loads
it via `launchctl bootstrap` (falling back to `launchctl load`). By default it
runs `clean --profile basic --older-than-days 30 --no-commands -y` once a week
and writes a silent report of every run to `~/.mac_tweaker/scheduled.log`.
The schedule never uses `sudo` (no terminal for a password), never uses `--hard`
(everything goes to the Trash) and never touches "dangerous" targets (model
weights, VM disks). CPU/IO priority is lowered (`Nice`, `LowPriorityIO`,
`ProcessType=Background`) so the cleanup stays out of the way.

The manual template is still available:

```bash
cp com.user.maccrapcleaner.plist ~/Library/LaunchAgents/
# edit USERNAME in the paths, then:
launchctl load ~/Library/LaunchAgents/com.user.maccrapcleaner.plist
launchctl list | grep maccrapcleaner
tail -f ~/Library/Logs/mac_crap_cleaner.log
```

---

## What to clean manually (outside the tool)

| Location | Command |
|---|---|
| Time Machine local snapshots | `tmutil listlocalsnapshots /`, then `sudo tmutil deletelocalsnapshots <date>` |
| Old Xcode iOS runtimes | Xcode > Settings > Components |
| Docker, everything | `docker system prune -a --volumes` (this deletes volumes too!) |
| macOS installer cache | `/Applications/Install macOS *.app` |
| Mail downloads | Mail > Settings > your account |

---

## License

MIT. Before the first run, do a `scan` (effectively a dry run) and, ideally, make a Time Machine snapshot. The tool tries to be safe, but responsibility for your data remains with you.
