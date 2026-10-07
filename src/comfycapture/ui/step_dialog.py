from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSpinBox,
    QWidget,
)

from comfycapture.core import ir, selectors
from comfycapture.core.models import (
    TARGETED_ACTIONS,
    VALUE_ACTIONS,
    Action,
    Selector,
    SelectorKind,
    Step,
    Target,
    Variable,
)
from comfycapture.ui.dialogs import FormDialog
from comfycapture.ui.icons import icon
from comfycapture.ui.theme import active_tokens
from comfycapture.ui.widgets import IconButton, hint

ASSERTIONS = frozenset(
    {Action.ASSERT_VISIBLE, Action.ASSERT_TEXT, Action.ASSERT_VALUE, Action.ASSERT_CHECKED}
)

SECRET_REFERENCE = re.compile(r"\{\{\s*secret:([^}\s]+)\s*\}\}")


def reference_text(variable: Variable) -> str:
    return "{{secret:" + variable.name + "}}" if variable.is_secret else "{{" + variable.name + "}}"


def selector_text(selector: Selector) -> str:
    flag = "   ⚠ generated-looking id" if selector.suspicious else ""
    prefix = "css " if selector.kind is SelectorKind.CSS else ""
    return f"{prefix}{selectors.describe(selector)}{flag}"


