from __future__ import annotations

from importlib import resources

from PySide6.QtCore import QLocale, QSettings, QTranslator
from PySide6.QtWidgets import QApplication

LANGUAGES = ("en", "nl")
LANGUAGE_KEY = "ui/language"


def preferred_language() -> str:
    override = QSettings().value(LANGUAGE_KEY, "", str)
    if override in LANGUAGES:
        return override
    system = QLocale.system().name().split("_")[0]
    return system if system in LANGUAGES else "en"


def install_translator(application: QApplication) -> QTranslator | None:
    language = preferred_language()
    if language == "en":
        return None
    translation = resources.files("browsertests.ui").joinpath("i18n", f"browsertests_{language}.qm")
    if not translation.is_file():
        return None
    translator = QTranslator(application)
    if not translator.load(str(translation)):
        return None
    application.installTranslator(translator)
    return translator
