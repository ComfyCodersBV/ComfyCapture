from __future__ import annotations

import contextlib
import re
import sqlite3

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from comfycapture.core import db, ir
from comfycapture.core.models import Project, Variable
from comfycapture.core.secrets import SecretStore, environment_key
from comfycapture.ui.dialogs import FormDialog
from comfycapture.ui.widgets import Card, IconButton, data_table, enable_with_selection, muted

NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")
SECRET_PREFIX = "secret:"


def references(connection: sqlite3.Connection, project_id: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for stored in db.TestRepository(connection).for_project(project_id):
        for name in ir.placeholders(stored.test):
            counts[name] = counts.get(name, 0) + 1
    return counts


def reference_key(variable: Variable) -> str:
    return f"{SECRET_PREFIX}{variable.name}" if variable.is_secret else variable.name


class VariableDialog(FormDialog):
    def __init__(
        self,
        variable: Variable | None = None,
        secret: bool = False,
        name: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        editing = variable is not None
        self.set_heading(
            self.tr("Edit variable") if editing else self.tr("New variable"),
            self.tr("Use it in a step value as {{name}}, or {{secret:name}} for a secret."),
        )
        self.name = QLineEdit(variable.name if variable else name)
        self.name.setReadOnly(editing)
        self.secret = QCheckBox(
            self.tr("Secret: stored in the operating system's keychain, never in the database")
        )
        self.secret.setChecked(variable.is_secret if variable else secret)
        self.secret.setEnabled(not editing)
        self.value = QLineEdit(variable.value or "" if variable and not variable.is_secret else "")
        self.secret.toggled.connect(self._toggle_echo)
        self._toggle_echo(self.secret.isChecked())
        self._keep_secret = editing and variable is not None and variable.is_secret
        self.add_field(self.tr("Name"), self.name, required=True)
        self.add_widget(self.secret)
        self.add_field(
            self.tr("Value"),
            self.value,
            required=not self._keep_secret,
            help_text=self.tr("Leave empty to keep the stored secret.") if self._keep_secret else "",
        )
        self.finish_layout(self.tr("Save variable"))

    def _toggle_echo(self, secret: bool) -> None:
        self.value.setEchoMode(QLineEdit.EchoMode.Password if secret else QLineEdit.EchoMode.Normal)

    def validate(self) -> tuple[str, QWidget] | None:
        if not NAME_PATTERN.fullmatch(self.name.text().strip()):
            return self.tr("A name starts with a letter and contains letters, digits, _ . or -."), self.name
        if self.secret.isChecked() and not self._keep_secret and not self.value.text():
            return self.tr("A new secret needs a value."), self.value
        return None

    def result_variable(self) -> Variable:
        return Variable(self.name.text().strip(), self.value.text(), self.secret.isChecked())


class VariablesDialog(QDialog):
    def __init__(
        self, connection: sqlite3.Connection, project: Project, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Variables and secrets"))
        self.resize(900, 560)
        self._connection = connection
        self._project = project
        self._variables = db.VariableRepository(connection)
        self._secrets = SecretStore(project.slug)
        self._shown: list[Variable] = []

        title = QLabel(self.tr("Variables and secrets"))
        title.setObjectName("PageTitle")
        intro = muted(
            self.tr(
                "Values that change per project, such as an order number or a login. Tests refer to them by "
                "name, so the value never ends up in a test or an export. On a server, a secret comes from the "
                "environment variable shown in the table."
            )
        )
        self.missing = QLabel()
        self.missing.setObjectName("Required")
        self.missing.setWordWrap(True)

        self.table = data_table(
            self,
            [self.tr("Name"), self.tr("Type"), self.tr("Value"), self.tr("Used by"), self.tr("On a server")],
            4,
        )
        self.table.doubleClicked.connect(self._edit)
        card = Card(self.tr("Variables"))
        edit = IconButton(self.tr("Edit"), "edit", "ghost", self._edit)
        delete = IconButton(self.tr("Delete"), "trash", "danger", self._delete)
        card.add_action(edit)
        card.add_action(delete)
        card.add_action(
            IconButton(self.tr("Add secret"), "shield", "secondary", lambda: self._add(secret=True))
        )
        card.add_action(
            IconButton(self.tr("Add variable"), "plus", "primary", lambda: self._add(secret=False))
        )
        enable_with_selection(self.table, edit, delete)
        card.body.addWidget(self.missing)
        card.body.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(IconButton(self.tr("Close"), variant="ghost", on_click=self.accept))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addWidget(card, 1)
        layout.addLayout(buttons)
        self._load()

    def _load(self) -> None:
        project_id = self._project.id or 0
        self._shown = self._variables.for_project(project_id)
        used = references(self._connection, project_id)
        self.table.setRowCount(len(self._shown))
        for row, variable in enumerate(self._shown):
            if variable.is_secret:
                kind = self.tr("Secret")
                value = (
                    self.tr("•••••• in keychain")
                    if self._secret_stored(variable.name)
                    else self.tr("not set")
                )
                server = environment_key(variable.name)
            else:
                kind = self.tr("Variable")
                value = variable.value or ""
                server = self.tr("stored with the project")
            cells = (variable.name, kind, value, str(used.get(reference_key(variable), 0)), server)
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        defined = {reference_key(variable) for variable in self._shown}
        missing = sorted(name for name in used if name not in defined)
        self.missing.setVisible(bool(missing))
        self.missing.setText(
            self.tr("Used by tests but not defined yet: {names}").format(names=", ".join(missing))
        )

    def _secret_stored(self, name: str) -> bool:
        try:
            return self._secrets.has(name)
        except Exception:
            return False

    def _selected(self) -> Variable | None:
        rows = self.table.selectionModel().selectedRows()
        return self._shown[rows[0].row()] if rows else None

    def _add(self, secret: bool) -> None:
        dialog = VariableDialog(secret=secret, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._store(dialog.result_variable(), keep_secret=False)

    def _edit(self) -> None:
        variable = self._selected()
        if variable is None:
            return
        dialog = VariableDialog(variable, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            result = dialog.result_variable()
            self._store(result, keep_secret=result.is_secret and not result.value)

    def _store(self, variable: Variable, keep_secret: bool) -> None:
        if variable.is_secret and not keep_secret:
            try:
                self._secrets.set(variable.name, variable.value or "")
            except Exception as error:
                QMessageBox.critical(
                    self,
                    self.windowTitle(),
                    self.tr("The keychain refused to store the secret: {error}").format(error=error),
                )
                return
        self._variables.save(self._project.id or 0, variable)
        self._load()

    def _delete(self) -> None:
        variable = self._selected()
        if variable is None:
            return
        answer = QMessageBox.question(
            self, self.tr("Delete variable"), self.tr("Delete {name}?").format(name=variable.name)
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if variable.is_secret:
            with contextlib.suppress(Exception):
                self._secrets.delete(variable.name)
        self._variables.delete(self._project.id or 0, variable.name)
        self._load()
