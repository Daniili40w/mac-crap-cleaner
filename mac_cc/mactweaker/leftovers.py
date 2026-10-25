"""
mactweaker.leftovers — поиск «сирот»: мусора, оставшегося от программ,
которых на Mac уже нет.

Сторонние приложения раскидывают данные по десяткам мест:
    ~/Library/Application Support/<Vendor>
    ~/Library/Caches/<bundle.id>
    ~/Library/Preferences/<bundle.id>.plist
    ~/Library/Containers/<bundle.id>
    ~/Library/Group Containers/<team>.<bundle.id>
    ~/Library/HTTPStorages, WebKit, Application Scripts, Cookies, Logs,
    ~/Library/LaunchAgents, ~/.config, ~/.cache, ~/.local/share
    /Library/... (те же категории для всех пользователей)

Алгоритм:
  1. Собираем реестр установленных приложений (bundle id + имена) из
     /Applications, ~/Applications, /System/Applications и через Spotlight
     (mdfind) — чтобы учесть программы на внешних томах.
  2. Добавляем в «живые» имена запущенных процессов и их префиксы.
  3. Для каждого элемента в перечисленных каталогах определяем владельца
     (bundle id или имя каталога) и сверяем с реестром.
  4. Вердикт: orphan (владельца нет), unknown (имя не похоже на bundle id —
     НЕ помечаем как мусор), system (com.apple.*), alive.

Никакой магии: неизвестное = не трогаем. Apple-идентификаторы помечаются
отдельно и по умолчанию не предлагаются к удалению.
"""

from __future__ import annotations

import os
import plistlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .i18n import tr
from .safety import (Paths, dir_size, human, is_datavault, matches_exclude,
                     newest_mtime, run, safe_exists, safe_isdir, safe_scandir)

VERDICT_ALIVE = "alive"        # программа установлена/запущена
VERDICT_ORPHAN = "orphan"      # владельца на диске нет → сирота
VERDICT_UNKNOWN = "unknown"    # не удалось определить владельца → не трогаем
VERDICT_SYSTEM = "system"      # компонент macOS
VERDICT_TOOL = "tool"          # данные CLI-инструмента (pip, npm, brew…)
VERDICT_STALE = "stale"        # давно не использовалось — вероятный остаток

VERDICT_LABEL = {
    VERDICT_ORPHAN: "СИРОТА",
    VERDICT_UNKNOWN: "неясно",
    VERDICT_SYSTEM: "система",
    VERDICT_ALIVE: "живое",
    VERDICT_TOOL: "утилита",
    VERDICT_STALE: "устарело",
}

BUNDLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\.[A-Za-z0-9._-]+)+$")
TEAM_GROUP_RE = re.compile(r"^[A-Z0-9]{10}\.(.+)$")

#: Имена каталогов в Application Support, которые точно не относятся к
#: сторонним программам (служебные данные macOS).
SYSTEM_SUPPORT_NAMES = frozenset({
    "com.apple.sharedfilelist", "com.apple.TCC", "AddressBook", "CallHistoryDB",
    "CallHistoryTransactions", "CloudDocs", "CloudKit", "Compositions",
    "Contacts", "CoreParse", "CoreSuggestions", "DiagnosticExtensions",
    "Family", "FrontBoard", "GameKit", "HomeKit", "IdentityService",
    "InnovativeInterfaces", "Knowledge", "Metadata", "MobileAsset",
    "MobileSync", "Notes", "Photo Booth", "Quick Look", "QuickTime",
    "Reminders", "Safari", "SafariSafeBrowsing", "SafariTechnologies",
    "ScreenReader", "Speech", "Suggestions", "SyncServices", "Translation",
    "VoiceTrigger", "Wallet", "WebpagePreviews", "iLifeMediaBrowser",
    "iPod", "iTunes", "Accounts", "Assistant", "Automator", "DVD Player",
    "Dock", "Extensions", "Fonts", "Home", "Icons", "Keyboard Layouts",
    "Keychains", "LaunchAgents", "LaunchDaemons", "Maps", "News",
    "Podcasts", "Preferences", "Screen Savers", "Services", "Sounds",
    "Spelling", "Stickies", "TV", "Trial", "Usage", "iMovie",
    "SyncServices", "GarageBand", "Logic", "MainStage",
    "CrashReporter",
})

