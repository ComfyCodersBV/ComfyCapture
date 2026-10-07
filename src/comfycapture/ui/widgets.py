from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import (
    QCompleter,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from comfycapture.ui.icons import icon
from comfycapture.ui.theme import active_tokens, heading_font, pill

PILL_ROLE = Qt.ItemDataRole.UserRole + 1


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
        self.setIcon(icon(self._icon_name, self._icon_color(), 16))

    def _icon_color(self) -> str:
        variant = self.property("variant")
        if variant == "primary":
            return active_tokens().accent_text
        if variant == "danger":
            return active_tokens().danger
        if variant == "secondary":
            return active_tokens().text
        return self.palette().color(QPalette.ColorRole.ButtonText).name()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange):
            self._render_icon()


class Card(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.header = QHBoxLayout()
        self.header.setSpacing(4)
        heading = QVBoxLayout()
        heading.setSpacing(4)
        self.title = QLabel(title)
        self.title.setObjectName("CardTitle")
        heading.addWidget(self.title)
        if subtitle:
            self.subtitle = QLabel(subtitle)
            self.subtitle.setObjectName("Muted")
            self.subtitle.setWordWrap(True)
            self.subtitle.setMinimumWidth(140)
            heading.addWidget(self.subtitle)
        self.header.addLayout(heading, 1)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(24, 22, 24, 22)
        self.body.setSpacing(16)
        self.body.addLayout(self.header)

    def add_action(self, widget: QWidget) -> None:
        self.header.addWidget(widget, 0, Qt.AlignmentFlag.AlignTop)


class PillDelegate(QStyledItemDelegate):
    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        tone = index.data(PILL_ROLE)
        if tone is None:
            super().paint(painter, option, index)
            return
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        background.text = ""
        widget = background.widget
        style = widget.style() if widget is not None else None
        if style is not None:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, background, painter, widget)
        self._paint_pill(painter, option, str(tone), str(index.data(Qt.ItemDataRole.DisplayRole) or ""))

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> QSize:
        size = super().sizeHint(option, index)
        if index.data(PILL_ROLE) is None:
            return size
        return QSize(size.width() + 28 + (12 if pill(str(index.data(PILL_ROLE))).dot else 0), size.height())

    def _paint_pill(self, painter: QPainter, option: QStyleOptionViewItem, tone: str, text: str) -> None:
        colors = pill(tone)
        font = QFont(option.font)
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.Medium)
        metrics = QFontMetrics(font)
        dot_space = 12 if colors.dot else 0
        width = metrics.horizontalAdvance(text) + 22 + dot_space
        height = 24
        left = option.rect.left() + 12
        top = option.rect.center().y() - height / 2 + 1
        shape = QRectF(left, top, min(width, option.rect.width() - 16), height)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors.background))
        painter.drawRoundedRect(shape, height / 2, height / 2)
        if colors.dot:
            painter.setBrush(QColor(colors.dot))
            painter.drawEllipse(QRectF(shape.left() + 10, shape.center().y() - 3, 6, 6))
        painter.setFont(font)
        painter.setPen(QColor(colors.text))
        painter.drawText(
            shape.adjusted(10 + dot_space, 0, -10, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(shape.width()) - 20 - dot_space),
        )
        painter.restore()


def pill_item(text: str, tone: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setToolTip(text)
    item.setData(PILL_ROLE, tone)
    return item


def data_table(parent: QWidget, headers: list[str], stretch_column: int | None = None) -> QTableWidget:
    table = QTableWidget(0, len(headers), parent)
    table.setHorizontalHeaderLabels([header.upper() for header in headers])
    table.horizontalHeader().setFont(heading_font(11, QFont.Weight.DemiBold, 10))
    table.setItemDelegate(PillDelegate(table))
    table.setMouseTracking(True)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    table.horizontalHeader().setHighlightSections(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(46)
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


class TagCompleter(QCompleter):
    def __init__(self, tags: list[str], parent: QObject | None = None) -> None:
        super().__init__(tags, parent)
        self.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterMode(Qt.MatchFlag.MatchContains)

    def splitPath(self, path: str) -> list[str]:
        return [path.split(",")[-1].strip()]

    def pathFromIndex(self, index: QModelIndex | QPersistentModelIndex) -> str:
        chosen = str(index.data())
        widget = self.widget()
        text = widget.text() if isinstance(widget, QLineEdit) else ""
        head = [part.strip() for part in text.split(",")[:-1] if part.strip()]
        return ", ".join([*head, chosen])


def attach_tag_completer(field: QLineEdit, tags: list[str]) -> None:
    if tags:
        field.setCompleter(TagCompleter(tags, field))
