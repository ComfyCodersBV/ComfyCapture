from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from browsertests import __version__
from browsertests.core import db
from browsertests.core.models import Project
from browsertests.ui.dialogs import ProjectDialog
from browsertests.ui.project_view import ProjectView
from browsertests.ui.settings_dialog import SettingsDialog
from browsertests.ui.widgets import IconButton

WINDOW_TITLE = "ComfyCoders BrowsertestSuite {version}"


class MainWindow(QMainWindow):
    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE.format(version=__version__))
        self.resize(1280, 800)
        self.setMinimumSize(960, 600)
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

    def _sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(250)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(6)

        brand = QLabel("BrowsertestSuite")
        brand.setObjectName("Brand")
        company = QLabel(f"COMFYCODERS  ·  {__version__}")
        company.setObjectName("BrandSub")
        layout.addWidget(brand)
        layout.addWidget(company)
        layout.addSpacing(18)

        heading_row = QHBoxLayout()
        heading = QLabel(self.tr("PROJECTS"))
        heading.setObjectName("SidebarHeading")
        heading_row.addWidget(heading)
        heading_row.addStretch()
        add = IconButton("", "plus", "ghost", self._new_project)
        add.setToolTip(self.tr("New project"))
        heading_row.addWidget(add)
        layout.addLayout(heading_row)
        layout.addWidget(self.project_list, 1)
        settings = IconButton(self.tr("Settings"), "settings", "ghost", self._open_settings)
        settings.setStyleSheet("text-align: left; padding-left: 10px;")
        layout.addWidget(settings)
        return sidebar

    def _load_projects(self, select_id: int | None = None) -> None:
        self.project_list.blockSignals(True)
        self.project_list.clear()
        for project in self._projects.all():
            item = QListWidgetItem(project.name)
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
            QMessageBox.warning(self, self.tr("Project"), self.tr("Another project already uses this slug."))
            return
        self._load_projects(saved.id)

    def _delete_project(self) -> None:
        project = self._current_project()
        if project is None or project.id is None:
            return
        answer = QMessageBox.question(
            self,
            self.tr("Delete project"),
            self.tr("Delete {name} with all its environments, tests and runs?").format(name=project.name),
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._projects.delete(project.id)
            self._load_projects()

    def _open_settings(self) -> None:
        SettingsDialog(self).exec()