#: Известные соответствия «имя каталога → bundle id приложения».
#: Используется, когда имя не является bundle id.
CURATED: Dict[str, Tuple[str, ...]] = {
    "slack": ("com.tinyspeck.slackmacgap",),
    "docker": ("com.docker.docker", "com.electron.docker-frontend"),
    "docker desktop": ("com.docker.docker",),
    "zoom": ("us.zoom.xos",),
    "zoomus": ("us.zoom.xos",),
    "telegram": ("ru.keepcoder.Telegram", "org.telegram.desktop",
                 "nekox.messenger", "de.ddwork.gramdesktop"),
    "telegram desktop": ("org.telegram.desktop",),
    "spotify": ("com.spotify.client",),
    "discord": ("com.hnc.Discord", "com.discordapp.Discord"),
    "notion": ("notion.id", "com.makenotion.notion"),
    "figma": ("com.figma.Desktop",),
    "postman": ("com.postmanlabs.mac",),
    "obsidian": ("md.obsidian",),
    "signal": ("org.whispersystems.signal-desktop",),
    "whatsapp": ("net.whatsapp.WhatsApp",),
    "viber": ("com.viber",),
    "skype": ("com.skype.skype",),
    "teamviewer": ("com.teamviewer.TeamViewer",),
    "anydesk": ("com.philandro.anydesk", "de.avm.anydesk"),
    "1password": ("com.agilebits.onepassword", "com.1password.1password"),
    "1password 7": ("com.agilebits.onepassword7",),
    "keepassxc": ("org.keepassxc.keepassxc",),
    "vlc": ("org.videolan.vlc",),
    "iina": ("com.colliderli.iina",),
    "the unarchiver": ("com.macpaw.site.theunarchiver",),
    "keka": ("com.aone.keka",),
    "betterzip": ("com.macitbetter.betterzip",),
    "transmission": ("org.m0k.transmission",),
    "qbittorrent": ("org.qbittorrent.qBittorrent",),
    "utorrent": ("com.bittorrent.uTorrent",),
    "chrome": ("com.google.Chrome",),
    "google": ("com.google.Chrome", "com.google.drivefs", "com.google.earth.pro"),
    "firefox": ("org.mozilla.firefox",),
    "opera": ("com.operasoftware.Opera",),
    "brave": ("com.brave.Browser",),
    "bravesoftware": ("com.brave.Browser",),
    "vivaldi": ("com.vivaldi.Vivaldi",),
    "arc": ("company.thebrowser.Browser",),
    "yandex": ("ru.yandex.desktop.yandex-browser",),
    "safari": ("com.apple.Safari",),
    "microsoft": ("com.microsoft.Word", "com.microsoft.Excel",
                  "com.microsoft.Powerpoint", "com.microsoft.Outlook",
                  "com.microsoft.teams", "com.microsoft.VSCode",
                  "com.microsoft.edgemac"),
    "teams": ("com.microsoft.teams",),
    "onedrive": ("com.microsoft.OneDrive",),
    "onedrive-finderintegration": ("com.microsoft.OneDrive",),
    "adobe": ("com.adobe.Photoshop", "com.adobe.lightroomCC",
              "com.adobe.premierepro", "com.adobe.acc.AdobeCreativeCloud"),
    "jetbrains": ("com.jetbrains.intellij", "com.jetbrains.pycharm",
                  "com.jetbrains.webstorm", "com.jetbrains.goland",
                  "com.jetbrains.rider", "com.jetbrains.AppCode",
                  "com.jetbrains.datagrip", "com.jetbrains.clion"),
    "androidstudio": ("com.google.android.studio",),
    "sublime text": ("com.sublimetext.4", "com.sublimetext.3"),
    "sublime text 3": ("com.sublimetext.3",),
    "atom": ("com.github.atom",),
    "visual studio code": ("com.microsoft.VSCode",),
    "code": ("com.microsoft.VSCode",),
    "cursor": ("com.todesktop.230313mzl4w4u92", "com.cursor.Cursor"),
    "iterm2": ("com.googlecode.iterm2",),
    "hyper": ("co.zeit.hyper",),
    "warp": ("dev.warp.Warp-Stable",),
    "kitty": ("net.kovidgoyal.kitty",),
    "alacritty": ("org.alacritty",),
    "steam": ("com.valvesoftware.steam",),
    "epic games": ("com.epicgames.EpicGamesLauncher",),
    "battle.net": ("net.battle.app",),
    "blizzard": ("net.battle.app",),
    "minecraft": ("com.mojang.minecraftlauncher", "net.minecraft.legacylauncher"),
    "obs": ("com.obsproject.obs-studio",),
    "streamlabs obs": ("com.streamlabs.obs",),
    "skitch": ("com.skitch.skitch",),
    "evernote": ("com.evernote.Evernote",),
    "dropbox": ("com.getdropbox.dropbox",),
    "google drive": ("com.google.drivefs",),
    "google backup and sync": ("com.google.GoogleDrive",),
    "onedrive updater": ("com.microsoft.OneDriveUpdater",),
    "yandex disk": ("ru.yandex.desktop.yandex-disk",),
    "mega": ("mega.privacy.mac.app",),
    "nextcloud": ("com.nextcloud.desktopclient.nextcloud",),
    "syncthing": ("com.github.xor-gate.syncthing-macosx",),
    "filezilla": ("org.filezilla-project.filezilla",),
    "cyberduck": ("ch.sudo.cyberduck",),
    "transmit": ("com.panic.Transmit",),
    "forklift": ("com.binarynights.ForkLift",),
    "cleanmymac": ("com.macpaw.CleanMyMac4", "com.macpaw.CleanMyMacX"),
    "cleanmymac x": ("com.macpaw.CleanMyMacX",),
    "mackeeper": ("com.zeobit.MacKeeper",),
    "avast": ("com.avast.security",),
    "avg": ("com.avg.antivirus",),
    "kaspersky": ("com.kaspersky.KES",),
    "malwarebytes": ("com.malwarebytes.Malwarebytes",),
    "little snitch": ("at.obdev.littlesnitch",),
    "lulu": ("com.objective-see.lulu",),
    "karabiner": ("org.pqrs.Karabiner-Elements",),
    "karabiner-elements": ("org.pqrs.Karabiner-Elements",),
    "bettertouchtool": ("com.hegenberg.BetterTouchTool",),
    "rectangle": ("com.knollsoft.Rectangle",),
    "magnet": ("com.crowdcafe.windowmagnet",),
    "alfred": ("com.runningwithcrayons.Alfred",),
    "raycast": ("com.raycast.macos",),
    "bartender": ("com.surteesstudios.Bartender",),
    "istat menus": ("com.bjango.istatmenus",),
    "appcleaner": ("net.freemacsoft.AppCleaner",),
    "the unarchiver preferences": ("com.macpaw.site.theunarchiver",),
    "wireshark": ("org.wireshark.Wireshark",),
    "charles": ("com.xk72.charles",),
    "proxyman": ("com.proxyman.NSProxy",),
    "postico": ("at.eggerapps.Postico",),
    "tableplus": ("com.tinyapp.TablePlus",),
    "dbeaver": ("com.dbeaver.products", "org.jkiss.dbeaver.core"),
    "datagrip": ("com.jetbrains.datagrip",),
    "xcode": ("com.apple.dt.Xcode",),
    "corellium": ("com.corellium.CorelliumDesktop",),
    "genymotion": ("com.genymobile.genymotion",),
    "parallels": ("com.parallels.desktop", "com.parallels.Parallels Desktop"),
    "vmware fusion": ("com.vmware.fusion",),
    "virtualbox": ("org.virtualbox.app.VirtualBox",),
    "utm": ("com.utmapp.UTM",),
    "wine": ("org.winehq.wine",),
    "crossover": ("com.codeweavers.CrossOver",),
    "gpg suite": ("org.gpgtools.gpgkeychain",),
    "gnupg": ("org.gnupg.gpgtools",),
    "homebrew": ("sh.brew",),
    "portainer": ("io.portainer.app",),
    "lens": ("com.electron.lens", "com.mirantis.lens"),
    "rancher desktop": ("io.rancherdesktop.app",),
    "podman": ("com.electron.podman",),
    "kindle": ("com.amazon.Kindle",),
    "calibre": ("net.kovidgoyal.calibre",),
    "sketch": ("com.bohemiancoding.sketch3",),
    "affinity": ("com.seriflabs.affinityphoto", "com.seriflabs.affinitydesigner"),
    "pixelmator": ("com.pixelmator.pixelmator", "com.pixelmatorteam.photomator"),
    "gimp": ("org.gimp.gimp",),
    "blender": ("org.blender.foundation.blender",),
    "audacity": ("org.audacityteam.audacity",),
    "garageband": ("com.apple.garageband10",),
    "ableton": ("com.ableton.live",),
    "fl studio": ("com.image-line.flstudio",),
    "logic pro": ("com.apple.logic10",),
    "djay": ("com.algoriddim.djay",),
    "handbrake": ("fr.handbrake.HandBrake",),
    "makemkv": ("com.makemkv.MakeMKV",),
    "plex": ("com.plexapp.plex", "com.plexapp.plexmediaserver"),
    "infuse": ("com.firecore.infuse",),
    "elgato": ("com.elgato.ControlCenter", "com.elgato.StreamDeck"),
    "logi options": ("com.logi.optionsplus", "com.logitech.logi-options"),
    "logitech": ("com.logitech.logi-options", "com.logi.optionsplus"),
    "razer synapse": ("com.razer.rzsynapse",),
    "steelseries": ("com.steelseries.gg",),
    "sonos": ("com.sonos.SonosController", "com.sonos.Sonos",),
    "bose": ("com.bose.BoseUpdater",),
    "airbuddy": ("codes.rambo.AirBuddy",),
    "clean shot": ("pl.maketheweb.cleanshotx",),
    "cleanshot x": ("pl.maketheweb.cleanshotx",),
    "shottr": ("cc.ffitch.shottr",),
    "monosnap": ("ru.monosnap.monosnap",),
    "kap": ("com.wulkano.kap",),
    "loom": ("co.loom.desktop",),
    "zoom recordings": ("us.zoom.xos",),
    "teamviewer host": ("com.teamviewer.TeamViewerHost",),
    "anytype": ("com.anytype.anytype",),
    "logseq": ("com.electron.logseq",),
    "typora": ("abnerworks.Typora",),
    "ia writer": ("pro.writer.mac",),
    "ulysses": ("com.ulyssesapp.mac",),
    "bear": ("net.shinyfrog.bear",),
    "craft": ("com.lukilabs.lukiapp",),
    "notability": ("com.gingerlabs.Notability",),
    "goodnotes": ("com.goodnotesapp.goodnotes", "com.goodnotes.goodnotes",),
    "money": ("com.jumsoft.money",),
    "coin tracker": ("com.cointracker.desktop",),
    "ledger live": ("com.ledger.live",),
    "trezor suite": ("io.trezor.TrezorSuite",),
    "exodus": ("exodus.Desktop",),
    "metamask": ("io.metamask",),
    "phantom": ("app.phantom.desktop",),
    "solflare": ("com.solflare.desktop",),
    "coinbase wallet": ("com.coinbase.wallet",),
    "binance": ("com.binance.Binance",),
    "kraken": ("com.kraken.invest.app",),
    "discord ptb": ("com.discordapp.DiscordPTB",),
    "element": ("im.riot.app",),
    "matrix": ("im.riot.app",),
    "thunderbird": ("org.mozilla.thunderbird",),
    "airmail": ("it.bloop.airmail2",),
    "spark": ("com.readdle.smartemail-Mac",),
    "edison mail": ("com.easilydo.mail",),
    "canary mail": ("com.canarymail.mac",),
    "mimestream": ("com.mimestream.Mimestream",),
    "superhuman": ("com.superhuman.electron",),
    "linear": ("com.linear.linear",),
    "jira": ("com.atlassian.jira",),
    "confluence": ("com.atlassian.confluence",),
    "trello": ("com.atlassian.trello",),
    "asana": ("com.electron.asana",),
    "monday": ("com.monday.monday",),
    "clickup": ("com.clickup.desktop",),
    "miro": ("com.electron.realtimeboard",),
    "mural": ("co.mural.mac",),
    "lucidchart": ("com.electron.lucidchart",),
    "drawio": ("com.jgraph.drawio.desktop",),
    "omnigraffle": ("com.omnigroup.OmniGraffle",),
    "omnifocus": ("com.omnigroup.OmniFocus",),
    "things": ("com.culturedcode.ThingsMac",),
    "todoist": ("com.todoist.mac",),
    "ticktick": ("com.TickTick.Mac",),
    "fantastical": ("com.flexibits.fantastical2.mac",),
    "notion calendar": ("com.cron.electron",),
    "cron": ("com.cron.electron",),
}

