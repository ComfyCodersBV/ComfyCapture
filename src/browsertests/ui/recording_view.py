from __future__ import annotations

from typing import Any

from PySide6.QtCore import QCoreApplication, Qt, QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
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
from browsertests.ui.device_viewer import DevicePanel
from browsertests.ui.widgets import Card, IconButton, data_table, muted

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
    for column in range(3):
        table.resizeColumnToContents(column)
        table.setColumnWidth(column, min(table.columnWidth(column), 420))
    table.scrollToBottom()


def steps_table(parent: QWidget) -> QTableWidget:
    headers = [
        QCoreApplication.translate("StepsTable", "Action"),
        QCoreApplication.translate("StepsTable", "Target"),
        QCoreApplication.translate("StepsTable", "Value"),
        QCoreApplication.translate("StepsTable", "Needs attention"),
    ]
    return data_table(parent, headers, stretch_column=3)


class RecordingDialog(QDialog):
    def __init__(self, payload: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Recording"))
        self.resize(940, 600)
        self._payload = payload
        self._steps: tuple[Step, ...] = ()
        self.viewport: tuple[int, int] | None = None
        self._error: str | None = None
        self._finished = False
        self._closing = False
        self._maximized = False

        title = QLabel(self.tr("Recording"))
        title.setObjectName("PageTitle")
        self.status = QLabel(self.tr("Starting browser…"))
        self.status.setObjectName("Badge")
        self.hint = muted(
            self.tr(
                "Click through the site in the browser window. Use the toolbar at the bottom of the page to add "
                "assertions. Close the browser or press Stop when you are done."
            )
        )
        self.table = steps_table(self)
        card = Card(self.tr("Recorded steps"))
        card.body.addWidget(self.table)
        self.stop_button = IconButton(self.tr("Stop recording"), "stop", "primary", self._stop)

        heading = QHBoxLayout()
        heading.addWidget(title)
        heading.addSpacing(8)
        heading.addWidget(self.status)
        heading.addStretch()
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.stop_button)
        column = QVBoxLayout()
        column.setSpacing(12)
        column.addLayout(heading)
        column.addWidget(self.hint)
        column.addWidget(card, 1)
        column.addLayout(buttons)

        self.device: DevicePanel | None = None
        if payload.get("viewer"):
            self.hint.setText(
                self.tr(
                    "Use the device on the left like a phone or a browser. The toolbar at the bottom of the page "
                    "adds assertions. Press Stop when you are done."
                )
            )
            self.device = DevicePanel(str(payload.get("base_url", "")))
            self.device.command.connect(self._send)
            side = QWidget()
            side.setFixedWidth(460)
            side.setLayout(column)
            layout = QHBoxLayout(self)
            layout.setContentsMargins(20, 18, 20, 18)
            layout.setSpacing(20)
            layout.addWidget(self.device, 1)
            layout.addWidget(side)
            self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        else:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(24, 22, 24, 20)
            layout.addLayout(column)

        self.process = CoreProcess(self)
        self.process.message.connect(self._on_message)
        self.process.finished.connect(self._on_finished)
        self.process.start("browsertests.core.session", payload)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self.device is not None and not self._maximized:
            self._maximized = True
            owner = self.parentWidget() or self
            if owner.screen() is not None:
                self.setGeometry(owner.screen().availableGeometry())
            QTimer.singleShot(0, self.showMaximized)

    @property
    def steps(self) -> tuple[Step, ...]:
        return self._steps

    def _send(self, command: dict[str, Any]) -> None:
        self.process.send(command)

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
        if kind == "frame" and self.device is not None:
            self.device.viewer.show_frame(str(message.get("data", "")))
            return
        if kind == "viewer" and self.device is not None:
            self.device.viewer.set_device(
                int(message.get("width", 0)), int(message.get("height", 0)), bool(message.get("mobile"))
            )
            self.device.viewer.setFocus()
            return
        if kind == "location" and self.device is not None:
            self.device.bar.set_location(str(message.get("url", "")))
            return
        if kind == "viewport":
            self.viewport = (int(message.get("width", 0)), int(message.get("height", 0)))
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
