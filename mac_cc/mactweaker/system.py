"""
mactweaker.system — сведения о системе: ОС, диск, память, аптайм, права.
"""

from __future__ import annotations

import os
import platform
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .i18n import tr
from .safety import Paths, human, run, sudo_ok


@dataclass
class DiskInfo:
    path: str
    total: int = 0
    used: int = 0
    free: int = 0

    @property
    def percent(self) -> float:
        return (self.used / self.total * 100.0) if self.total else 0.0


@dataclass
class SystemInfo:
    hostname: str = ""
    user: str = ""
    os_name: str = ""
    os_version: str = ""
    build: str = ""
    kernel: str = ""
    arch: str = ""
    model: str = ""
    cpu: str = ""
    cores: int = 0
    ram_total: int = 0
    ram_free: int = 0
    uptime: float = 0.0
    python: str = ""
    is_darwin: bool = False
    has_sudo: bool = False
    homebrew: bool = False
    xcode_cli: bool = False
    full_disk_access: Optional[bool] = None   # None — не macOS/не определили
    disks: List[DiskInfo] = field(default_factory=list)

    @property
    def macos_major(self) -> int:
        try:
            return int(self.os_version.split(".")[0])
        except (ValueError, IndexError, AttributeError):
            return 0

    @property
    def cpu_short(self) -> str:
        """«Intel(R) Core(TM) i5-8210Y CPU @ 1.60GHz» → «i5-8210Y, 1.60GHz»."""
        import re
        cpu = self.cpu or self.arch
        cpu = re.sub(r"\((?:R|TM|C)\)", "", cpu)
        cpu = re.sub(r"\bIntel\b", "", cpu)
        cpu = re.sub(r"\bCore\b", "", cpu)
        cpu = re.sub(r"\bCPU\s*@?\s*", "", cpu)
        cpu = re.sub(r"\s{2,}", " ", cpu).strip(" ,")
        return cpu or self.arch

    def summary_lines(self) -> List[str]:
        lines = [
            f"{self.model or platform.machine()}  •  {self.os_name} {self.os_version}"
            + (f" ({self.build})" if self.build else ""),
            tr("ядер: {n}  •  RAM: {total}, свободно {free}").format(
                n=self.cores, total=human(self.ram_total),
                free=human(self.ram_free)).join([f"{self.cpu_short}  •  ", ""]),
            tr("хост: {host}  •  {user}  •  аптайм: {up}").format(
                host=self.hostname, user=self.user,
                up=fmt_uptime(self.uptime)),
        ]
        for d in self.disks:
            lines.append(tr("{path}: свободно {free} из {total} ({pct}%)").format(
                path=d.path, free=human(d.free), total=human(d.total),
                pct=f"{100 - d.percent:.0f}"))
        extras = []
        if self.has_sudo:
            extras.append(tr("sudo: активен"))
        if self.homebrew:
            extras.append("Homebrew")
        if self.xcode_cli:
            extras.append("Xcode CLT")
        extras.append(f"Python {self.python}")
        lines.append("  •  ".join(extras))
        if self.full_disk_access is False:
            lines.append(tr("⚠ нет Full Disk Access: защищённые каталоги "
                            "(Mail, Messages…) будут пропущены"))
        return lines


def fmt_uptime(sec: float) -> str:
    sec = int(sec)
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if d:
        return tr("{d} дн. {h} ч.").format(d=d, h=h)
    if h:
        return tr("{h} ч. {m} мин.").format(h=h, m=m)
    return tr("{m} мин.").format(m=m)


def disk_usage(path: str = "/") -> DiskInfo:
    try:
        st = os.statvfs(path)
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        return DiskInfo(path=path, total=total, used=total - free, free=free)
    except OSError:
        return DiskInfo(path=path)


def _sysctl(key: str, cast=int, default=0):
    code, out = run(["sysctl", "-n", key], timeout=15)
    if code or not out:
        return default
    try:
        return cast(out.strip())
    except (ValueError, TypeError):
        return default


def _memory(paths: Paths) -> Tuple[int, int]:
    total = _sysctl("hw.memsize", int, 0)
    if not total:
        try:
            total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        except (ValueError, OSError, AttributeError):
            total = 0
    free = 0
    code, out = run(["vm_stat"], timeout=15)
    if code == 0:
        pages = 0
        page_size = 4096
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("page size of"):
                try:
                    page_size = int(line.split()[3])
                except (IndexError, ValueError):
                    pass
            for key in ("Pages free", "Pages inactive", "Pages speculative",
                        "Pages purgeable"):
                if line.startswith(key):
                    try:
                        pages += int(line.split(":")[1].strip().rstrip("."))
                    except (IndexError, ValueError):
                        pass
        free = pages * page_size
    else:
        try:
            free = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        except (ValueError, OSError, AttributeError):
            free = 0
    return total, free