#: Каталоги консольных утилит: это не остатки приложений.
TOOL_NAMES = frozenset({
    "pip", "pip3", "pipx", "npm", "yarn", "pnpm", "node", "nodejs", "nvm",
    "go", "golang", "cargo", "rustup", "brew", "homebrew", "gem", "bundler",
    "composer", "maven", "gradle", "sbt", "lein", "deno", "bun", "poetry",
    "conda", "miniconda", "anaconda", "pyenv", "rbenv", "rvm", "jenv",
    "sdkman", "terraform", "ansible", "kubectl", "helm", "aws", "gcloud",
    "az", "docker", "podman", "colima", "lima", "vagrant", "git", "gh",
    "heroku", "netlify", "vercel", "firebase", "stripe", "twilio",
    "httpie", "curl", "wget", "jq", "fzf", "tmux", "zsh", "bash", "fish",
    "oh-my-zsh", "starship", "powerlevel10k", "neovim", "vim", "emacs",
    "sublime-text", "jetbrains", "python", "python3", "pycharm", "idea",
    "xcode", "cocoapods", "carthage", "swift", "swiftlint", "clang",
    "electron", "electron-builder", "yarnpkg", "corepack", "volta",
})

#: Ключевые слова, наличие которых в имени каталога говорит о «служебности».
SERVICE_HINTS = ("crashpad", "crashlytics", "preferences", "caches", "cache",
                 "logs", "updates", "updater", "installer", "tmp", "temp")


