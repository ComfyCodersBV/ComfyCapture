from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from comfycapture import __version__
from comfycapture.core import db, exchange
from comfycapture.core.models import Project
from comfycapture.core.secrets import SecretStore
from comfycapture.ui import messages
from comfycapture.ui.dialogs import ProjectDialog
from comfycapture.ui.icons import icon, mark_pixmap
from comfycapture.ui.project_view import ProjectView
from comfycapture.ui.settings_dialog import SettingsDialog
from comfycapture.ui.theme import active_tokens, heading_font
from comfycapture.ui.widgets import IconButton

WINDOW_TITLE = "ComfyCapture {version}"


class MainWindow(QMainWindow):
    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE.format(version=__version__))
        self.resize(1280, 800)
        self.setMinimumSize(960, 600)
        self._connection = connection
        self._projects = db.ProjectRepository(connection)
        self._tests = db.TestRepository(connection)

        self.project_list = QListWidget()
        self.project_list.setObjectName("ProjectList")
        self.project_list.currentItemChanged.connect(self._on_project_selected)

        self.project_view = ProjectView(connection)
        self.project_view.edit_project_requested.connect(self._edit_project)
        self.project_view.delete_project_requested.connect(self._delete_project)
        self.project_view.new_project_requested.connect(self._new_project)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._sidebar())
        layout.addWidget(self.project_view, 1)
        self.setCentralWidget(root)
        self._load_projects()

    def show_maximised(self) -> None:
        screen = self.screen()
        if screen is not None:
            self.setGeometry(screen.availableGeometry())
        self.show()
        QTimer.singleShot(0, self.showMaximized)

    def _sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(264)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 24, 16, 24)
        layout.setSpacing(4)

        layout.addLayout(self._brand())
        layout.addSpacing(30)

        heading_row = QHBoxLayout()
        heading_row.setContentsMargins(8, 0, 0, 0)
        heading = QLabel(self.tr("PROJECTS"))
        heading.setObjectName("SidebarHeading")
        heading.setFont(heading_font(11, QFont.Weight.Bold, 14))
        heading_row.addWidget(heading)
        heading_row.addStretch()
        add = IconButton("", "plus", "ghost", self._new_project)
        add.setToolTip(self.tr("New project"))
        heading_row.addWidget(add)
        layout.addLayout(heading_row)
        layout.addWidget(self.project_list, 1)
        import_button = IconButton(self.tr("Import tests"), "upload", "ghost", self._import)
        import_button.setObjectName("SidebarLink")
        layout.addWidget(import_button)
        settings = IconButton(self.tr("Settings"), "settings", "ghost", self._open_settings)
        settings.setObjectName("SidebarLink")
        layout.addWidget(settings)
        return sidebar

    def _brand(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(8, 0, 0, 0)
        row.setSpacing(12)
        mark = QLabel()
        mark.setPixmap(mark_pixmap(40))
        mark.setFixedSize(40, 40)
        row.addWidget(mark)

        names = QVBoxLayout()
        names.setSpacing(3)
        brand = QLabel("<b style='font-weight:800'>COMFY</b><span style='font-weight:300'>CAPTURE</span>")
        brand.setObjectName("Brand")
        brand.setFont(heading_font(15, QFont.Weight.Normal, 5))
        company = QLabel(f"COMFYCODERS · {__version__}")
        company.setObjectName("BrandSub")
        company.setFont(heading_font(10, QFont.Weight.Medium, 14))
        names.addStretch()
        names.addWidget(brand)
        names.addWidget(company)
        names.addStretch()
        row.addLayout(names, 1)
        return row

    def _load_projects(self, select_id: int | None = None) -> None:
        self.project_list.blockSignals(True)
        self.project_list.clear()
        for project in self._projects.all():
            item = QListWidgetItem(icon("dot", active_tokens().highlight, 16), project.name)
            item.setData(Qt.ItemDataRole.UserRole, project.id)
            self.project_list.addItem(item)
            if project.id == select_id:
                self.project_list.setCurrentItem(item)
        if self.project_list.currentItem() is None and self.project_list.count():
            self.project_list.setCurrentRow(0)
        self.project_list.blockSignals(False)
        self.project_view.set_project(self._current_project())

    def _current_project(self) -> Project | None:
        item = self.project_list.currentItem()
        return self._projects.get(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _on_project_selected(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        self.project_view.set_project(self._current_project() if current else None)

    def _new_project(self) -> None:
        dialog = ProjectDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save(dialog.result_project())

    def _edit_project(self) -> None:
        project = self._current_project()
        if project is None:
            return
        dialog = ProjectDialog(project, self, self._tests.for_project(project.id or 0))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save(dialog.result_project())

    def _save(self, project: Project) -> None:
        try:
            saved = self._projects.save(project)
        except sqlite3.IntegrityError:
            messages.warn(self, self.tr("Project"), self.tr("Another project already uses this slug."))
            return
        self._load_projects(saved.id)

    def _delete_project(self) -> None:
        project = self._current_project()
        if project is None or project.id is None:
            return
        if messages.confirm(
            self,
            self.tr("Delete project"),
            self.tr("Delete {name} with all its environments, tests and runs?").format(name=project.name),
            self.tr("Delete project"),
            destructive=True,
        ):
            self._projects.delete(project.id)
            self._load_projects()

    def _import(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, self.tr("Import tests"), "", self.tr("Exported tests (*.json)")
        )
        if not files:
            return
        try:
            documents = [json.loads(Path(file).read_text(encoding="utf-8")) for file in files]
            reports = exchange.import_documents(
                self._connection, documents, lambda slug, name: SecretStore(slug).has(name)
            )
        except (OSError, json.JSONDecodeError, exchange.ExchangeError) as error:
            messages.fail(self, self.tr("Import tests"), str(error))
            return
        self._load_projects(self._projects.by_slug(reports[-1].project).id if reports else None)
        messages.inform(
            self, self.tr("Import tests"), "\n\n".join(self._describe(report) for report in reports)
        )

    def _describe(self, report: exchange.ImportReport) -> str:
        lines = [self.tr("Project {name}").format(name=report.project)]
        parts = (
            (report.tests_added, self.tr("Added tests: {items}")),
            (report.tests_updated, self.tr("Updated tests: {items}")),
            (report.environments_added, self.tr("Added environments: {items}")),
            (report.missing_variables, self.tr("Fill in these variables: {items}")),
            (report.missing_secrets, self.tr("Add these secrets: {items}")),
            (report.missing_tests, self.tr("Setup or login tests that were not imported: {items}")),
        )
        for items, template in parts:
            if items:
                lines.append(template.format(items=", ".join(items)))
        if not report.ready:
            lines.append(self.tr("Runs refuse to start until the missing items are supplied."))
        return "\n".join(lines)

    def _open_settings(self) -> None:
        SettingsDialog(self).exec()
