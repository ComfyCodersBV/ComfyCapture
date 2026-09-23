from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import platformdirs

CORE_FLAG = "--core"
CORE_MODULES = frozenset({"browsertests.core.session", "browsertests.core.verify"})


def configure_browsers() -> None:
    if not getattr(sys, "frozen", False):
        return
    browsers = Path(platformdirs.user_data_dir("BrowsertestSuite", "ComfyCoders")) / "browsers"
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers))


def core_command(module: str, *arguments: str) -> list[str]:
    if module not in CORE_MODULES:
        raise ValueError(f"Not a core subprocess module: {module}")
    if getattr(sys, "frozen", False):
        return [sys.executable, CORE_FLAG, module, *arguments]
    return [sys.executable, "-m", module, *arguments]


def browser_install_command() -> list[str]:
    from playwright._impl._driver import compute_driver_executable

    driver = compute_driver_executable()
    executable = [str(part) for part in driver] if isinstance(driver, tuple) else [str(driver)]
    return [*executable, "install", "chromium"]


def dispatch(argv: Sequence[str]) -> int | None:
    configure_browsers()
    if len(argv) < 2 or argv[0] != CORE_FLAG or argv[1] not in CORE_MODULES:
        return None
    module = importlib.import_module(argv[1])
    return int(module.main(list(argv[2:])))