# --------------------------------------------------------------------------- #
#  Реестр установленных программ
# --------------------------------------------------------------------------- #

@dataclass
class AppInfo:
    name: str
    bundle_id: str
    path: Path
    vendor: str = ""

    @property
    def token(self) -> str:
        return self.bundle_id.lower()


class AppRegistry:
    """Что реально установлено/запущено на этом Mac."""

    def __init__(self) -> None:
        self.apps: List[AppInfo] = []
        self.bundle_ids: Set[str] = set()
        self.id_prefixes: Set[str] = set()
        self.names: Set[str] = set()
        self.vendors: Set[str] = set()
        self.name_words: Set[str] = set()
        self.processes: Set[str] = set()

    # -- построение --
    @classmethod
    def build(cls, paths: Paths, use_spotlight: bool = True,
              include_processes: bool = True) -> "AppRegistry":
        reg = cls()
        roots: List[Path] = [
            paths.sysroot / "Applications",
            paths.home / "Applications",
            paths.sysroot / "System" / "Applications",
        ]
        for r in roots:
            reg._scan_apps(r, depth=0)
        # App Wrapper'ы и helper'ы внутри /Library/Application Support
        for extra in (paths.sys_lib / "Application Support",):
            reg._scan_apps(extra, depth=0, max_depth=3)

        if use_spotlight:
            reg._from_spotlight(paths)
        if include_processes:
            reg._from_processes()

        for a in reg.apps:
            bid = a.bundle_id.lower()
            if bid:
                reg.bundle_ids.add(bid)
                parts = bid.split(".")
                # «вендор» = вторая часть id (com.google.Chrome → google).
                # Полные префиксы вроде «com»/«org» вендорами НЕ считаются:
                # иначе любой com.* выглядел бы установленным.
                if len(parts) >= 3:
                    reg.vendors.add(parts[1])
                    reg.id_prefixes.add(".".join(parts[:2]))
                elif len(parts) == 2:
                    reg.vendors.add(parts[0])
            reg.names.add(a.name.lower())
            for w in re.split(r"[^a-z0-9а-яё]+", a.name.lower()):
                if len(w) > 3:
                    reg.name_words.add(w)
        return reg

    def _scan_apps(self, root: Path, depth: int = 0, max_depth: int = 2) -> None:
        if not safe_isdir(root):
            return
        for e in safe_scandir(root):
            try:
                if e.is_symlink():
                    continue
                p = Path(e.path)
            except OSError:
                continue
            if p.suffix == ".app" and safe_isdir(p):
                info = read_bundle_info(p)
                if info:
                    self.apps.append(info)
                continue
            if depth < max_depth and safe_isdir(p) and not p.name.startswith("."):
                self._scan_apps(p, depth + 1, max_depth)

    def _from_spotlight(self, paths: Paths) -> None:
        code, out = run(["mdfind", "kMDItemContentTypeTree == 'com.apple.application'"],
                        timeout=60)
        if code != 0 or not out:
            return
        known = {str(a.path) for a in self.apps}
        for line in out.splitlines():
            line = line.strip()
            if not line.endswith(".app") or line in known:
                continue
            p = Path(line)
            info = read_bundle_info(p)
            if info:
                self.apps.append(info)
                known.add(line)

    def _from_processes(self) -> None:
        code, out = run(["ps", "-axo", "comm="], timeout=30)
        if code != 0:
            return
        for line in out.splitlines():
            name = Path(line.strip()).name.lower()
            if name:
                if name.endswith(".app"):
                    name = name[:-4]
                self.processes.add(name)

    # -- проверки --
    def has_bundle_id(self, bid: str) -> bool:
        """Точное совпадение bundle id с установленным приложением."""
        bid = (bid or "").lower().strip()
        return bool(bid) and bid in self.bundle_ids

    def has_vendor(self, bid: str) -> bool:
        """Тот же вендор, что у какого-то установленного приложения."""
        parts = (bid or "").lower().split(".")
        if len(parts) < 3:
            return False
        return parts[1] in self.vendors

    def has_name(self, name: str) -> bool:
        n = (name or "").lower().strip()
        if not n:
            return False
        if n in self.names or n in self.processes:
            return True
        key = re.sub(r"[-_. ]", "", n)
        for cand in self.names | self.processes:
            c = re.sub(r"[-_. ]", "", cand)
            if key and (key == c or (len(key) > 4 and (key in c or c in key))):
                return True
        return False

    def has_word(self, name: str) -> bool:
        n = (name or "").lower()
        return any(w in self.name_words for w in re.split(r"[^a-z0-9а-яё]+", n)
                   if len(w) > 3)


