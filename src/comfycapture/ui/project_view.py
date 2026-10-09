from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, Signal
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from comfycapture.core import db, exchange, ir, pest
from comfycapture.core.models import Environment, Project, StoredTest, Test, Variable
from comfycapture.core.session import SessionPayload
from comfycapture.ui import formatting, messages, tickets
from comfycapture.ui.dialogs import EnvironmentDialog, RecordSetupDialog, split_list
from comfycapture.ui.icons import icon
from comfycapture.ui.recording_view import RecordingDialog
from comfycapture.ui.run_view import STATUS_TONES, RunDialog
from comfycapture.ui.test_editor import ReviewDialog
from comfycapture.ui.theme import active_tokens
from comfycapture.ui.variables_dialog import VariablesDialog, create_variable
from comfycapture.ui.widgets import (
    PILL_ROLE,
    Card,
    IconButton,
    attach_tag_completer,
    data_table,
    enable_with_selection,
    fit_rows,
    muted,
)

TAGS_COLUMN = 3
TICKET_LINKS_ROLE = Qt.ItemDataRole.UserRole + 1


def set_row(widget: QTableWidget, row: int, key: int, cells: tuple[str, ...]) -> None:
    for column, text in enumerate(cells):
        item = QTableWidgetItem(text)
        item.setToolTip(text)
        if column == 0:
            item.setData(Qt.ItemDataRole.UserRole, key)
        widget.setItem(row, column, item)


def selected_key(widget: QTableWidget) -> int | None:
    rows = widget.selectionModel().selectedRows()
    if not rows:
        return None
    return widget.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)


def run_label(status: str) -> str:
    labels = {
        "passed": QCoreApplication.translate("RunStatus", "Passed"),
        "flaky": QCoreApplication.translate("RunStatus", "Flaky"),
        "failed": QCoreApplication.translate("RunStatus", "Failed"),
        "error": QCoreApplication.translate("RunStatus", "Error"),
        "skipped": QCoreApplication.translate("RunStatus", "Skipped"),
    }
    return labels.get(status, status)


