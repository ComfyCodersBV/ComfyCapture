from __future__ import annotations

import sys

from browsertests.core.processes import dispatch


def main() -> int:
    exit_code = dispatch(sys.argv[1:])
    if exit_code is not None:
        return exit_code

    from PySide6.QtWidgets import QApplication

    from browsertests.core import db
    from browsertests.ui.main_window import MainWindow
    from browsertests.ui.translations import install_translator

    application = QApplication(sys.argv)
    application.setApplicationName(db.APP_NAME)
    application.setOrganizationName(db.APP_AUTHOR)
    application.setDesktopFileName("nl.comfycoders.BrowserTests")
    install_translator(application)
    window = MainWindow(db.connect(db.default_database_path()))
    window.show()
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