def read_bundle_info(app: Path) -> Optional[AppInfo]:
    """Прочитать CFBundleIdentifier/CFBundleName из Info.plist (binary и xml)."""
    plist = Path(app) / "Contents" / "Info.plist"
    if not safe_exists(plist):
        plist = Path(app) / "Info.plist"
    if not safe_exists(plist):
        return None
    try:
        with open(plist, "rb") as fh:
            data = plistlib.load(fh)
    except Exception:  # noqa: BLE001
        return None
    bid = str(data.get("CFBundleIdentifier") or "").strip()
    name = str(data.get("CFBundleName") or data.get("CFBundleDisplayName")
               or Path(app).stem).strip()
    vendor = ""
    if bid.count(".") >= 2:
        vendor = bid.split(".")[1].lower()
    return AppInfo(name=name, bundle_id=bid, path=Path(app), vendor=vendor)


# --------------------------------------------------------------------------- #
#  Модель находки
# --------------------------------------------------------------------------- #

@dataclass
class Leftover:
    path: Path
    source: str                 # «Application Support», «Caches», …
    owner: str                  # bundle id или имя каталога
    verdict: str                # VERDICT_*
    evidence_tpl: str = ""      # ru-шаблон причины (переводится при показе)
    evidence_args: dict = field(default_factory=dict)
    size: int = 0
    files: int = 0
    mtime: float = 0.0
    selected: bool = False
    curated: Tuple[str, ...] = ()

    @property
    def evidence(self) -> str:
        """Причина вердикта на текущем языке."""
        fmt = {k: (tr(v) if isinstance(v, str) else v)
               for k, v in self.evidence_args.items()}
        return tr(self.evidence_tpl).format(**fmt)

    @property
    def age_days(self) -> float:
        import time as _t
        return (_t.time() - self.mtime) / 86400.0 if self.mtime else 0.0


