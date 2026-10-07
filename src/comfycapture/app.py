from __future__ import annotations

import sys

from comfycapture.core.processes import dispatch


def migrate_legacy_settings() -> None:
    from PySide6.QtCore import QSettings

    from comfycapture.core import db

    settings = QSettings()
    if settings.allKeys():
        return
    legacy = QSettings(db.APP_AUTHOR, db.LEGACY_APP_NAME)
    for key in legacy.allKeys():
        settings.setValue(key, legacy.value(key))


def main() -> int:
    exit_code = dispatch(sys.argv[1:])
    if exit_code is not None:
        return exit_code

    from PySide6.QtWidgets import QApplication

    from comfycapture.core import db
    from comfycapture.ui.icons import app_icon
    from comfycapture.ui.main_window import MainWindow
    from comfycapture.ui.theme import apply_theme, follow_system
    from comfycapture.ui.translations import install_translator

    application = QApplication(sys.argv)
    application.setApplicationName(db.APP_NAME)
    application.setOrganizationName(db.APP_AUTHOR)
    application.setDesktopFileName("nl.comfycoders.ComfyCapture")
    application.setWindowIcon(app_icon())
    migrate_legacy_settings()
    install_translator(application)
    apply_theme(application)
    follow_system(application)
    window = MainWindow(db.connect(db.default_database_path()))
    window.show_maximised()
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
