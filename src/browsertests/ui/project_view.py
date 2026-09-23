from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from browsertests.core import db, ir
from browsertests.core.models import Environment, Project, StoredTest, Test
from browsertests.core.session import SessionPayload
from browsertests.ui import formatting
from browsertests.ui.dialogs import EnvironmentDialog, RecordSetupDialog, split_list
from browsertests.ui.recording_view import RecordingDialog
from browsertests.ui.test_editor import ReviewDialog


def table(parent: QWidget, headers: list[str]) -> QTableWidget:
    widget = QTableWidget(0, len(headers), parent)
    widget.setHorizontalHeaderLabels(headers)
    widget.horizontalHeader().setStretchLastSection(True)
    widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    widget.verticalHeader().setVisible(False)
    return widget


def set_row(widget: QTableWidget, row: int, key: int, cells: tuple[str, ...]) -> None:
    for column, text in enumerate(cells):
        item = QTableWidgetItem(text)
        if column == 0:
            item.setData(Qt.ItemDataRole.UserRole, key)
        widget.setItem(row, column, item)


def selected_key(widget: QTableWidget) -> int | None:
    rows = widget.selectionModel().selectedRows()
    if not rows:
        return None
    return widget.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)


class ProjectView(QWidget):
    def __init__(self, connection: sqlite3.Connection, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._environments = db.EnvironmentRepository(connection)
        self._tests = db.TestRepository(connection)
        self._project: Project | None = None

        self.title = QLabel()
        self.title.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.attributes = QLabel()

        self.environment_table = table(
            self, [self.tr("Environment"), self.tr("Base URL"), self.tr("Destructive")]
        )
        environment_buttons = self._buttons(
            (self.tr("Add"), self._add_environment),
            (self.tr("Edit"), self._edit_environment),
            (self.tr("Delete"), self._delete_environment),
        )
        environment_box = QGroupBox(self.tr("Environments"))
        environment_layout = QVBoxLayout(environment_box)
        environment_layout.addWidget(self.environment_table)
        environment_layout.addLayout(environment_buttons)

        self.tag_filter = QLineEdit()
        self.tag_filter.setPlaceholderText(self.tr("Filter by tags, e.g. CINF-19, checkout"))
        self.tag_filter.textChanged.connect(self._load_tests)
        self.test_table = table(
            self, [self.tr("Test"), self.tr("Device"), self.tr("Tags"), self.tr("Steps"), self.tr("Updated")]
        )
        self.test_table.doubleClicked.connect(self._review_test)
        test_buttons = self._buttons(
            (self.tr("Record new test"), self._record_test),
            (self.tr("Continue recording"), self._continue_recording),
            (self.tr("Review"), self._review_test),
            (self.tr("Delete"), self._delete_test),
        )
        test_box = QGroupBox(self.tr("Tests"))
        test_layout = QVBoxLayout(test_box)
        test_layout.addWidget(self.tag_filter)
        test_layout.addWidget(self.test_table)
        test_layout.addLayout(test_buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.attributes)
        layout.addWidget(environment_box, 1)
        layout.addWidget(test_box, 3)
        self.set_project(None)

    def _buttons(self, *definitions: tuple[str, Callable[[], None]]) -> QHBoxLayout:
        row = QHBoxLayout()
        for label, handler in definitions:
            button = QPushButton(label)
            button.clicked.connect(handler)
            row.addWidget(button)
        row.addStretch()
        return row

    def set_project(self, project: Project | None) -> None:
        self._project = project
        self.setEnabled(project is not None)
        self.title.setText(project.name if project else self.tr("Select or create a project"))
        self.attributes.setText(
            self.tr("Test attributes: {attributes}").format(attributes=", ".join(project.test_id_attributes))
            if project
            else ""
        )
        self._load_environments()
        self._load_tests()

    def _environment_list(self) -> list[Environment]:
        if self._project is None or self._project.id is None:
            return []
        return self._environments.for_project(self._project.id)

    def _load_environments(self) -> None:
        environments = self._environment_list()
        self.environment_table.setRowCount(len(environments))
        for row, environment in enumerate(environments):
            allowed = self.tr("allowed") if environment.allow_destructive else self.tr("refused")
            set_row(
                self.environment_table,
                row,
                environment.id or 0,
                (environment.name, environment.base_url, allowed),
            )
        self.environment_table.resizeColumnsToContents()

    def _load_tests(self) -> None:
        if self._project is None or self._project.id is None:
            self.test_table.setRowCount(0)
            return
        stored = self._tests.for_project(self._project.id, split_list(self.tag_filter.text()))
        self.test_table.setRowCount(len(stored))
        for row, item in enumerate(stored):
            test = item.test
            cells = (
                test.name,
                test.device.label,
                "  ".join(formatting.tag_text(tag) for tag in test.tags),
                str(len(test.steps)),
                item.updated_at.replace("T", " ")[:16],
            )
            set_row(self.test_table, row, item.id, cells)
        self.test_table.resizeColumnsToContents()

    def _add_environment(self) -> None:
        if self._project is None or self._project.id is None:
            return
        dialog = EnvironmentDialog(self._project.id, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save_environment(dialog.result_environment())

    def _edit_environment(self) -> None:
        key = selected_key(self.environment_table)
        environment = self._environments.get(key) if key else None
        if environment is None:
            return
        dialog = EnvironmentDialog(environment.project_id, environment, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save_environment(dialog.result_environment())

    def _save_environment(self, environment: Environment) -> None:
        try:
            self._environments.save(environment)
        except sqlite3.IntegrityError:
            QMessageBox.warning(
                self,
                self.tr("Environment"),
                self.tr("This project already has an environment with that name."),
            )
        self._load_environments()

    def _delete_environment(self) -> None:
        key = selected_key(self.environment_table)
        if key is None:
            return
        answer = QMessageBox.question(
            self, self.tr("Delete environment"), self.tr("Delete this environment and its run history?")
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._environments.delete(key)
            self._load_environments()

    def _payload(
        self, project: Project, environment: Environment, test: Test, start_path: str = "/"
    ) -> SessionPayload:
        return SessionPayload(
            base_url=environment.base_url,
            test_id_attributes=project.test_id_attributes,
            project_slug=project.slug,
            start_path=start_path,
            device=test.device,
            environment=environment.config,
            steps=test.steps,
        )

    def _record_test(self) -> None:
        environments = self._environment_list()
        if self._project is None:
            return
        if not environments:
            QMessageBox.information(
                self, self.tr("Record"), self.tr("Add an environment to this project first.")
            )
            return
        setup = RecordSetupDialog(environments, self)
        if setup.exec() != QDialog.DialogCode.Accepted:
            return
        environment = next(item for item in environments if item.id == setup.environment_id())
        test = Test(
            id=ir.new_test_id(),
            name=setup.name.text().strip(),
            tags=setup.test_tags(),
            device=setup.selected_device(),
        )
        self._record(
            test,
            environment,
            self._payload(self._project, environment, test, setup.start_path.text().strip() or "/"),
        )

    def _continue_recording(self) -> None:
        stored = self._selected_test()
        if stored is None or self._project is None:
            return
        environment = self._choose_environment()
        if environment is None:
            return
        self._record(stored.test, environment, self._payload(self._project, environment, stored.test))

    def _record(self, test: Test, environment: Environment, payload: SessionPayload) -> None:
        recording = RecordingDialog(payload.to_dict(), self)
        if recording.exec() != QDialog.DialogCode.Accepted:
            return
        self._review(replace(test, steps=recording.steps), environment)

    def _review_test(self) -> None:
        stored = self._selected_test()
        if stored is None:
            return
        environment = self._choose_environment()
        if environment is None:
            return
        self._review(stored.test, environment)

    def _review(self, test: Test, environment: Environment) -> None:
        if self._project is None or self._project.id is None:
            return
        review = ReviewDialog(test, self._project, environment, self)
        if review.exec() != QDialog.DialogCode.Accepted:
            return
        self._tests.save(self._project.id, review.result_test())
        self._load_tests()

    def _delete_test(self) -> None:
        stored = self._selected_test()
        if stored is None:
            return
        answer = QMessageBox.question(
            self, self.tr("Delete test"), self.tr("Delete {name}?").format(name=stored.test.name)
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._tests.delete(stored.id)
            self._load_tests()

    def _selected_test(self) -> StoredTest | None:
        key = selected_key(self.test_table)
        return self._tests.get(key) if key else None

    def _choose_environment(self) -> Environment | None:
        environments = self._environment_list()
        if not environments:
            QMessageBox.information(
                self, self.tr("Environment"), self.tr("Add an environment to this project first.")
            )
            return None
        if len(environments) == 1:
            return environments[0]
        names = [environment.name for environment in environments]
        name, accepted = QInputDialog.getItem(
            self, self.tr("Environment"), self.tr("Run against"), names, 0, False
        )
        if not accepted:
            return None
        return environments[names.index(name)]