class ProjectView(QStackedWidget):
    edit_project_requested = Signal()
    delete_project_requested = Signal()
    new_project_requested = Signal()

    def __init__(self, connection: sqlite3.Connection, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._connection = connection
        self._environments = db.EnvironmentRepository(connection)
        self._tests = db.TestRepository(connection)
        self._runs = db.RunRepository(connection)
        self._database = db.database_file(connection) or db.default_database_path()
        self._project: Project | None = None
        self.addWidget(self._empty_page())
        self.addWidget(self._project_page())
        self.set_project(None)

    def _empty_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch()
        title = QLabel(self.tr("Record your first browser test"))
        title.setObjectName("PageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QLabel(
            self.tr("Create a project for a website, add the environments it runs on, then record a test.")
        )
        text.setObjectName("EmptyState")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setWordWrap(True)
        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(
            IconButton(self.tr("Create a project"), "plus", "primary", self.new_project_requested.emit)
        )
        button_row.addStretch()
        layout.addWidget(title)
        layout.addWidget(text)
        layout.addSpacing(12)
        layout.addLayout(button_row)
        layout.addStretch()
        return page

    def _project_page(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(20)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        self.title = QLabel()
        self.title.setObjectName("PageTitle")
        self.attributes = muted("")
        titles.addWidget(self.title)
        titles.addWidget(self.attributes)
        header.addLayout(titles, 1)
        header.addWidget(IconButton(self.tr("Variables"), "braces", "ghost", self._open_variables))
        header.addWidget(IconButton(self.tr("Edit"), "edit", "ghost", self.edit_project_requested.emit))
        header.addWidget(IconButton(self.tr("Delete"), "trash", "danger", self.delete_project_requested.emit))
        layout.addLayout(header)

        environments = Card(
            self.tr("Environments"), self.tr("Where the tests run, e.g. staging and production.")
        )
        self.environment_table = data_table(
            self, [self.tr("Name"), self.tr("Base URL"), self.tr("Destructive tests")], stretch_column=1
        )
        self.environment_table.doubleClicked.connect(self._edit_environment)
        edit_environment = IconButton(self.tr("Edit"), "edit", "ghost", self._edit_environment)
        delete_environment = IconButton(self.tr("Delete"), "trash", "danger", self._delete_environment)
        environments.add_action(edit_environment)
        environments.add_action(delete_environment)
        environments.add_action(
            IconButton(self.tr("Add environment"), "plus", "secondary", self._add_environment)
        )
        enable_with_selection(self.environment_table, edit_environment, delete_environment)
        self.environment_empty = muted(self.tr("No environments yet. Add one to start recording."))
        environments.body.addWidget(self.environment_empty)
        environments.body.addWidget(self.environment_table)
        layout.addWidget(environments)

        tests = Card(self.tr("Tests"), self.tr("Recorded tests. Double-click a test to review it."))
        self.test_table = data_table(
            self,
            [
                self.tr("Test"),
                self.tr("Last run"),
                self.tr("Device"),
                self.tr("Tags"),
                self.tr("Steps"),
                self.tr("Updated"),
            ],
            stretch_column=0,
        )
        self.test_table.setMinimumHeight(200)
        self.test_table.doubleClicked.connect(self._review_test)
        self.test_table.cellClicked.connect(self._open_ticket)
        self.test_table.viewport().installEventFilter(self)
        review = IconButton(self.tr("Review"), "edit", "ghost", self._review_test)
        continue_recording = IconButton(
            self.tr("Continue recording"), "continue", "ghost", self._continue_recording
        )
        delete_test = IconButton(self.tr("Delete"), "trash", "danger", self._delete_test)
        run_selected = IconButton(self.tr("Run"), "continue", "ghost", self._run_selected)
        for button in (run_selected, review, continue_recording, delete_test):
            tests.add_action(button)
        tests.add_action(IconButton(self.tr("Export"), "download", "ghost", self._export))
        tests.add_action(IconButton(self.tr("Pest"), "download", "ghost", self._export_pest))
        tests.add_action(IconButton(self.tr("Run all"), "continue", "secondary", self._run_all))
        tests.add_action(IconButton(self.tr("Record new test"), "record", "primary", self._record_test))
        enable_with_selection(self.test_table, run_selected, review, continue_recording, delete_test)
        self.tag_filter = QLineEdit()
        self.tag_filter.setObjectName("SearchField")
        self.tag_filter.addAction(
            icon("search", active_tokens().text_subtle, 16), QLineEdit.ActionPosition.LeadingPosition
        )
        self.tag_filter.setPlaceholderText(self.tr("Filter by tags, e.g. CINF-19, checkout"))
        self.tag_filter.setClearButtonEnabled(True)
        self.tag_filter.textChanged.connect(self._load_tests)
        self._filter_completer_tags: list[str] = []
        self.test_empty = muted(self.tr("No tests yet. Record one with the button above."))
        tests.body.addWidget(self.tag_filter)
        tests.body.addWidget(self.test_empty)
        tests.body.addWidget(self.test_table, 1)
        layout.addWidget(tests, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    @property
    def project(self) -> Project | None:
        return self._project

    def set_project(self, project: Project | None) -> None:
        self._project = project
        self.setCurrentIndex(0 if project is None else 1)
        if project is None:
            return
        self.title.setText(project.name)
        self.attributes.setText(
            self.tr("Slug {slug}  ·  test attributes: {attributes}").format(
                slug=project.slug, attributes=", ".join(project.test_id_attributes)
            )
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
            allowed = self.tr("Allowed") if environment.allow_destructive else self.tr("Refused")
            set_row(
                self.environment_table,
                row,
                environment.id or 0,
                (environment.name, environment.base_url, allowed),
            )
            self.environment_table.item(row, 2).setData(
                PILL_ROLE, "warning" if environment.allow_destructive else "neutral"
            )
        self.environment_table.resizeColumnsToContents()
        fit_rows(self.environment_table, 1, 5)
        self.environment_empty.setVisible(not environments)
        self.environment_table.setVisible(bool(environments))

    def _load_tests(self) -> None:
        if self._project is None or self._project.id is None:
            self.test_table.setRowCount(0)
            return
        tags = self._tests.tags(self._project.id)
        if tags != self._filter_completer_tags:
            self._filter_completer_tags = tags
            attach_tag_completer(self.tag_filter, tags)
        stored = self._tests.for_project(self._project.id, split_list(self.tag_filter.text()))
        latest = self._runs.latest([item.id for item in stored])
        self.test_table.setRowCount(len(stored))
        for row, item in enumerate(stored):
            test = item.test
            run = latest.get(item.id)
            cells = (
                test.name + self._role(test.id),
                run_label(run.status.value) if run else self.tr("Never run"),
                test.device.label,
                "  ".join(formatting.tag_text(tag) for tag in test.tags),
                str(len(test.steps)),
                item.updated_at.replace("T", " ")[:16],
            )
            set_row(self.test_table, row, item.id, cells)
            self.test_table.item(row, 1).setData(
                PILL_ROLE, STATUS_TONES.get(run.status.value, "neutral") if run else "neutral"
            )
            if run is not None:
                self.test_table.item(row, 1).setToolTip(run.message or run.started_at)
            links = tickets.ticket_links(test.tags)
            self.test_table.item(row, TAGS_COLUMN).setData(TICKET_LINKS_ROLE, links)
            if links:
                self.test_table.item(row, TAGS_COLUMN).setToolTip(
                    self.tr("Click to open {tickets}").format(tickets=", ".join(links))
                )
        self.test_table.resizeColumnsToContents()
        filtering = bool(self.tag_filter.text().strip())
        self.test_empty.setText(
            self.tr("No tests match these tags.")
            if filtering
            else self.tr("No tests yet. Record one with the button above.")
        )
        self.test_empty.setVisible(not stored)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.test_table.viewport() and isinstance(event, QMouseEvent):
            self._update_ticket_cursor(event)
        return super().eventFilter(watched, event)

    def _update_ticket_cursor(self, event: QMouseEvent) -> None:
        item = self.test_table.itemAt(event.position().toPoint())
        linked = item is not None and item.column() == TAGS_COLUMN and bool(item.data(TICKET_LINKS_ROLE))
        if linked:
            self.test_table.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            return
        self.test_table.viewport().unsetCursor()

    def _open_ticket(self, row: int, column: int) -> None:
        if column != TAGS_COLUMN:
            return
        links = self.test_table.item(row, column).data(TICKET_LINKS_ROLE) or {}
        if len(links) == 1:
            tickets.open_ticket(next(iter(links.values())))
            return
        if not links:
            return
        menu = QMenu(self)
        for tag, url in links.items():
            menu.addAction(tag, lambda url=url: tickets.open_ticket(url))
        menu.exec(QCursor.pos())

    def _open_variables(self) -> None:
        if self._project is not None:
            VariablesDialog(self._connection, self._project, self).exec()

    def _role(self, test_id: str) -> str:
        if self._project is None:
            return ""
        if test_id == self._project.setup_test_uuid:
            return "  ·  " + self.tr("setup")
        if test_id == self._project.login_test_uuid:
            return "  ·  " + self.tr("login")
        return ""

    def _run(self, tests: list[StoredTest]) -> None:
        if self._project is None or not tests:
            return
        environment = self._choose_environment()
        if environment is None:
            return
        RunDialog(self._project, environment, tests, self._database, self).exec()
        self._load_tests()

    def _run_selected(self) -> None:
        stored = self._selected_test()
        if stored is not None:
            self._run([stored])

    def _run_all(self) -> None:
        if self._project is None or self._project.id is None:
            return
        special = {self._project.setup_test_uuid, self._project.login_test_uuid}
        tests = [
            stored
            for stored in self._tests.for_project(self._project.id, split_list(self.tag_filter.text()))
            if stored.test.id not in special
        ]
        if not tests:
            messages.inform(self, self.tr("Run"), self.tr("There are no tests to run."))
            return
        self._run(tests)

    def _export(self) -> None:
        if self._project is None or self._project.id is None:
            return
        selected = self._selected_test()
        tests = (
            [selected]
            if selected
            else self._tests.for_project(self._project.id, split_list(self.tag_filter.text()))
        )
        if not tests:
            messages.inform(self, self.tr("Export"), self.tr("There are no tests to export."))
            return
        directory = QFileDialog.getExistingDirectory(self, self.tr("Export tests to"))
        if not directory:
            return
        written = []
        for name, text in exchange.export_tests(self._connection, self._project, tests):
            path = Path(directory) / name
            path.write_text(text, encoding="utf-8")
            written.append(name)
        messages.inform(
            self,
            self.tr("Export"),
            self.tr(
                "Exported {count} tests to {directory}. Values of variables and secrets are not included."
            ).format(count=len(written), directory=directory),
        )

    def _export_pest(self) -> None:
        if self._project is None or self._project.id is None:
            return
        special = {self._project.setup_test_uuid, self._project.login_test_uuid}
        selected = self._selected_test()
        tests = (
            [selected]
            if selected
            else [
                stored
                for stored in self._tests.for_project(self._project.id, split_list(self.tag_filter.text()))
                if stored.test.id not in special
            ]
        )
        if not tests:
            messages.inform(self, self.tr("Pest"), self.tr("There are no tests to export."))
            return
        directory = QFileDialog.getExistingDirectory(self, self.tr("Write Pest tests to, e.g. tests/Browser"))
        if not directory:
            return
        written, problems = 0, []
        for stored in tests:
            try:
                text = pest.render(stored.test)
            except pest.PestExportError as error:
                problems.append(str(error))
                continue
            (Path(directory) / pest.filename(stored.test)).write_text(text, encoding="utf-8")
            written += 1
        message = self.tr("Wrote {count} Pest tests to {directory}.").format(
            count=written, directory=directory
        )
        if problems:
            message += "\n\n" + self.tr("Skipped:") + "\n" + "\n".join(problems)
        messages.inform(self, self.tr("Pest"), message)

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
            messages.warn(
                self,
                self.tr("Environment"),
                self.tr("This project already has an environment with that name."),
            )
        self._load_environments()

    def _delete_environment(self) -> None:
        key = selected_key(self.environment_table)
        if key is None:
            return
        if messages.confirm(
            self,
            self.tr("Delete environment"),
            self.tr("Delete this environment and its run history?"),
            self.tr("Delete"),
            destructive=True,
        ):
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
            viewer=not test.device.fullscreen,
            selector_kinds=project.selector_kinds,
        )

    def _record_test(self) -> None:
        environments = self._environment_list()
        if self._project is None:
            return
        if not environments:
            messages.inform(self, self.tr("Record"), self.tr("Add an environment to this project first."))
            return
        setup = RecordSetupDialog(environments, self, self._tests.tags(self._project.id or 0))
        if setup.exec() != QDialog.DialogCode.Accepted:
            return
        environment = next(item for item in environments if item.id == setup.environment_id())
        test = Test(
            id=ir.new_test_id(),
            name=setup.name.text().strip(),
            tags=setup.test_tags(),
            device=setup.selected_device(),
        )
        start_path = setup.start_path.text().strip() or "/"
        self._record(test, environment, self._payload(self._project, environment, test, start_path))

    def _continue_recording(self) -> None:
        stored = self._selected_test()
        if stored is None or self._project is None:
            return
        environment = self._choose_environment()
        if environment is None:
            return
        self._record(stored.test, environment, self._payload(self._project, environment, stored.test))

    def _record(self, test: Test, environment: Environment, payload: SessionPayload) -> None:
        recording = RecordingDialog(payload.to_dict(), self, self._create_secret)
        if recording.exec() != QDialog.DialogCode.Accepted:
            return
        device = test.device
        if device.fullscreen and recording.viewport is not None:
            device = replace(device, width=recording.viewport[0], height=recording.viewport[1])
        self._review(replace(test, steps=recording.steps, device=device), environment)

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
        review = ReviewDialog(
            test,
            self._project,
            environment,
            self,
            self._tests.tags(self._project.id),
            db.VariableRepository(self._connection).for_project(self._project.id),
            self._create_secret,
        )
        if review.exec() != QDialog.DialogCode.Accepted:
            return
        self._tests.save(self._project.id, review.result_test())
        self._load_tests()

    def _create_secret(self, parent: QWidget, name: str, value: str = "") -> Variable | None:
        if self._project is None:
            return None
        return create_variable(parent, self._connection, self._project, secret=True, name=name, value=value)

    def _delete_test(self) -> None:
        stored = self._selected_test()
        if stored is None:
            return
        if messages.confirm(
            self,
            self.tr("Delete test"),
            self.tr("Delete {name}?").format(name=stored.test.name),
            self.tr("Delete"),
            destructive=True,
        ):
            self._tests.delete(stored.id)
            self._load_tests()

    def _selected_test(self) -> StoredTest | None:
        key = selected_key(self.test_table)
        return self._tests.get(key) if key else None

    def _choose_environment(self) -> Environment | None:
        environments = self._environment_list()
        if not environments:
            messages.inform(
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
