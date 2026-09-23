from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from browsertests.core import db
from browsertests.core.models import Environment, Project, StoredTest
from browsertests.core.processes import show_trace_command
from browsertests.ui.core_process import CoreProcess
from browsertests.ui.widgets import Card, IconButton, data_table, enable_with_selection, muted

STATUS_COLORS = {
    "passed": "#16a34a",
    "flaky": "#d97706",
    "failed": "#dc2626",
    "error": "#dc2626",
    "skipped": "#6b6b7b",
    "running": "#7c3aed",
    "queued": "#6b6b7b",
}


def status_item(status: str, label: str) -> QTableWidgetItem:
    item = QTableWidgetItem(f"●  {label}")
    item.setForeground(QColor(STATUS_COLORS.get(status, "#6b6b7b")))
    return item


class RunDialog(QDialog):
    def __init__(
        self,
        project: Project,
        environment: Environment,
        tests: list[StoredTest],
        database: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Run tests"))
        self.resize(980, 560)
        self._project = project
        self._environment = environment
        self._tests = tests
        self._database = database
        self._rows = {stored.test.id: row for row, stored in enumerate(tests)}
        self._steps = dict.fromkeys(self._rows, 0)
        self._artifacts: dict[int, str] = {}
        self._process: CoreProcess | None = None

        title = QLabel(self.tr("Run tests"))
        title.setObjectName("PageTitle")
        self.subtitle = muted(
            self.tr("{count} tests against {environment} ({url})").format(
                count=len(tests), environment=environment.name, url=environment.base_url
            )
        )
        self.status = QLabel(self.tr("Ready."))
        self.status.setObjectName("Badge")

        self.table = data_table(
            self,
            [self.tr("Status"), self.tr("Test"), self.tr("Duration"), self.tr("Message")],
            stretch_column=3,
        )
        self.table.setRowCount(len(tests))
        for row, stored in enumerate(tests):
            self.table.setItem(row, 0, status_item("queued", self.tr("Queued")))
            self.table.setItem(row, 1, QTableWidgetItem(stored.test.name))
            self.table.setItem(row, 2, QTableWidgetItem(""))
            self.table.setItem(row, 3, QTableWidgetItem(""))
        self.table.resizeColumnsToContents()

        card = Card(self.tr("Results"))
        self.open_trace = IconButton(self.tr("Open trace"), "search", "ghost", self._open_trace)
        self.open_folder = IconButton(self.tr("Open folder"), "folder", "ghost", self._open_folder)
        card.add_action(self.open_trace)
        card.add_action(self.open_folder)
        enable_with_selection(self.table, self.open_trace, self.open_folder)
        card.body.addWidget(self.table)

        self.headed = QCheckBox(self.tr("Show the browser"))
        self.start_button = IconButton(self.tr("Start run"), "continue", "primary", self._start)
        self.close_button = IconButton(self.tr("Close"), variant="ghost", on_click=self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(self.headed)
        buttons.addStretch()
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.start_button)

        heading = QHBoxLayout()
        heading.addWidget(title)
        heading.addSpacing(8)
        heading.addWidget(self.status)
        heading.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        layout.addLayout(heading)
        layout.addWidget(self.subtitle)
        layout.addWidget(card, 1)
        layout.addLayout(buttons)

    def _start(self) -> None:
        self.start_button.setEnabled(False)
        self.headed.setEnabled(False)
        self.status.setText(self.tr("Running…"))
        arguments = [
            "--database",
            str(self._database),
            "run",
            "--project",
            self._project.slug,
            "--env",
            self._environment.name,
            "--jsonl",
        ]
        for stored in self._tests:
            arguments += ["--test", stored.test.id]
        if self.headed.isChecked():
            arguments.append("--headed")
        self._process = CoreProcess(self)
        self._process.message.connect(self._on_message)
        self._process.finished.connect(self._on_finished)
        self._process.start_module("browsertests.cli", arguments)

    def _on_message(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "login_started":
            self.status.setText(self.tr("Logging in with {name}…").format(name=message.get("name")))
            return
        if kind == "test_started":
            row = self._rows.get(str(message.get("test")))
            if row is not None:
                self.table.setItem(row, 0, status_item("running", self.tr("Running")))
            return
        if kind == "step":
            test = str(message.get("test"))
            row = self._rows.get(test)
            if row is not None:
                self._steps[test] = self._steps.get(test, 0) + 1
                self.table.item(row, 3).setText(self.tr("Step {count}").format(count=self._steps[test]))
            return
        if kind == "test_finished":
            self._show_result(message.get("result", {}))
            return
        if kind == "summary":
            counts = message.get("counts", {})
            parts = [f"{count} {status}" for status, count in counts.items() if count]
            self.status.setText(", ".join(parts))

    def _show_result(self, result: dict[str, Any]) -> None:
        row = self._rows.get(str(result.get("test")))
        if row is None:
            return
        labels = {
            "passed": self.tr("Passed"),
            "flaky": self.tr("Flaky"),
            "failed": self.tr("Failed"),
            "error": self.tr("Error"),
            "skipped": self.tr("Skipped"),
        }
        status = str(result.get("status"))
        self.table.setItem(row, 0, status_item(status, labels.get(status, status)))
        self.table.item(row, 2).setText(f"{int(result.get('duration_ms', 0)) / 1000:.1f}s")
        message = result.get("message") or ""
        if result.get("failed_step_id"):
            message = self.tr("Step {step}: {message}").format(step=result["failed_step_id"], message=message)
        self.table.item(row, 3).setText(message)
        self.table.item(row, 3).setToolTip(message)
        if result.get("artifact_path"):
            self._artifacts[row] = str(result["artifact_path"])
        self.table.resizeColumnToContents(0)

    def _on_finished(self, exit_code: int) -> None:
        self.start_button.setEnabled(True)
        self.headed.setEnabled(True)
        if exit_code == 2 and self._process is not None and self._process.stderr.strip():
            self.status.setText(self.tr("Configuration error"))
            self.subtitle.setText(self._process.stderr.strip().removeprefix("error: "))

    def _selected_artifact(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        return self._artifacts.get(rows[0].row()) if rows else None

    def _open_trace(self) -> None:
        artifact = self._selected_artifact()
        if artifact is None:
            return
        viewer = CoreProcess(self)
        viewer.start_command(show_trace_command(str(Path(artifact) / "trace.zip")))

    def _open_folder(self) -> None:
        artifact = self._selected_artifact() or str(db.data_dir() / "artifacts" / self._project.slug)
        QDesktopServices.openUrl(QUrl.fromLocalFile(artifact))
