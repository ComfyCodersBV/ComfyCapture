"""Refresh the translation sources and compile them.

    uv run python packaging/update_translations.py

Runs lupdate over the UI (new strings land in the .ts as unfinished), then lrelease into the .qm the app
loads. Translate the unfinished strings in Qt Linguist (`pyside6-linguist`) and run this again.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import PySide6

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "src" / "comfycapture" / "ui"
LANGUAGES = ("nl",)


def tool(name: str) -> str:
    return str(Path(PySide6.__file__).parent / name)


def main() -> int:
    sources = sorted(str(path) for path in UI.glob("*.py"))
    for language in LANGUAGES:
        source = UI / "i18n" / f"comfycapture_{language}.ts"
        subprocess.run([tool("lupdate"), *sources, "-ts", str(source), "-no-obsolete"], check=True)
        subprocess.run([tool("lrelease"), str(source), "-qm", str(source.with_suffix(".qm"))], check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
