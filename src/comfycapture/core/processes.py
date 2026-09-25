from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Sequence

CORE_FLAG = "--core"
CORE_MODULES = frozenset(
    {"comfycapture.cli", "comfycapture.core.health", "comfycapture.core.session", "comfycapture.core.verify"}
)


def configure_browsers() -> None:
    if not getattr(sys, "frozen", False):
        return
    from comfycapture.core.db import data_dir

    browsers = data_dir() / "browsers"
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers))


def core_command(module: str, *arguments: str) -> list[str]:
    if module not in CORE_MODULES:
        raise ValueError(f"Not a core subprocess module: {module}")
    if getattr(sys, "frozen", False):
        return [sys.executable, CORE_FLAG, module, *arguments]
    return [sys.executable, "-m", module, *arguments]


def driver_command(*arguments: str) -> list[str]:
    from playwright._impl._driver import compute_driver_executable

    driver = compute_driver_executable()
    executable = [str(part) for part in driver] if isinstance(driver, tuple) else [str(driver)]
    return [*executable, *arguments]


def browser_install_command() -> list[str]:
    return driver_command("install", "chromium")


def show_trace_command(trace: str) -> list[str]:
    return driver_command("show-trace", trace)


def restore_standard_streams() -> None:
    for name, descriptor, mode in (("stdin", 0, "r"), ("stdout", 1, "w"), ("stderr", 2, "w")):
        if getattr(sys, name) is not None:
            continue
        try:
            setattr(sys, name, os.fdopen(descriptor, mode, encoding="utf-8", closefd=False))
        except OSError:
            continue


def dispatch(argv: Sequence[str]) -> int | None:
    configure_browsers()
    if len(argv) < 2 or argv[0] != CORE_FLAG or argv[1] not in CORE_MODULES:
        return None
    restore_standard_streams()
    module = importlib.import_module(argv[1])
    return int(module.main(list(argv[2:])))
