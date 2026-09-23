from __future__ import annotations

from dataclasses import replace
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from browsertests.core import ir
from browsertests.core.models import Environment, Project, Step, Test
from browsertests.core.session import SessionPayload
from browsertests.ui.core_process import CoreProcess
from browsertests.ui.dialogs import split_list
from browsertests.ui.recording_view import fill_steps_table, steps_table


class ReviewDialog(QDialog):
    def __init__(
        self, test: Test, project: Project, environment: Environment, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Review test"))
        self.resize(1000, 620)
        self._test = test
        self._project = project
        self._environment = environment
        self._steps: list[Step] = list(test.steps)
        self._verifier: CoreProcess | None = None

        self.name = QLineEdit(test.name)
        self.tags = QLineEdit(", ".join(test.tags))
        self.description = QLineEdit(test.description)
        self.destructive = QCheckBox(self.tr("This test changes data (places orders, sends e-mails, pays)"))
        self.destructive.setChecked(test.destructive)
        form = QFormLayout()
        form.addRow(self.tr("Name"), self.name)
        form.addRow(self.tr("Tags"), self.tags)
        form.addRow(self.tr("Description"), self.description)
        form.addRow(self.tr("Device"), QLabel(test.device.label))
        form.addRow("", self.destructive)

        self.table = steps_table(self)
        self.status = QLabel()
        self.status.setWordWrap(True)

        self.up_button = QPushButton(self.tr("Move up"))
        self.down_button = QPushButton(self.tr("Move down"))
        self.remove_button = QPushButton(self.tr("Remove step"))
        self.verify_button = QPushButton(self.tr("Verify selectors"))
        self.verify_button.setToolTip(
            self.tr("Replays the test headless and keeps only selectors that match the recorded element.")
        )
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button.clicked.connect(lambda: self._move(1))
        self.remove_button.clicked.connect(self._remove)
        self.verify_button.clicked.connect(self._verify)
        step_buttons = QHBoxLayout()
        for button in (self.up_button, self.down_button, self.remove_button):
            step_buttons.addWidget(button)
        step_buttons.addStretch()
        step_buttons.addWidget(self.verify_button)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.table)
        layout.addLayout(step_buttons)
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)
        self._refresh()

    def result_test(self) -> Test:
        return replace(
            self._test,
            name=self.name.text().strip(),
            tags=ir.normalize_tags(split_list(self.tags.text())),
            description=self.description.text().strip(),
            destructive=self.destructive.isChecked(),
            steps=tuple(self._steps),
        )

    def _refresh(self, select: int | None = None) -> None:
        fill_steps_table(self.table, tuple(self._steps))
        if select is not None and 0 <= select < len(self._steps):
            self.table.selectRow(select)
        attention = sum(1 for row in range(self.table.rowCount()) if self.table.item(row, 3).text())
        self.status.setText(
            self.tr("{count} steps, {attention} need attention.").format(
                count=len(self._steps), attention=attention
            )
        )

    def _selected_row(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _move(self, offset: int) -> None:
        row = self._selected_row()
        if row is None or not 0 <= row + offset < len(self._steps):
            return
        self._steps[row], self._steps[row + offset] = self._steps[row + offset], self._steps[row]
        self._refresh(row + offset)

    def _remove(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        del self._steps[row]
        self._refresh(min(row, len(self._steps) - 1))

    def _verify(self) -> None:
        if self.destructive.isChecked() and not self._environment.allow_destructive:
            QMessageBox.warning(
                self,
                self.windowTitle(),
                self.tr(
                    "This test is marked destructive and {environment} does not allow destructive tests."
                ).format(environment=self._environment.name),
            )
            return
        payload = SessionPayload(
            base_url=self._environment.base_url,
            test_id_attributes=self._project.test_id_attributes,
            project_slug=self._project.slug,
            device=self._test.device,
            environment=self._environment.config,
            steps=tuple(self._steps),
        )
        self.verify_button.setEnabled(False)
        self.status.setText(self.tr("Verifying selectors…"))
        self._verifier = CoreProcess(self)
        self._verifier.message.connect(self._on_verify_message)
        self._verifier.finished.connect(lambda _code: self.verify_button.setEnabled(True))
        self._verifier.start("browsertests.core.verify", payload.to_dict())

    def _on_verify_message(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "replayed":
            self.status.setText(self.tr("Verifying step {step}…").format(step=message["outcome"]["step_id"]))
            return
        if kind == "error":
            self.status.setText(
                self.tr("Verification failed: {message}").format(message=message.get("message"))
            )
            return
        if kind != "done":
            return
        self._steps = [ir.step_from_dict(step) for step in message.get("steps", [])]
        self._refresh()
        failed = message.get("failed")
        if failed:
            self.status.setText(
                self.tr("Verification stopped at step {step}: {message}").format(
                    step=failed.get("step_id"), message=failed.get("message")
                )
            )
            return
        self.status.setText(self.status.text() + " " + self.tr("All steps replayed; selectors verified."))

    def _save(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, self.windowTitle(), self.tr("A test needs a name."))
            return
        self.accept()
