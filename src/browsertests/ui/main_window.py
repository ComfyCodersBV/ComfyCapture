from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from browsertests import __version__
from browsertests.core import db
from browsertests.core.models import Project
from browsertests.ui.dialogs import ProjectDialog
from browsertests.ui.project_view import ProjectView


class MainWindow(QMainWindow):
    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__()
        self.setWindowTitle(self.tr("BrowsertestSuite {version}").format(version=__version__))
        self.resize(1200, 760)
        self._projects = db.ProjectRepository(connection)

        self.project_list = QListWidget()
        self.project_list.currentItemChanged.connect(self._on_project_selected)
        buttons = QHBoxLayout()
        for label, handler in (
            (self.tr("New"), self._new_project),
            (self.tr("Edit"), self._edit_project),
            (self.tr("Delete"), self._delete_project),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.addWidget(self.project_list)
        sidebar_layout.addLayout(buttons)

        self.project_view = ProjectView(connection)
        splitter = QSplitter()
        splitter.addWidget(sidebar)
        splitter.addWidget(self.project_view)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 940])
        self.setCentralWidget(splitter)
        self._load_projects()

    def _load_projects(self, select_id: int | None = None) -> None:
        self.project_list.clear()
        for project in self._projects.all():
            item = QListWidgetItem(project.name)
            item.setData(Qt.ItemDataRole.UserRole, project.id)
            self.project_list.addItem(item)
            if project.id == select_id:
                self.project_list.setCurrentItem(item)
        if self.project_list.currentItem() is None and self.project_list.count():
            self.project_list.setCurrentRow(0)
        if not self.project_list.count():
            self.project_view.set_project(None)

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
        dialog = ProjectDialog(project, self)
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