# --------------------------------------------------------------------------- #
#  Что сканируем
# --------------------------------------------------------------------------- #

def search_roots(paths: Paths) -> List[Tuple[str, Path, str]]:
    """(метка источника, каталог, тип элемента: bundleid|name)."""
    h, lib, syslib = paths.home, paths.lib, paths.sys_lib
    roots: List[Tuple[str, Path, str]] = [
        ("Application Support", paths.app_support, "name"),
        ("Caches", lib / "Caches", "bundleid"),
        ("Preferences", lib / "Preferences", "bundleid"),
        ("HTTPStorages", lib / "HTTPStorages", "bundleid"),
        ("WebKit", lib / "WebKit", "bundleid"),
        ("Application Scripts", lib / "Application Scripts", "bundleid"),
        ("Containers", lib / "Containers", "bundleid"),
        ("Group Containers", lib / "Group Containers", "team"),
        ("Cookies", lib / "Cookies", "bundleid"),
        ("Logs", lib / "Logs", "name"),
        ("Saved Application State", lib / "Saved Application State", "bundleid"),
        ("Internet Plug-Ins", lib / "Internet Plug-Ins", "name"),
        ("Preferences/ByHost", lib / "Preferences" / "ByHost", "bundleid"),
        (".config", h / ".config", "name"),
        (".cache", h / ".cache", "name"),
        (".local/share", h / ".local" / "share", "name"),
        ("/Library/App Support", syslib / "Application Support", "name"),
        ("/Library/Caches", syslib / "Caches", "bundleid"),
        ("/Library/Preferences", syslib / "Preferences", "bundleid"),
        ("/Library/Internet Plug-Ins", syslib / "Internet Plug-Ins", "name"),
        ("/Library/Logs", syslib / "Logs", "name"),
    ]
    return roots


#: Элементы, которые точно не нужно предлагать к удалению.
SKIP_NAMES = frozenset({
    "com.apple.TCC", "com.apple.sharedfilelist", "ByHost", "Mobile Documents",
    "CrashReporter", "SyncServices", "AddressBook", "CallHistoryDB",
    "DiagnosticReports", "Keychains", "UserEventScheduler",
})

#: Префиксы идентификаторов, которые считаются системными.
SYSTEM_ID_PREFIXES = (
    "com.apple.", "com.apple-", "apple.", "com.macromates.", "com.adobe.acc.",
)


def _is_system_id(bid: str) -> bool:
    b = bid.lower()
    return b.startswith(SYSTEM_ID_PREFIXES) or b.startswith("com.apple")


def _owner_of(name: str, kind: str) -> str:
    """Извлечь идентификатор владельца из имени файла/каталога."""
    base = name
    for suffix in (".savedState", ".plist", ".binarycookies", ".cookies",
                   ".lockfile", ".dat", ".json", ".log", ".dist", ".crash",
                   ".ips", ".bundle", ".prefPane", ".app", ".framework",
                   ".kext", ".dSYM", ".lproj", ".byhost"):
        if base.lower().endswith(suffix.lower()):
            base = base[: -len(suffix)]
            break
    if kind == "team":
        m = TEAM_GROUP_RE.match(base)
        if m:
            base = m.group(1)
    # Preferences/ByHost: com.foo.bar.1A2B3C.plist
    base = re.sub(r"\.[0-9A-F]{8}(-[0-9A-F]{4}){0,3}(-[0-9A-F]{12})?$", "", base,
                  flags=re.IGNORECASE)
    return base.strip()


