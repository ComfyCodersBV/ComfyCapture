from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from browsertests.ui.icons import icon


class IconButton(QPushButton):
    def __init__(
        self,
        text: str,
        icon_name: str | None = None,
        variant: str = "secondary",
        on_click: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._icon_name = icon_name
        self.setProperty("variant", variant)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if on_click is not None:
            self.clicked.connect(on_click)
        self._render_icon()

    def _render_icon(self) -> None:
        if self._icon_name is None:
            return
        if self.property("variant") == "primary":
            color = "#ffffff"
        else:
            color = self.palette().color(QPalette.ColorRole.ButtonText).name()
        self.setIcon(icon(self._icon_name, color, 16))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange):
            self._render_icon()


class Card(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("CardTitle")
        heading.addWidget(self.title)
        if subtitle:
            self.subtitle = QLabel(subtitle)
            self.subtitle.setObjectName("Muted")
            self.subtitle.setWordWrap(True)
            heading.addWidget(self.subtitle)
        self.header.addLayout(heading, 1)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 16)
        self.body.setSpacing(12)
        self.body.addLayout(self.header)

    def add_action(self, widget: QWidget) -> None:
        self.header.addWidget(widget, 0, Qt.AlignmentFlag.AlignTop)


def data_table(parent: QWidget, headers: list[str], stretch_column: int | None = None) -> QTableWidget:
    table = QTableWidget(0, len(headers), parent)
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    table.horizontalHeader().setHighlightSections(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(38)
    table.setShowGrid(False)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    table.setWordWrap(False)
    if stretch_column is not None:
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)
    return table


def fit_rows(table: QTableWidget, minimum_rows: int, maximum_rows: int) -> None:
    rows = max(minimum_rows, min(table.rowCount(), maximum_rows))
    header = table.horizontalHeader().sizeHint().height()
    table.setFixedHeight(header + rows * table.verticalHeader().defaultSectionSize() + 4)


class SelectionGate(QObject):
    def __init__(self, table: QTableWidget, buttons: tuple[QPushButton, ...]) -> None:
        super().__init__(table)
        self._table = table
        self._buttons = buttons
        table.selectionModel().selectionChanged.connect(self.update)
        table.model().modelReset.connect(self.update)
        table.model().rowsRemoved.connect(self.update)
        self.update()

    def update(self) -> None:
        if not isValid(self._table):
            return
        selected = bool(self._table.selectionModel().selectedRows())
        for button in self._buttons:
            if isValid(button):
                button.setEnabled(selected)


def enable_with_selection(table: QTableWidget, *buttons: QPushButton) -> SelectionGate:
    return SelectionGate(table, buttons)


def field_label(text: str, required: bool) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    layout.addWidget(QLabel(text))
    marker = QLabel("*" if required else QCoreApplication.translate("Form", "optional"))
    marker.setObjectName("Required" if required else "Optional")
    layout.addWidget(marker)
    layout.addStretch()
    return widget


def hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("FieldHint")
    label.setWordWrap(True)
    return label


def muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(True)
    return label
