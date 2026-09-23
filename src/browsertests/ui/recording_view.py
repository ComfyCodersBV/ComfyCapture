from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from browsertests.core import ir
from browsertests.core.models import Step
from browsertests.core.processes import browser_install_command
from browsertests.ui import formatting
from browsertests.ui.core_process import CoreProcess

MISSING_BROWSER = "Executable doesn't exist"


def fill_steps_table(table: QTableWidget, steps: tuple[Step, ...]) -> None:
    table.setRowCount(len(steps))
    for row, step in enumerate(steps):
        cells = (
            step.action.value,
            formatting.target_text(step),
            formatting.value_text(step),
            "; ".join(formatting.attention(step)),
        )
        for column, text in enumerate(cells):
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            table.setItem(row, column, item)
    table.resizeColumnsToContents()


def steps_table(parent: QWidget) -> QTableWidget:
    table = QTableWidget(0, 4, parent)
    table.setHorizontalHeaderLabels(
        [parent.tr("Action"), parent.tr("Target"), parent.tr("Value"), parent.tr("Needs attention")]
    )
    table.horizontalHeader().setStretchLastSection(True)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    return table


class RecordingDialog(QDialog):
    def __init__(self, payload: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Recording"))
        self.resize(900, 520)
        self._payload = payload
        self._steps: tuple[Step, ...] = ()
        self._error: str | None = None
        self._finished = False
        self._closing = False

        self.status = QLabel(self.tr("Starting browser…"))
        self.table = steps_table(self)
        self.hint = QLabel(
            self.tr(
                "Click through the site in the browser window. Use the toolbar in the page to add assertions. "
                "Close the browser or press Stop when you are done."
            )
        )
        self.hint.setWordWrap(True)
        self.stop_button = QPushButton(self.tr("Stop recording"))
        self.stop_button.clicked.connect(self._stop)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.stop_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.hint)
        layout.addWidget(self.table)
        layout.addLayout(buttons)

        self.process = CoreProcess(self)
        self.process.message.connect(self._on_message)
        self.process.finished.connect(self._on_finished)
        self.process.start("browsertests.core.session", payload)

    @property
    def steps(self) -> tuple[Step, ...]:
        return self._steps

    def _stop(self) -> None:
        self.stop_button.setEnabled(False)
        self.status.setText(self.tr("Stopping…"))
        self.process.stop()

    def _on_message(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "status":
            text = {
                "replaying": self.tr("Replaying the saved steps…"),
                "recording": self.tr("Recording."),
            }.get(message.get("status", ""), "")
            self.status.setText(text)
            return
        if kind == "replayed":
            outcome = message.get("outcome", {})
            state = self.tr("passed") if outcome.get("passed") else self.tr("failed")
            self.status.setText(
                self.tr("Replaying: step {step} {state}").format(step=outcome.get("step_id"), state=state)
            )
            return
        if kind in ("steps", "done"):
            self._steps = tuple(ir.step_from_dict(step) for step in message.get("steps", []))
            fill_steps_table(self.table, self._steps)
            self._finished = self._finished or kind == "done"
            return
        if kind == "error":
            self._error = str(message.get("message", ""))
            if not message.get("fatal"):
                QMessageBox.warning(self, self.windowTitle(), self._error)

    def _on_finished(self, exit_code: int) -> None:
        if self._closing:
            return
        if self._finished:
            self.accept()
            return
        error = self._error or self.process.stderr.strip() or self.tr("The recording stopped unexpectedly.")
        if MISSING_BROWSER in error and self._offer_browser_install():
            return
        QMessageBox.critical(self, self.windowTitle(), error)
        self.reject()

    def _offer_browser_install(self) -> bool:
        answer = QMessageBox.question(
            self,
            self.windowTitle(),
            self.tr("The Playwright browser is not installed yet. Download it now (about 150 MB)?"),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        self.status.setText(self.tr("Downloading the browser…"))
        self.stop_button.setEnabled(False)
        installer = CoreProcess(self)
        installer.finished.connect(self._on_installed)
        installer.start_command(browser_install_command())
        return True

    def _on_installed(self, exit_code: int) -> None:
        if exit_code != 0:
            QMessageBox.critical(self, self.windowTitle(), self.tr("Installing the browser failed."))
            self.reject()
            return
        self._error = None
        self.stop_button.setEnabled(True)
        self.status.setText(self.tr("Starting browser…"))
        self.process.start("browsertests.core.session", self._payload)

    def reject(self) -> None:
        self._closing = True
        if not self._finished:
            self.process.kill()
        super().reject()