def scan_leftovers(paths: Paths,
                   registry: Optional[AppRegistry] = None,
                   include_system: bool = False,
                   include_unknown: bool = False,
                   min_size: int = 0,
                   min_age_days: float = 0.0,
                   stale_days: float = 365.0,
                   excludes: Sequence[str] = (),
                   progress=None) -> List[Leftover]:
    """Главный сканер сирот."""
    reg = registry or AppRegistry.build(paths)
    out: List[Leftover] = []
    roots = search_roots(paths)

    for idx, (label, root, kind) in enumerate(roots):
        if progress:
            progress(idx, len(roots), label)
        if not safe_isdir(root):
            continue
        for e in safe_scandir(root):
            try:
                p = Path(e.path)
                name = e.name
            except OSError:
                continue
            if name in SKIP_NAMES or is_datavault(p) or name == ".localized":
                continue
            if matches_exclude(p, excludes):
                continue
            # сгруппировать plist-файлы предпочтений по владельцу
            if kind == "bundleid" and name.endswith(".plist") and label == "Preferences":
                owner = _owner_of(name, kind)
            else:
                owner = _owner_of(name, kind)
            if not owner:
                continue

            # логи и отдельные файлы в ~/Library/Logs — зона очистки кэшей
            if label in ("Logs", "/Library/Logs"):
                continue

            verdict, tpl, args, curated = classify(owner, name, kind, reg, paths)

            size, files = dir_size(p) if safe_isdir(p) else (_size(p), 1)
            if size < min_size:
                continue
            mt = newest_mtime(p) if safe_isdir(p) else _mtime(p)
            age = _age_days(mt)
            if min_age_days and mt and age < min_age_days:
                continue

            # «неясно», но не трогали больше года → вероятный остаток
            if verdict == VERDICT_UNKNOWN and stale_days and age >= stale_days:
                verdict = VERDICT_STALE
                tpl = "не использовалось {days} дн.; владелец не определён"
                args = {"days": int(age)}

            if verdict in (VERDICT_ALIVE, VERDICT_TOOL):
                continue
            if verdict == VERDICT_SYSTEM and not include_system:
                continue
            if verdict in (VERDICT_UNKNOWN, VERDICT_STALE) and not include_unknown:
                continue

            out.append(Leftover(
                path=p, source=label, owner=owner, verdict=verdict,
                evidence_tpl=tpl, evidence_args=args,
                size=size, files=files, mtime=mt,
                curated=curated,
                selected=(verdict == VERDICT_ORPHAN and not _is_system_id(owner)),
            ))

    if progress:
        progress(len(roots), len(roots), "")
    out.sort(key=lambda x: (-x.size, x.source, str(x.path)))
    return out


def _size(p: Path) -> int:
    from .safety import safe_lstat
    st = safe_lstat(p)
    return st.st_size if st else 0


def _mtime(p: Path) -> float:
    from .safety import safe_lstat
    st = safe_lstat(p)
    return st.st_mtime if st else 0.0


def _age_days(ts: float) -> float:
    import time as _t
    return (_t.time() - ts) / 86400.0 if ts else 0.0


def classify(owner: str, raw_name: str, kind: str, reg: AppRegistry,
             paths: Paths) -> Tuple[str, str, Tuple[str, ...]]:
    """Вердикт по владельцу. Возвращает (verdict, evidence, curated_ids)."""
    low = owner.lower()

    # 1. Apple-идентификаторы — системные компоненты
    if _is_system_id(owner):
        return VERDICT_SYSTEM, "компонент macOS", {}, ()

    # 2. Точное совпадение bundle id с установленным приложением
    if BUNDLE_ID_RE.match(owner) and reg.has_bundle_id(owner):
        return VERDICT_ALIVE, "установлено: {bid}", {"bid": owner}, ()

    # 3. Curated-соответствие имени каталога
    key = low.replace("_", " ").replace("  ", " ").strip()
    curated: Tuple[str, ...] = CURATED.get(key, ())
    if not curated:
        # «google chrome», «google drive» → пробуете по первым двум словам
        words = key.split()
        for n in (2, 1):
            if len(words) >= n:
                curated = CURATED.get(" ".join(words[:n]), ())
                if curated:
                    break
    if curated:
        for bid in curated:
            if reg.has_bundle_id(bid):
                return VERDICT_ALIVE, "установлено: {bid}", {"bid": bid}, curated
        return (VERDICT_ORPHAN, "приложение не найдено: {ids}",
                {"ids": ", ".join(curated)}, curated)

    # 4. Служебные каталоги macOS, которые не являются bundle id
    if low in SYSTEM_SUPPORT_NAMES:
        return VERDICT_SYSTEM, "служебный каталог macOS", {}, ()

    # 5. Имя совпадает с названием установленного приложения
    if reg.has_name(owner):
        return VERDICT_ALIVE, "установлено приложение «{name}»", {"name": owner}, ()

    # 6. Данные консольных утилит (не приложения — не мусор)
    if low in TOOL_NAMES or any(low.endswith("." + t) for t in TOOL_NAMES):
        return VERDICT_TOOL, "данные утилиты {name}", {"name": low}, ()

    # 7. Похоже на bundle id, но владельца нет → сирота
    if BUNDLE_ID_RE.match(owner):
        if reg.has_vendor(owner):
            vendor = low.split(".")[1]
            return (VERDICT_ALIVE,
                    "приложения вендора «{vendor}» установлены в системе",
                    {"vendor": vendor}, ())
        return (VERDICT_ORPHAN, "bundle id «{owner}» не найден среди установленных",
                {"owner": owner}, ())

    # 8. Обычное имя каталога, не bundle id
    if reg.has_word(owner):
        return (VERDICT_ALIVE, "похоже на установленное «{name}»",
                {"name": owner}, ())

    return VERDICT_UNKNOWN, "владелец не определён — не трогаем", {}, ()


