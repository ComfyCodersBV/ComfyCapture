from __future__ import annotations

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from comfycapture.ui.icons import icon
from comfycapture.ui.theme import pill
from comfycapture.ui.widgets import IconButton

KINDS = {
    "question": ("help", "info"),
    "destructive": ("trash", "danger"),
    "info": ("info", "info"),
    "warning": ("alert", "warning"),
    "error": ("error", "danger"),
}


class MessageDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        text: str,
        kind: str,
        accept_text: str,
        cancel_text: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.setMaximumWidth(640)
        icon_name, tone = KINDS[kind]

        badge = QLabel()
        badge.setFixedSize(44, 44)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        colors = pill(tone)
        badge.setStyleSheet(f"background: {colors.background}; border-radius: 22px;")
        badge.setPixmap(icon(icon_name, colors.text, 22).pixmap(22, 22))

        heading = QLabel(title)
        heading.setObjectName("CardTitle")
        heading.setWordWrap(True)
        body = QLabel(text)
        body.setObjectName("MessageText")
        body.setTextFormat(Qt.TextFormat.PlainText)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        texts = QVBoxLayout()
        texts.setSpacing(6)
        texts.addWidget(heading)
        texts.addWidget(body)
        texts.addStretch()

        content = QHBoxLayout()
        content.setSpacing(16)
        content.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        content.addLayout(texts, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch()
        if cancel_text is not None:
            buttons.addWidget(IconButton(cancel_text, variant="ghost", on_click=self.reject))
        variant = "destructive" if kind == "destructive" else "primary"
        accept = IconButton(accept_text, "trash" if kind == "destructive" else None, variant, self.accept)
        accept.setDefault(True)
        accept.setFocus()
        buttons.addWidget(accept)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(22)
        layout.addLayout(content)
        layout.addLayout(buttons)


def confirm(
    parent: QWidget | None, title: str, text: str, accept_text: str, destructive: bool = False
) -> bool:
    dialog = MessageDialog(
        parent,
        title,
        text,
        "destructive" if destructive else "question",
        accept_text,
        QCoreApplication.translate("Messages", "Cancel"),
    )
    return dialog.exec() == QDialog.DialogCode.Accepted


def inform(parent: QWidget | None, title: str, text: str) -> None:
    MessageDialog(parent, title, text, "info", QCoreApplication.translate("Messages", "OK")).exec()


def warn(parent: QWidget | None, title: str, text: str) -> None:
    MessageDialog(parent, title, text, "warning", QCoreApplication.translate("Messages", "OK")).exec()


def fail(parent: QWidget | None, title: str, text: str) -> None:
    MessageDialog(parent, title, text, "error", QCoreApplication.translate("Messages", "OK")).exec()
