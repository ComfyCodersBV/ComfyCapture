from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from comfycapture.core import ir
from comfycapture.core.models import Environment, Project, Step, Test, Variable
from comfycapture.core.session import SessionPayload
from comfycapture.ui import messages
from comfycapture.ui.core_process import CoreProcess
from comfycapture.ui.dialogs import split_list
from comfycapture.ui.recording_view import RecordingDialog, fill_steps_table, steps_table
from comfycapture.ui.step_dialog import StepDialog
from comfycapture.ui.widgets import (
    Card,
    IconButton,
    attach_tag_completer,
    enable_with_selection,
    field_label,
    muted,
)


class ReviewDialog(QDialog):
    def __init__(
        self,
        test: Test,
        project: Project,
        environment: Environment,
        parent: QWidget | None = None,
        tags: list[str] | None = None,
        variables: list[Variable] | None = None,
        create_secret: Callable[[QWidget, str], Variable | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._variables = variables or []
        self._create_secret = create_secret
        self.setWindowTitle(self.tr("Review test"))
        self.resize(1080, 720)
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
        self.name.setPlaceholderText(self.tr("e.g. Guest checkout"))
        self.tags.setPlaceholderText("CINF-19, checkout")
        attach_tag_completer(self.tags, tags or [])
        self.description.setPlaceholderText(self.tr("What this test proves"))
        title = QLabel(self.tr("Review test"))
        title.setObjectName("PageTitle")
        subtitle = muted(
            self.tr("{device}  ·  {environment} ({url})").format(
                device=test.device.label, environment=environment.name, url=environment.base_url
            )
        )

        form = QGridLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(4)
        form.addWidget(field_label(self.tr("Name"), True), 0, 0)
        form.addWidget(field_label(self.tr("Tags"), False), 0, 1)
        form.addWidget(self.name, 1, 0)
        form.addWidget(self.tags, 1, 1)
        form.addWidget(field_label(self.tr("Description"), False), 2, 0, 1, 2)
        form.addWidget(self.description, 3, 0, 1, 2)
        form.addWidget(self.destructive, 4, 0, 1, 2)

        self.table = steps_table(self)
        self.status = QLabel()
        self.status.setObjectName("Status")
        self.status.setWordWrap(True)

        self.verify_button = IconButton(self.tr("Verify selectors"), "shield", "secondary", self._verify)
        self.verify_button.setToolTip(
            self.tr("Replays the test headless and keeps only selectors that match the recorded element.")
        )
        steps_card = Card(self.tr("Steps"), self.tr("Double-click a step to edit its value and selectors."))
        steps_card.add_action(self.verify_button)
        self.table.doubleClicked.connect(self._edit)
        step_buttons = QHBoxLayout()
        edit = IconButton(self.tr("Edit step"), "edit", "ghost", self._edit)
        move_up = IconButton(self.tr("Move up"), "up", "ghost", lambda: self._move(-1))
        move_down = IconButton(self.tr("Move down"), "down", "ghost", lambda: self._move(1))
        rerecord = IconButton(
            self.tr("Re-record step"), "record", "ghost", lambda: self._record_at(replace_step=True)
        )
        record_after = IconButton(
            self.tr("Record after this step"),
            "continue",
            "ghost",
            lambda: self._record_at(replace_step=False),
        )
        remove = IconButton(self.tr("Remove step"), "trash", "danger", self._remove)
        for button in (edit, move_up, move_down, rerecord, record_after, remove):
            step_buttons.addWidget(button)
        enable_with_selection(self.table, edit, move_up, move_down, rerecord, record_after, remove)
        step_buttons.addStretch()
        steps_card.body.addWidget(self.table, 1)
        steps_card.body.addLayout(step_buttons)
        steps_card.body.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(IconButton(self.tr("Discard"), variant="ghost", on_click=self.reject))
        buttons.addWidget(IconButton(self.tr("Save test"), "check", "primary", self._save))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(form)
        layout.addWidget(steps_card, 1)
        layout.addLayout(buttons)
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

    def _edit(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        dialog = StepDialog(
            self._steps[row], self._variables, self, self._new_secret if self._create_secret else None
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._steps[row] = dialog.result_step()
            self._refresh(row)

    def _new_secret(self, parent: QWidget, name: str) -> Variable | None:
        if self._create_secret is None:
            return None
        variable = self._create_secret(parent, name)
        if variable is not None:
            self._variables = [item for item in self._variables if item.name != variable.name] + [variable]
        return variable

    def _record_at(self, replace_step: bool) -> None:
        row = self._selected_row()
        if row is None:
            return
        keep = row if replace_step else row + 1
        payload = SessionPayload(
            base_url=self._environment.base_url,
            test_id_attributes=self._project.test_id_attributes,
            project_slug=self._project.slug,
            device=self._test.device,
            environment=self._environment.config,
            steps=tuple(self._steps[:keep]),
            viewer=not self._test.device.fullscreen,
            selector_kinds=self._project.selector_kinds,
        )
        recording = RecordingDialog(payload.to_dict(), self)
        if recording.exec() != QDialog.DialogCode.Accepted:
            return
        recorded = list(recording.steps[keep:])
        if not recorded:
            return
        if replace_step:
            recorded[0] = replace(recorded[0], id=self._steps[row].id)
            self._steps[row : row + 1] = recorded
        else:
            self._steps[keep:keep] = recorded
        self._refresh(keep)

    def _remove(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        del self._steps[row]
        self._refresh(min(row, len(self._steps) - 1))

    def _verify(self) -> None:
        if self.destructive.isChecked() and not self._environment.allow_destructive:
            messages.warn(
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
        self._verifier.start("comfycapture.core.verify", payload.to_dict())

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
            messages.warn(self, self.windowTitle(), self.tr("A test needs a name."))
            return
        self.accept()