def _curated_by_vendor(vendor: str) -> Iterable[str]:
    if not vendor:
        return ()
    out: Set[str] = set()
    for ids in CURATED.values():
        for bid in ids:
            parts = bid.lower().split(".")
            if len(parts) > 1 and parts[1] == vendor:
                out.add(bid)
    return out


# --------------------------------------------------------------------------- #
#  Отдельные полезные сканы
# --------------------------------------------------------------------------- #

@dataclass
class BigFile:
    path: Path
    size: int
    mtime: float = 0.0
    kind: str = ""


def big_files(paths: Paths, min_mb: int = 500, limit: int = 40,
              roots: Sequence[Path] = (), progress=None) -> List[BigFile]:
    """Крупнейшие файлы домашнего каталога — часто это забытые образы/видео."""
    roots = [Path(r) for r in roots] or [paths.home]
    found: List[BigFile] = []
    threshold = min_mb * 1024 * 1024
    visited = 0
    stack: List[Tuple[Path, int]] = [(r, 0) for r in roots]
    while stack:
        cur, depth = stack.pop()
        if depth > 8:
            continue
        for e in safe_scandir(cur):
            visited += 1
            if progress and visited % 256 == 0:
                progress(visited, 0, paths.short(cur))
            try:
                p = Path(e.path)
                if e.is_symlink():
                    continue
                if e.is_dir(follow_symlinks=False):
                    if e.name in DEEP_SKIP or is_datavault(p):
                        continue
                    stack.append((p, depth + 1))
                    continue
                st = e.stat(follow_symlinks=False)
                if st.st_size >= threshold:
                    found.append(BigFile(path=p, size=st.st_size,
                                         mtime=st.st_mtime,
                                         kind=p.suffix.lower()))
            except OSError:
                continue
    if progress:
        progress(visited, visited, "")
    found.sort(key=lambda f: -f.size)
    return found[:limit]


DEEP_SKIP = frozenset({"Library", ".Trash", "node_modules", ".git"})


def duplicate_installers(paths: Paths) -> List[Leftover]:
    """Установщики .dmg/.pkg в домашнем каталоге (не только в Downloads)."""
    out: List[Leftover] = []
    exts = (".dmg", ".pkg", ".iso", ".mpkg")
    stack: List[Tuple[Path, int]] = [(paths.home, 0)]
    while stack:
        cur, depth = stack.pop()
        if depth > 5:
            continue
        for e in safe_scandir(cur):
            try:
                p = Path(e.path)
                if e.is_symlink():
                    continue
                if e.is_dir(follow_symlinks=False):
                    if e.name in DEEP_SKIP or e.name.startswith("."):
                        continue
                    stack.append((p, depth + 1))
                    continue
                if p.suffix.lower() in exts:
                    st = e.stat(follow_symlinks=False)
                    out.append(Leftover(
                        path=p, source="Установщики", owner=p.name,
                        verdict=VERDICT_ORPHAN,
                        evidence_tpl="образ/установщик: после установки обычно не нужен",
                        size=st.st_size, files=1, mtime=st.st_mtime,
                        selected=False))
            except OSError:
                continue
    out.sort(key=lambda x: -x.size)
    return out


def group_leftovers(items: Iterable[Leftover]) -> Dict[str, List[Leftover]]:
    out: Dict[str, List[Leftover]] = defaultdict(list)
    for it in items:
        out[it.source].append(it)
    return dict(out)


def summarize(items: Sequence[Leftover]) -> Dict[str, Dict[str, int]]:
    """Статистика по вердиктам: {verdict: {count, bytes}}."""
    res: Dict[str, Dict[str, int]] = {}
    for it in items:
        d = res.setdefault(it.verdict, {"count": 0, "bytes": 0})
        d["count"] += 1
        d["bytes"] += it.size
    return res