def collect(paths: Optional[Paths] = None) -> SystemInfo:
    paths = paths or Paths.detect()
    si = SystemInfo()
    si.is_darwin = os.uname().sysname == "Darwin"
    si.hostname = platform.node()
    si.user = os.environ.get("USER") or (
        run(["id", "-un"])[1] or "unknown")
    si.arch = platform.machine()
    si.kernel = platform.release()
    si.python = platform.python_version()

    if si.is_darwin:
        code, out = run(["sw_vers", "-productName"], timeout=10)
        si.os_name = out if code == 0 else "macOS"
        code, out = run(["sw_vers", "-productVersion"], timeout=10)
        si.os_version = out if code == 0 else platform.mac_ver()[0]
        code, out = run(["sw_vers", "-buildVersion"], timeout=10)
        si.build = out if code == 0 else ""
        si.model = _sysctl("hw.model", str, "")
        si.cpu = _sysctl("machdep.cpu.brand_string", str, "")
        si.cores = _sysctl("hw.ncpu", int, os.cpu_count() or 0)
        si.uptime = time.time() - _sysctl("kern.boottime", float, time.time())
        if si.uptime < 0:
            # kern.boottime отдаёт строку вида "{ sec = 1700000000, usec = 0 } ..."
            code, out = run(["sysctl", "-n", "kern.boottime"], timeout=10)
            si.uptime = _parse_boottime(out)
        si.xcode_cli = Path("/Library/Developer/CommandLineTools").exists()
    else:
        si.os_name = platform.system()
        si.os_version = platform.release()
        si.cores = os.cpu_count() or 0
        try:
            si.uptime = time.time() - float(open("/proc/uptime").read().split()[0])
        except OSError:
            si.uptime = 0.0

    si.ram_total, si.ram_free = _memory(paths)
    si.has_sudo = sudo_ok(non_interactive=True)
    si.homebrew = Path("/opt/homebrew/bin/brew").exists() or \
        Path("/usr/local/bin/brew").exists()
    if si.is_darwin:
        # явная проверка прав (TCC): без Full Disk Access часть каталогов
        # молча пропускается — лучше сказать об этом пользователю сразу
        from . import osprofile
        si.full_disk_access = osprofile.has_full_disk_access(paths)

    seen = set()
    for mount in (str(paths.home), "/"):
        real = os.path.realpath(mount)
        if real in seen:
            continue
        seen.add(real)
        d = disk_usage(mount)
        if d.total:
            si.disks.append(d)
    return si


def _parse_boottime(out: str) -> float:
    import re
    m = re.search(r"sec\s*=\s*(\d+)", out or "")
    if not m:
        return 0.0
    return max(0.0, time.time() - int(m.group(1)))


def top_level_sizes(root: Path, limit: int = 12,
                    progress=None) -> List[Tuple[Path, int]]:
    """Крупнейшие подкаталоги первого уровня (для экрана «Анализ диска»).

    Размеры считаются параллельно (ThreadPoolExecutor) — на APFS это
    основная по времени операция.
    """
    from concurrent.futures import ThreadPoolExecutor
    from .safety import dir_size, safe_scandir, workers
    entries = safe_scandir(Path(root))
    tasks: List[Path] = []
    sizes: List[Tuple[Path, int]] = []
    for e in entries:
        try:
            if e.is_symlink():
                continue
            tasks.append(Path(e.path))
        except OSError:
            continue

    def measure(p: Path) -> Tuple[Path, int]:
        try:
            size = dir_size(p)[0] if p.is_dir() else p.stat().st_size
        except OSError:
            size = 0
        return (p, size)

    n = max(1, min(workers(), len(tasks) or 1))
    if n == 1 or not tasks:
        for i, p in enumerate(tasks):
            if progress:
                progress(i, len(tasks), p.name)
            sizes.append(measure(p))
    else:
        with ThreadPoolExecutor(max_workers=n) as ex:
            for i, res in enumerate(ex.map(measure, tasks)):
                if progress:
                    progress(i, len(tasks), res[0].name)
                sizes.append(res)
    out = list(sizes)
    out.sort(key=lambda x: -x[1])
    return out[:limit]
