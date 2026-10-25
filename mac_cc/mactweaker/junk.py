"""
mactweaker.junk — поиск и удаление кэшей/мусора + глубокий сканер «раскиданного»
хлама по всему домашнему каталогу.

Два уровня:
  1. scan()      — известные кэш-locations по профилям basic/dev/aggressive
                   (эволюция clean_mac.py);
  2. deep_scan() — поиск мусора, который программы разбрасывают где попало:
                   .DS_Store, __pycache__, логи, краш-дампы, установщики,
                   кэши внутри проектов, осиротевшие артефакты сборки.

Удаление — только через safety.Deleter (по умолчанию в Корзину, обратимо).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .safety import (Deleter, Paths, dir_size, expand_glob, human, is_datavault,
                     is_safe, is_traversable, matches_exclude, needs_root,
                     newest_mtime, run, safe_exists, safe_isdir, safe_scandir)

PROFILES = ("basic", "dev", "aggressive")


@dataclass(frozen=True)
class JunkSpec:
    """Описание мусорного места.

    Порядок полей важен: note идёт ПЕРЕД needs_root, потому что в каталоге
    JUNK_SPECS примечание обычно передаётся пятым позиционным аргументом.
    collect_specs() дополнительно проверяет тип needs_root, чтобы перепутанные
    аргументы ломались сразу и громко, а не молча в рантайме.
    """
    category: str
    name: str
    profile: str
    patterns: Tuple[str, ...]
    note: str = ""
    needs_root: bool = False

    def resolve(self, paths: Paths) -> List[str]:
        """Подставить {home}/{lib}/{sys}/{syslib} в шаблоны."""
        subs = {
            "home": str(paths.home),
            "lib": str(paths.lib),
            "sys": str(paths.sysroot),
            "syslib": str(paths.sys_lib),
            "appsupport": str(paths.app_support),
        }
        return [p.format(**subs) for p in self.patterns]


# --------------------------------------------------------------------------- #
#  Каталог известных мусорных мест
# --------------------------------------------------------------------------- #

JUNK_SPECS: Tuple[JunkSpec, ...] = (
    # ---- basic ---------------------------------------------------------- #
    JunkSpec("Система", "Системные кэши (/Library/Caches)", "basic",
             ("{syslib}/Caches/*",),
             needs_root=True,
             note="Кэш общесистемных сервисов. Нужен пароль администратора."),
    JunkSpec("Система", "Ротированные системные логи", "basic",
             ("{sys}/private/var/log/*.gz", "{sys}/private/var/log/*.old",
              "{sys}/private/var/log/asl/*.asl"),
             needs_root=True,
             note="Сжатые/старые логи. Активные не трогаются."),
    JunkSpec("Система", "Системные отчёты об ошибках", "basic",
             ("{syslib}/Logs/DiagnosticReports/*",),
             needs_root=True,
             note="Краш-логи общесистемных процессов."),
    JunkSpec("Система", "Кэш установщиков macOS", "basic",
             ("{sys}/Library/Updates/*",),
             needs_root=True,
             note="Скачанные, но уже применённые обновления системы."),
    JunkSpec("Пользователь", "Кэши пользователя (~/Library/Caches)", "basic",
             ("{lib}/Caches/*",),
             "Главный источник мусора. Приложения пересоздадут кэш сами."),
    JunkSpec("Пользователь", "Краш-логи и отчёты приложений", "basic",
             ("{lib}/Logs/DiagnosticReports/*",),
             "Crash-репорты: полезны только для отладки."),
    JunkSpec("Пользователь", "Логи приложений (~/Library/Logs)", "basic",
             ("{lib}/Logs/*.log", "{lib}/Logs/*.old", "{lib}/Logs/*/*.log",
              "{lib}/Logs/*/*.gz"),
             "Только файлы .log/.old/.gz, не сами каталоги."),
    JunkSpec("Пользователь", "Сохранённые состояния окон", "basic",
             ("{lib}/Saved Application State/*.savedState",),
             "Списки открытых окон/вкладок. Безвредно."),
    JunkSpec("Пользователь", "Кэш QuickLook (миниатюры)", "basic",
             ("{lib}/Caches/com.apple.QuickLook.thumbnailcache",), ""),
    JunkSpec("Пользователь", "Кэш иконок и шрифтов", "basic",
             ("{lib}/Caches/com.apple.iconservices",
              "{lib}/Caches/com.apple.fontd"), ""),
    JunkSpec("Пользователь", "Кэш WebKit/HTTPStorages", "basic",
             ("{lib}/HTTPStorages/*.cookies", "{lib}/HTTPStorages/*.binarycookies"),
             "Только файлы cookies-кэша, не каталоги сессий."),
    JunkSpec("Пользователь", "Кэш контейнеров (Caches внутри Containers)", "basic",
             ("{lib}/Containers/*/Data/Library/Caches/*",),
             "Кэш песочных приложений; сами данные не трогаются."),

    # ---- dev ------------------------------------------------------------ #
    JunkSpec("Разработка", "Xcode DerivedData", "dev",
             ("{lib}/Developer/Xcode/DerivedData/*",),
             "Артефакты сборки. Первая сборка будет дольше."),
    JunkSpec("Разработка", "Xcode Archives", "dev",
             ("{lib}/Developer/Xcode/Archives/*",),
             "Архивы сборок для публикации. Удаляйте, только если не нужны!"),
    JunkSpec("Разработка", "Xcode iOS DeviceSupport", "dev",
             ("{lib}/Developer/Xcode/iOS DeviceSupport/*",
              "{lib}/Developer/Xcode/watchOS DeviceSupport/*",
              "{lib}/Developer/Xcode/tvOS DeviceSupport/*"),
             "Отладочные символы; скачаются заново при подключении устройства."),
    JunkSpec("Разработка", "Xcode UserData (кэш интерфейса)", "dev",
             ("{lib}/Developer/Xcode/UserData/IB Support/*",
              "{lib}/Developer/Xcode/UserData/FontAndColorThemes/*.cache"), ""),
    JunkSpec("Разработка", "Кэш симуляторов iOS", "dev",
             ("{lib}/Developer/CoreSimulator/Caches/*",
              "{lib}/Developer/CoreSimulator/Temp/*"), ""),
    JunkSpec("Разработка", "Кэш CocoaPods", "dev",
             ("{lib}/Caches/CocoaPods", "{home}/.cocoapods/repos/trunk"), ""),
    JunkSpec("Разработка", "Кэш RubyGems", "dev",
             ("{home}/.gem/cache", "{lib}/Caches/RubyGems"), ""),
    JunkSpec("Разработка", "Кэш Python (pip/poetry/mypy/pytest/ruff)", "dev",
             ("{lib}/Caches/pip", "{lib}/Caches/pypoetry", "{lib}/Caches/mypy",
              "{lib}/Caches/pytest", "{lib}/Caches/ruff", "{home}/.mypy_cache",
              "{home}/.pytest_cache", "{home}/.ruff_cache", "{home}/.tox"), ""),
    JunkSpec("Разработка", "Кэш Node.js (npm/yarn/pnpm)", "dev",
             ("{home}/.npm/_cacache", "{home}/.npm/_logs", "{lib}/Caches/Yarn",
              "{home}/.yarn/cache", "{lib}/pnpm/store", "{home}/.pnpm-store",
              "{home}/.node-gyp", "{home}/.electron"), ""),
    JunkSpec("Разработка", "Кэш Go", "dev",
             ("{lib}/Caches/go-build", "{home}/go/pkg/mod/cache"), ""),
    JunkSpec("Разработка", "Кэш Rust (cargo)", "dev",
             ("{home}/.cargo/registry/cache", "{home}/.cargo/registry/src",
              "{home}/.rustup/tmp"), ""),
    JunkSpec("Разработка", "Кэш Gradle / Maven", "dev",
             ("{home}/.gradle/caches", "{home}/.m2/repository"),
             "Maven-репозиторий скачается заново при сборке."),
    JunkSpec("Разработка", "Кэш PHP Composer", "dev",
             ("{lib}/Caches/composer", "{home}/.composer/cache"), ""),
    JunkSpec("Разработка", "Кэши IDE JetBrains", "dev",
             ("{lib}/Caches/JetBrains/*", "{lib}/Caches/Google/AndroidStudio*"),
             "Индексы проектов: переиндексируются при запуске (займёт время)."),
    JunkSpec("Разработка", "Кэш VS Code / Cursor", "dev",
             ("{appsupport}/Code/Cache/*", "{appsupport}/Code/CachedData/*",
              "{appsupport}/Code/CachedExtensionVSIXs/*", "{appsupport}/Code/logs/*",
              "{appsupport}/Cursor/Cache/*", "{appsupport}/Cursor/CachedData/*",
              "{appsupport}/Cursor/logs/*"),
             "Только кэш: настройки и расширения не трогаются."),
    JunkSpec("Разработка", "Кэш Android SDK / эмуляторов", "dev",
             ("{home}/.android/cache/*", "{home}/.android/avd/*.avd/snapshots/*",
              "{lib}/Caches/Google/*"), ""),
    JunkSpec("Разработка", "Кэш Unity", "dev",
             ("{lib}/Caches/Unity3D/*", "{lib}/Unity3D/cache/*"), ""),

    # ---- aggressive ----------------------------------------------------- #
    JunkSpec("Браузеры", "Safari (кэш, иконки)", "aggressive",
             ("{lib}/Caches/com.apple.Safari", "{lib}/Caches/com.apple.WebKit.*",
              "{lib}/Safari/Favicon Cache", "{lib}/Safari/Touch Icons Cache",
              "{lib}/Safari/UserMediaPermissions.plist.lock"),
             "Закройте Safari. Пароли, вкладки и история НЕ трогаются."),
    JunkSpec("Браузеры", "Google Chrome (Cache/Code Cache/GPUCache)", "aggressive",
             ("{lib}/Caches/Google/Chrome", "{appsupport}/Google/Chrome/*/Cache",
              "{appsupport}/Google/Chrome/*/Code Cache",
              "{appsupport}/Google/Chrome/*/GPUCache",
              "{appsupport}/Google/Chrome/GrShaderCache",
              "{appsupport}/Google/Chrome/ShaderCache",
              "{appsupport}/Google/Chrome/*/Service Worker/CacheStorage"),
             "Закройте Chrome. Пароли и закладки НЕ трогаются."),
    JunkSpec("Браузеры", "Edge / Brave / Arc / Vivaldi / Opera", "aggressive",
             ("{appsupport}/Microsoft Edge/*/Cache",
              "{appsupport}/Microsoft Edge/*/Code Cache",
              "{appsupport}/BraveSoftware/Brave-Browser/*/Cache",
              "{appsupport}/Arc/User Data/*/Cache",
              "{appsupport}/Vivaldi/*/Cache",
              "{appsupport}/com.operasoftware.Opera/Cache"), ""),
    JunkSpec("Браузеры", "Firefox (cache2, shader-cache)", "aggressive",
             ("{lib}/Caches/Firefox/*", "{lib}/Caches/org.mozilla.firefox/*",
              "{lib}/Caches/Mozilla/Firefox/*"), ""),
    JunkSpec("Приложения", "Кэш мессенджеров, почты, музыки", "aggressive",
             ("{lib}/Caches/com.tinyspeck.slackmacgap",
              "{lib}/Caches/com.microsoft.teams*", "{lib}/Caches/com.spotify.client",
              "{lib}/Caches/ru.keepcoder.Telegram",
              "{lib}/Caches/org.telegram.desktop",
              "{lib}/Caches/com.apple.Mail", "{lib}/Caches/com.microsoft.Outlook",
              "{lib}/Caches/com.discordapp.*", "{lib}/Caches/notion.id"), ""),
    JunkSpec("Приложения", "Кэш облачных клиентов", "aggressive",
             ("{home}/.dropbox/cache", "{lib}/Caches/com.getdropbox.dropbox",
              "{lib}/Caches/com.google.GoogleDrive*",
              "{lib}/Caches/com.apple.CloudDocs.*"), ""),
    JunkSpec("Приложения", "Кэш Adobe / офисных пакетов", "aggressive",
             ("{lib}/Caches/com.adobe.*", "{lib}/Caches/com.microsoft.*"),
             "Только кэш-каталоги, не лицензии и не настройки."),
)

#: Внешние команды-очистки (вызываются вместо удаления файлов).
COMMAND_SPECS: Tuple[Tuple[str, str, str, Tuple[str, ...], str], ...] = (
    ("dev", "Разработка", "Homebrew cleanup", ("brew", "cleanup", "--prune=all", "-s"),
     "Удаляет старые версии формул и кэш загрузок."),
    ("dev", "Разработка", "Docker: висячие образы и кэш сборки",
     ("docker", "system", "prune", "-f"),
     "Остановленные контейнеры, dangling-образы, сети, build cache."),
    ("dev", "Разработка", "Недоступные симуляторы iOS",
     ("xcrun", "simctl", "delete", "unavailable"),
     "Симуляторы для удалённых версий runtime."),
    ("dev", "Разработка", "npm cache verify", ("npm", "cache", "verify"),
     "Проверка и уплотнение кэша npm."),
    ("dev", "Разработка", "pip cache purge", ("pip3", "cache", "purge"), ""),
    ("dev", "Разработка", "Go: очистка кэша сборки", ("go", "clean", "-cache"), ""),
)


# --------------------------------------------------------------------------- #
#  Модель
# --------------------------------------------------------------------------- #

@dataclass
class JunkTarget:
    category: str
    name: str
    profile: str
    note: str = ""
    paths: List[Path] = field(default_factory=list)
    size: int = 0
    files: int = 0
    mtime: float = 0.0
    root_required: bool = False
    selected: bool = True
    kind: str = "paths"                       # paths | command | downloads | trash
    command: Optional[Tuple[str, ...]] = None

    @property
    def age_days(self) -> float:
        return (time.time() - self.mtime) / 86400.0 if self.mtime else 0.0

    def preview(self, paths: Paths, limit: int = 3) -> str:
        shown = [paths.short(p) for p in self.paths[:limit]]
        extra = len(self.paths) - limit
        if extra > 0:
            shown.append(f"… ещё {extra}")
        return ", ".join(shown)


# --------------------------------------------------------------------------- #
#  Сбор и сканирование
# --------------------------------------------------------------------------- #

def collect_specs(profile: str = "basic") -> List[JunkSpec]:
    idx = PROFILES.index(profile)
    out = []
    for s in JUNK_SPECS:
        # страховка от перепутанных позиционных аргументов в JUNK_SPECS
        if not isinstance(s.needs_root, bool):
            raise TypeError(
                f"JunkSpec({s.name!r}): needs_root должно быть bool, "
                f"получено {type(s.needs_root).__name__} — проверьте порядок "
                f"аргументов (category, name, profile, patterns, note, needs_root)")
        if PROFILES.index(s.profile) <= idx:
            out.append(s)
    return out


def scan_junk(paths: Paths,
              profile: str = "basic",
              older_than_days: Optional[float] = None,
              include_dirs: Sequence[str] = (),
              excludes: Sequence[str] = (),
              with_commands: bool = True,
              progress=None) -> List[JunkTarget]:
    """Найти и измерить все цели. progress(done, total, label) — опционально."""
    targets: List[JunkTarget] = []
    specs = collect_specs(profile)
    total_steps = len(specs) + 2

    for i, spec in enumerate(specs):
        if progress:
            progress(i, total_steps, spec.name)
        found: List[Path] = []
        for pat in spec.resolve(paths):
            found.extend(expand_glob(pat, paths, excludes))
        found = sorted(set(found), key=lambda p: str(p).lower())
        if not found:
            continue
        targets.append(JunkTarget(
            category=spec.category,
            name=spec.name,
            profile=spec.profile,
            note=spec.note,
            paths=found,
            root_required=bool(spec.needs_root)))

    # старые установщики в ~/Downloads
    if older_than_days is not None:
        cutoff = time.time() - older_than_days * 86400
        items = scan_downloads(paths, cutoff, excludes)
        if items:
            targets.append(JunkTarget(
                category="Пользователь", name="Старые установщики в ~/Downloads",
                profile="basic", kind="downloads",
                note=f"Файлы .dmg/.pkg/.zip и т.п. старше {older_than_days:g} дн.",
                paths=items))

    # пользовательские каталоги
    for d in include_dirs:
        p = Path(os.path.expanduser(d))
        if safe_exists(p) and is_safe(p, paths):
            targets.append(JunkTarget(category="Своё", name=f"Каталог {p.name}",
                                      profile="basic", paths=[p],
                                      note="Добавлен через --include-dir"))

    # внешние команды
    if with_commands:
        idx = PROFILES.index(profile)
        for prof, cat, name, cmd, note in COMMAND_SPECS:
            if PROFILES.index(prof) > idx:
                continue
            if not _command_available(paths, cmd):
                continue
            targets.append(JunkTarget(category=cat, name=name, profile=prof,
                                      note=note, kind="command",
                                      command=cmd, size=0))

    # измерить размеры
    for i, t in enumerate(targets):
        if progress:
            progress(len(specs) + (1 if i % 2 else 0), total_steps, t.name)
        if t.kind == "command":
            continue
        size = files = 0
        mt = 0.0
        live: List[Path] = []
        for p in t.paths:
            if not safe_exists(p):
                continue
            s, c = dir_size(p)
            size += s
            files += c
            m = newest_mtime(p) if t.kind == "downloads" else 0.0
            mt = max(mt, m)
            live.append(p)
        t.paths, t.size, t.files, t.mtime = live, size, files, mt
        if any(needs_root(p) for p in live):
            t.root_required = True

    if progress:
        progress(total_steps, total_steps, "")
    return [t for t in targets if t.size > 0 or t.kind == "command"]


def _command_available(paths: Paths, cmd: Tuple[str, ...]) -> bool:
    from .safety import have
    exe = cmd[0]
    if not have(exe):
        # brew/docker могут лежать вне PATH агента
        for cand in ("/opt/homebrew/bin", "/usr/local/bin"):
            if safe_exists(Path(cand) / exe):
                return True
        return False
    if exe == "docker":
        return run(["docker", "info"], timeout=25)[0] == 0
    if exe == "xcrun":
        return safe_isdir(paths.lib / "Developer" / "CoreSimulator" / "Devices")
    return True


DOWNLOAD_EXT = {
    ".dmg", ".pkg", ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
    ".iso", ".download", ".crdownload", ".part", ".mp4", ".mov", ".avi",
    ".mkv", ".deb", ".rpm", ".apk", ".ipa", ".torrent", ".pkgpart",
}


def scan_downloads(paths: Paths, cutoff: float,
                   excludes: Sequence[str] = ()) -> List[Path]:
    out: List[Path] = []
    dl = paths.downloads
    if not safe_isdir(dl):
        return out
    for e in safe_scandir(dl):
        try:
            p = Path(e.path)
            if e.is_symlink() or e.is_dir(follow_symlinks=False):
                continue
            if p.suffix.lower() not in DOWNLOAD_EXT:
                continue
            st = e.stat(follow_symlinks=False)
            if st.st_mtime > cutoff:
                continue
            if matches_exclude(p, excludes):
                continue
            out.append(p)
        except OSError:
            continue
    return sorted(out)


# --------------------------------------------------------------------------- #
#  Глубокий сканер «раскиданного» хлама
# --------------------------------------------------------------------------- #

#: 0 — безопасно удалять, 1 — скорее мусор, но лучше спросить, 2 — только совет
RISK_SAFE, RISK_ASK, RISK_ADVICE = 0, 1, 2

RISK_LABEL = {RISK_SAFE: "безопасно", RISK_ASK: "спросить", RISK_ADVICE: "совет"}

#: Правила по ИМЕНИ файла/каталога: (категория, риск, правило, описание, имена)
NAME_RULES: Tuple[Tuple[str, int, str, str, Tuple[str, ...]], ...] = (
    ("Системный мусор", RISK_SAFE, "Finder .DS_Store",
     "Служебные файлы Finder: пересоздаются автоматически",
     (".DS_Store", ".DS_Store?", "._.DS_Store")),
    ("Системный мусор", RISK_SAFE, "Метаданные AppleDouble",
     "Файлы ._* после копирования с не-Mac томов", ("._*",)),
    ("Системный мусор", RISK_SAFE, "Thumbs.db / desktop.ini",
     "Следы Windows-разделов", ("Thumbs.db", "desktop.ini")),
    ("Сборка", RISK_SAFE, "__pycache__ / *.pyc",
     "Байткод Python: пересоздаётся при импорте",
     ("__pycache__", "*.pyc", "*.pyo")),
    ("Сборка", RISK_SAFE, "Кэши линтеров и тестов",
     "Пересоздаются при следующем запуске",
     (".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".nox",
      ".coverage", ".eslintcache", ".stylelintcache", ".parcel-cache",
      ".turbo", ".svelte-kit", ".nuxt", ".vite")),
    ("Логи", RISK_SAFE, "Файлы логов",
     "Журналы внутри домашнего каталога",
     ("*.log", "*.log.[0-9]", "*.log.gz", "*.old.log", "npm-debug.log*",
      "yarn-error.log*", "yarn-debug.log*", "*.tlog")),
    ("Логи", RISK_SAFE, "Краш-дампы",
     "Отчёты о падениях: нужны только для отладки",
     ("*.crash", "*.ips", "*.stackshot", "*.hang", "core.[0-9]*",
      "*.dmp", "hs_err_pid*.log", "*.spin", "*.wakeups_resource")),
    ("Установщики", RISK_ASK, "Установщики и образы дисков",
     ".dmg/.pkg/.iso — после установки обычно не нужны",
     ("*.dmg", "*.pkg", "*.iso", "*.mpkg")),
    ("Архивы", RISK_ASK, "Старые архивы",
     ".zip/.rar/.7z/.tar — проверьте, распакованы ли они",
     ("*.zip", "*.rar", "*.7z", "*.tar", "*.tar.gz", "*.tgz")),
    ("Медиа", RISK_ADVICE, "Крупные видео и образы",
     "Только отчёт: решайте сами",
     ("*.mov", "*.mp4", "*.avi", "*.mkv", "*.vmwarevm", "*.sparsebundle",
      "*.sparseimage", "*.dmg.zip")),
)

#: Правила, которым нужен КОНТЕКСТ: (категория, риск, правило, описание,
#: суффикс относительного пути, маркер-родитель)
CONTEXT_RULES: Tuple[Tuple[str, int, str, str, str, str], ...] = (
    ("Сборка", RISK_ASK, "Кэш сборщика внутри node_modules",
     "Кэш webpack/babel/vite — не сами зависимости",
     ".cache", "node_modules"),
    ("Сборка", RISK_ASK, "Артефакты сборки Maven/Gradle",
     "target/ и build/ пересоберутся, но сборка займёт время",
     "target", ""),
    ("Сборка", RISK_ASK, "Кэш сборки Xcode в проекте",
     "xcuserdata и промежуточные данные",
     "xcuserdata", ""),
    ("Разработка", RISK_ASK, "Виртуальное окружение (.venv/venv)",
     "Удаляйте, только если проект больше не нужен",
     ".venv", ""),
)

#: Каталоги-артефакты: учитываем целиком и внутрь не спускаемся.
DIR_RULE_NAMES = frozenset({
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".nox",
    ".coverage", ".eslintcache", ".stylelintcache", ".parcel-cache", ".turbo",
    ".svelte-kit", ".nuxt", ".vite", ".cache",
})

#: Каталоги, внутрь которых глубокий сканер не заходит.
DEEP_SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", ".env", ".terraform",
    "Pods", ".idea", ".vscode", "Photos Library.photoslibrary",
    ".MusicBrainz", "iTunes Media", ".npm", ".gradle", ".m2", ".cargo",
    ".rustup", "go", ".docker", ".kube", ".android", "Applications",
    ".orbstack", ".colima", ".lima", "site-packages", ".Trash",
})

#: Отдельный точечный проход: что безопасно вычистить из защищённых каталогов.
DESKTOP_SAFE_NAMES = (".DS_Store", "Thumbs.db", "desktop.ini")


@dataclass
class DeepItem:
    path: Path
    category: str
    rule: str
    note: str
    risk: int
    size: int = 0
    files: int = 1
    mtime: float = 0.0
    selected: bool = False

    @property
    def age_days(self) -> float:
        return (time.time() - self.mtime) / 86400.0 if self.mtime else 0.0


def fnmatch_name(name: str, pattern: str) -> bool:
    import fnmatch as _fm
    if not any(ch in pattern for ch in "*?["):
        return name == pattern
    return _fm.fnmatch(name, pattern)


def _index_rules(risk_max: int):
    """Индексы правил: точные имена и glob-шаблоны."""
    exact: Dict[str, Tuple[str, int, str, str]] = {}
    globs: List[Tuple[str, str, int, str, str]] = []
    for cat, risk, rule, note, names in NAME_RULES:
        if risk > risk_max:
            continue
        for n in names:
            if any(ch in n for ch in "*?["):
                globs.append((n, n.lower(), cat, risk, rule, note))
            else:
                exact[n] = (cat, risk, rule, note)
                exact[n.lower()] = (cat, risk, rule, note)
    return exact, globs


def _match_context(rel: str, name: str, risk_max: int):
    for cat, risk, rule, note, suffix, parent in CONTEXT_RULES:
        if risk > risk_max:
            continue
        if name != suffix and not rel.endswith("/" + suffix):
            continue
        if parent and parent not in rel:
            continue
        if not parent and "/" not in rel:
            continue          # контекстные правила не работают в корне дома
        return (cat, risk, rule, note)
    return None


def _add(items: List[DeepItem], p: Path, match, min_size: int,
         cutoff: Optional[float], is_file: bool = False) -> None:
    cat, risk, rule, note = match
    size, files = (_size_of(p), 1) if is_file else dir_size(p)
    if size < min_size:
        return
    mt = _mtime_of(p) if is_file else newest_mtime(p)
    if cutoff is not None and mt > cutoff and rule != "Finder .DS_Store":
        return
    items.append(DeepItem(path=p, category=cat, rule=rule, note=note,
                          risk=risk, size=size, files=files, mtime=mt,
                          selected=(risk == RISK_SAFE)))


def _size_of(p: Path) -> int:
    from .safety import safe_lstat
    st = safe_lstat(p)
    return st.st_size if st else 0


def _mtime_of(p: Path) -> float:
    from .safety import safe_lstat
    st = safe_lstat(p)
    return st.st_mtime if st else 0.0


def deep_scan(paths: Paths,
              roots: Sequence[Path] = (),
              max_depth: int = 6,
              min_size: int = 1,
              older_than_days: Optional[float] = None,
              risk_max: int = RISK_ASK,
              excludes: Sequence[str] = (),
              progress=None) -> List[DeepItem]:
    """Обойти домашний каталог и найти «раскиданный» хлам."""
    roots = [Path(r) for r in roots] or [paths.home]
    cutoff = time.time() - older_than_days * 86400 if older_than_days else None
    exact, globs = _index_rules(risk_max)

    items: List[DeepItem] = []
    seen: Set[str] = set()
    visited = 0
    home_s = str(paths.home)

    stack: List[Tuple[Path, int]] = [(r, 0) for r in roots]
    while stack:
        cur, depth = stack.pop()
        if depth > max_depth:
            continue
        if progress and visited % 64 == 0:
            progress(visited, 0, paths.short(cur))
        for e in safe_scandir(cur):
            visited += 1
            name = e.name
            p = Path(e.path)
            if e.path in seen or is_datavault(p) or matches_exclude(p, excludes):
                continue
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            rel = e.path[len(home_s):].lstrip("/") if e.path.startswith(home_s) \
                else e.path

            if is_dir:
                if name in DEEP_SKIP_DIRS or not is_traversable(p, paths):
                    continue
                seen.add(e.path)
                match = exact.get(name) or exact.get(name.lower())
                if match and name in DIR_RULE_NAMES:
                    _add(items, p, match, min_size, cutoff)
                    continue
                ctx = _match_context(rel, name, risk_max)
                if ctx:
                    _add(items, p, ctx, min_size, cutoff)
                    continue
                if depth < max_depth:
                    stack.append((p, depth + 1))
                continue

            seen.add(e.path)
            match = exact.get(name) or exact.get(name.lower())
            if not match:
                for pat, patlow, cat, risk, rule, note in globs:
                    if fnmatch_name(name, pat) or fnmatch_name(name.lower(), patlow):
                        match = (cat, risk, rule, note)
                        break
            if not match:
                match = _match_context(rel, name, risk_max)
            if match:
                _add(items, p, match, min_size, cutoff, is_file=True)

    items.extend(_desktop_safe_scan(paths, excludes))

    if progress:
        progress(visited, visited, "")
    items.sort(key=lambda it: (-it.size, str(it.path)))
    return items


def _desktop_safe_scan(paths: Paths,
                       excludes: Sequence[str] = ()) -> List[DeepItem]:
    """Точечно: .DS_Store и подобные в защищённых Desktop/Documents."""
    out: List[DeepItem] = []
    for root in (paths.home / "Desktop", paths.home / "Documents"):
        for e in safe_scandir(root):
            p = Path(e.path)
            if e.name not in DESKTOP_SAFE_NAMES or matches_exclude(p, excludes):
                continue
            _add(out, p, ("Системный мусор", RISK_SAFE, "Finder .DS_Store",
                          "Служебные файлы Finder в защищённом каталоге"),
                 1, None, is_file=not safe_isdir(p))
    return out




# --------------------------------------------------------------------------- #
#  Корзина и служебные действия
# --------------------------------------------------------------------------- #

def trash_size(paths: Paths) -> int:
    """Размер Корзины пользователя и корзин внешних томов."""
    import glob as _glob
    total = 0
    candidates = [str(paths.trash)]
    candidates += _glob.glob(str(paths.sysroot / "Volumes" / "*" / ".Trashes" / "*"))
    for raw in candidates:
        total += dir_size(Path(raw))[0]
    return total


def empty_trash(paths: Paths, deleter: Optional[Deleter] = None) -> Tuple[int, bool]:
    """Очистить Корзину. Возвращает (освобождено, успех)."""
    before = trash_size(paths)
    code, _ = run(["osascript", "-e", 'tell application "Finder" to empty trash'],
                  timeout=300)
    if code == 0:
        return before, True
    t = paths.trash
    failed = 0
    for e in safe_scandir(t):
        p = Path(e.path)
        try:
            if p.is_symlink() or p.is_file():
                p.unlink()
            else:
                shutil_rmtree(p, deleter)
        except OSError:
            failed += 1
    return before, failed == 0


def shutil_rmtree(p: Path, deleter: Optional[Deleter]) -> None:
    import shutil
    shutil.rmtree(p, ignore_errors=True)


def purge_dns(use_sudo: bool = True) -> bool:
    prefix = ["sudo", "-n"] if use_sudo else []
    c1, _ = run(prefix + ["dscacheutil", "-flushcache"])
    c2, _ = run(prefix + ["killall", "-HUP", "mDNSResponder"])
    return c1 == 0 and c2 == 0


def rebuild_launch_services() -> bool:
    lsregister = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/"
                  "LaunchServices.framework/Support/lsregister")
    code, _ = run([lsregister, "-kill", "-r", "-domain", "local",
                   "-domain", "system", "-domain", "user"])
    return code == 0


def clean_targets(targets: Sequence[JunkTarget], deleter: Deleter,
                  progress=None) -> Tuple[int, int, int]:
    """Выполнить очистку. Возвращает (освобождено, ошибок, пропущено)."""
    freed = errors = skipped = 0
    sel = [t for t in targets if t.selected]
    for i, t in enumerate(sel):
        if progress:
            progress(i, len(sel), t.name)
        if t.kind == "command" and t.command:
            code, out = run(t.command, timeout=1800)
            if code == 0:
                freed += 0
            else:
                errors += 1
            continue
        usable = [p for p in t.paths if not (t.root_required and not deleter.use_sudo)]
        if t.root_required and not deleter.use_sudo:
            skipped += len(t.paths)
            continue
        f, failed = deleter.delete(usable)
        freed += f
        skipped += len(failed)
    if progress:
        progress(len(sel), len(sel), "")
    return freed, errors, skipped


def group_by_category(targets: Iterable[JunkTarget]) -> Dict[str, List[JunkTarget]]:
    out: Dict[str, List[JunkTarget]] = {}
    for t in targets:
        out.setdefault(t.category, []).append(t)
    for v in out.values():
        v.sort(key=lambda x: -x.size)
    return out


def size_of_paths(ps: Iterable[Path]) -> Tuple[int, int]:
    size = files = 0
    for p in ps:
        s, c = dir_size(p)
        size += s
        files += c
    return size, files
