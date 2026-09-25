from __future__ import annotations

import pkgutil
import subprocess
import sys

import comfycapture.core


def test_core_modules_import_without_qt() -> None:
    modules = [f"comfycapture.core.{info.name}" for info in pkgutil.iter_modules(comfycapture.core.__path__)]
    script = "\n".join(
        [
            "import importlib, sys",
            f"for name in {modules!r}:",
            "    importlib.import_module(name)",
            "import comfycapture.cli",
            "assert not any(m.startswith('PySide6') for m in sys.modules), 'PySide6 leaked into core'",
        ]
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr


def test_cli_prints_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "comfycapture.cli", "--version"], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0
    assert result.stdout.startswith("comfycapture ")