class StepDialog(FormDialog):
    def __init__(
        self,
        step: Step,
        variables: list[Variable],
        parent: QWidget | None = None,
        create_secret: Callable[[QWidget, str], Variable | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._step = step
        self._variables = list(variables)
        self._create_secret = create_secret
        self.setMinimumWidth(620)
        self.set_heading(
            self.tr("Edit step"),
            self.tr("The first selector is tried first; the others are fallbacks, in order."),
        )
        if step.action is Action.UNKNOWN:
            self.add_widget(hint(self.tr("Recorded as: {raw}").format(raw=step.raw or "")))

        self.action = QComboBox()
        for action in Action:
            if action is not Action.UNKNOWN or step.action is Action.UNKNOWN:
                self.action.addItem(action.value, action)
        self.action.setCurrentIndex(max(0, self.action.findData(step.action)))
        self.action.currentIndexChanged.connect(self._update_visibility)
        self.add_field(self.tr("Action"), self.action, required=True)

        self.url = QLineEdit(step.url or "")
        self.url.setPlaceholderText("/checkout")
        self.url_label = self._field(self.tr("Path or URL"), self.url, True)

        self.value = QLineEdit(step.value or "")
        value_row = QWidget()
        row = QHBoxLayout(value_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.value, 1)
        self.insert = IconButton(self.tr("Insert variable"), "braces", "ghost")
        self._build_variable_menu()
        row.addWidget(self.insert)
        self.value_label = self._field(self.tr("Value"), value_row, True)

        self.checked = QCheckBox(self.tr("Expect the element to be checked"))
        self.checked.setChecked(step.checked is not False)
        self.add_widget(self.checked)

        self.timeout = QSpinBox()
        self.timeout.setRange(0, 120_000)
        self.timeout.setSingleStep(1000)
        self.timeout.setSuffix(" ms")
        self.timeout.setSpecialValueText(self.tr("default (10 s)"))
        self.timeout.setValue(step.timeout_ms or 0)
        self.timeout_label = self._field(self.tr("Wait at most"), self.timeout, False)

        self.selectors = QListWidget()
        self.selectors.setMinimumHeight(150)
        for selector in step.target.candidates if step.target else ():
            self._add_selector(selector)
        selector_buttons = QWidget()
        buttons = QHBoxLayout(selector_buttons)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(IconButton(self.tr("Make primary"), "check", "ghost", self._make_primary))
        buttons.addWidget(IconButton(self.tr("Up"), "up", "ghost", lambda: self._move(-1)))
        buttons.addWidget(IconButton(self.tr("Down"), "down", "ghost", lambda: self._move(1)))
        buttons.addWidget(IconButton(self.tr("Remove"), "trash", "danger", self._remove))
        buttons.addStretch()
        buttons.addWidget(IconButton(self.tr("Add CSS selector"), "plus", "secondary", self._add_css))
        self.selectors_label = self._field(self.tr("Selectors"), self.selectors, True)
        self.add_widget(selector_buttons)
        self._selector_buttons = selector_buttons

        self.resolved = QCheckBox(self.tr("Clear the attention note: {note}").format(note=step.note or ""))
        self.resolved.setVisible(bool(step.note))
        self.add_widget(self.resolved)

        self.finish_layout(self.tr("Apply"))
        self._update_visibility()

    def _field(self, label: str, widget: QWidget, required: bool) -> list[QWidget]:
        before = self.layout_.count()
        self.add_field(label, widget, required)
        return [
            self.layout_.itemAt(index).widget()
            for index in range(before, self.layout_.count())
            if self.layout_.itemAt(index).widget()
        ]

    def selected_action(self) -> Action:
        return Action(self.action.currentData())

    def _update_visibility(self) -> None:
        action = self.selected_action()
        for widget in self.url_label:
            widget.setVisible(action is Action.NAVIGATE)
        for widget in self.value_label:
            widget.setVisible(action in VALUE_ACTIONS)
        self.checked.setVisible(action is Action.ASSERT_CHECKED)
        for widget in self.timeout_label:
            widget.setVisible(action in ASSERTIONS)
        targeted = action in TARGETED_ACTIONS
        for widget in self.selectors_label:
            widget.setVisible(targeted)
        self._selector_buttons.setVisible(targeted)
        self.fit_height()

    def _add_selector(self, selector: Selector) -> None:
        item = QListWidgetItem(selector_text(selector))
        item.setData(256, selector)
        self.selectors.addItem(item)
        self._relabel()

    def _relabel(self) -> None:
        for row in range(self.selectors.count()):
            item = self.selectors.item(row)
            role = self.tr("primary") if row == 0 else self.tr("fallback {number}").format(number=row)
            item.setText(f"{role}   ·   {selector_text(item.data(256))}")

    def _selector_list(self) -> list[Selector]:
        return [self.selectors.item(row).data(256) for row in range(self.selectors.count())]

    def _make_primary(self) -> None:
        row = self.selectors.currentRow()
        if row <= 0:
            return
        item = self.selectors.takeItem(row)
        self.selectors.insertItem(0, item)
        self.selectors.setCurrentRow(0)
        self._relabel()

    def _move(self, offset: int) -> None:
        row = self.selectors.currentRow()
        target = row + offset
        if row < 0 or not 0 <= target < self.selectors.count():
            return
        item = self.selectors.takeItem(row)
        self.selectors.insertItem(target, item)
        self.selectors.setCurrentRow(target)
        self._relabel()

    def _remove(self) -> None:
        row = self.selectors.currentRow()
        if row >= 0:
            self.selectors.takeItem(row)
            self._relabel()

    def _add_css(self) -> None:
        text, accepted = QInputDialog.getText(self, self.tr("Add CSS selector"), self.tr("CSS selector"))
        if accepted and text.strip():
            self._add_selector(Selector(SelectorKind.CSS, text.strip()))

    def _build_variable_menu(self) -> None:
        menu = QMenu(self.insert)
        for variable in self._variables:
            reference = reference_text(variable)
            menu.addAction(reference, lambda reference=reference: self.value.insert(reference))
        if self._create_secret is not None:
            if self._variables:
                menu.addSeparator()
            menu.addAction(
                icon("shield", active_tokens().text_secondary, 16), self.tr("New secret…"), self._new_secret
            )
        self.insert.setMenu(menu)
        self.insert.setEnabled(bool(self._variables) or self._create_secret is not None)

    def _missing_secret(self) -> str:
        known = {variable.name for variable in self._variables if variable.is_secret}
        for name in SECRET_REFERENCE.findall(self.value.text()):
            if name not in known:
                return name
        return ""

    def _new_secret(self) -> None:
        if self._create_secret is None:
            return
        variable = self._create_secret(self, self._missing_secret())
        if variable is None:
            return
        self._variables = [item for item in self._variables if item.name != variable.name] + [variable]
        self._build_variable_menu()
        reference = reference_text(variable)
        if reference not in self.value.text():
            self.value.insert(reference)

    def result_step(self) -> Step:
        action = self.selected_action()
        candidates = self._selector_list()
        target = (
            Target(candidates[0], tuple(candidates[1:]))
            if candidates and action in TARGETED_ACTIONS
            else None
        )
        note = None if self.resolved.isChecked() else self._step.note
        return replace(
            self._step,
            action=action,
            url=self.url.text().strip() if action is Action.NAVIGATE else None,
            value=self.value.text() if action in VALUE_ACTIONS else None,
            checked=self.checked.isChecked() if action is Action.ASSERT_CHECKED else None,
            timeout_ms=self.timeout.value() or None if action in ASSERTIONS else None,
            target=target,
            raw=self._step.raw if action is Action.UNKNOWN else None,
            note=note,
        )

    def validate(self) -> tuple[str, QWidget] | None:
        try:
            ir.validate_step(self.result_step())
        except ir.InvalidDocumentError as error:
            action = self.selected_action()
            if action is Action.NAVIGATE:
                widget: QWidget = self.url
            elif action in TARGETED_ACTIONS and not self._selector_list():
                widget = self.selectors
            else:
                widget = self.value
            return str(error), widget
        return None
