"""
Mac Crap Cleaner (MacCC) — псевдографический инструмент обслуживания macOS.

Модули:
    safety     предохранители, безопасные stat-обёртки, удаление в Корзину, журнал
    osprofile  версионированный профиль macOS: фичи ОС, пути, FDA, APFS-снапшоты
    system     сведения о системе и дисках
    junk       кэши и «раскиданный» хлам
    leftovers  остатки удалённых программ («сироты»)
    startup    автозагрузка: LaunchAgents/LaunchDaemons, Login Items, BTM
    schedule   launchd-агент еженедельной автоочистки
    tweaks     обратимые настройки через defaults
    ui         псевдографический движок (ANSI + termios, без curses)
    app        экраны и главный цикл TUI
    cli        субкоманды для запуска без интерфейса
"""

__version__ = "2.2.0"
__all__ = ["safety", "osprofile", "system", "junk", "leftovers", "startup",
           "schedule", "tweaks", "ui", "app", "cli", "__version__"]
