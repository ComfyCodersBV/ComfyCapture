from __future__ import annotations

import base64
import time
from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSettings, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QPen,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from browsertests.ui.widgets import IconButton

SPECIAL_KEYS = {
    Qt.Key.Key_Return: "Enter",
    Qt.Key.Key_Enter: "Enter",
    Qt.Key.Key_Backspace: "Backspace",
    Qt.Key.Key_Tab: "Tab",
    Qt.Key.Key_Backtab: "Tab",
    Qt.Key.Key_Escape: "Escape",
    Qt.Key.Key_Delete: "Delete",
    Qt.Key.Key_Left: "ArrowLeft",
    Qt.Key.Key_Right: "ArrowRight",
    Qt.Key.Key_Up: "ArrowUp",
    Qt.Key.Key_Down: "ArrowDown",
    Qt.Key.Key_Home: "Home",
    Qt.Key.Key_End: "End",
    Qt.Key.Key_PageUp: "PageUp",
    Qt.Key.Key_PageDown: "PageDown",
}
MOUSE_BUTTONS = {
    Qt.MouseButton.LeftButton: "left",
    Qt.MouseButton.RightButton: "right",
    Qt.MouseButton.MiddleButton: "middle",
}
MOVE_INTERVAL = 1 / 30
INVERT_SCROLL_KEY = "viewer/invert_scroll"
MAX_SCALE = 1.5
MARGIN = 28


def modifier_names(modifiers: Qt.KeyboardModifier) -> list[str]:
    names = []
    for flag, name in (
        (Qt.KeyboardModifier.ControlModifier, "Control"),
        (Qt.KeyboardModifier.AltModifier, "Alt"),
        (Qt.KeyboardModifier.ShiftModifier, "Shift"),
        (Qt.KeyboardModifier.MetaModifier, "Meta"),
    ):
        if modifiers & flag:
            names.append(name)
    return names


class DeviceViewer(QWidget):
    command = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(320, 360)
        self._image: QImage | None = None
        self._css_width = 393
        self._css_height = 659
        self._mobile = True
        self._last_move = 0.0
        self._requested_size: tuple[int, int] | None = None
        self.invert_scroll = QSettings().value(INVERT_SCROLL_KEY, False, bool)
        self._size_timer = QTimer(self)
        self._size_timer.setSingleShot(True)
        self._size_timer.setInterval(200)
        self._size_timer.timeout.connect(self._request_frame_size)

    def set_device(self, width: int, height: int, mobile: bool) -> None:
        self._css_width = max(1, width)
        self._css_height = max(1, height)
        self._mobile = mobile
        self.setCursor(Qt.CursorShape.PointingHandCursor if mobile else Qt.CursorShape.ArrowCursor)
        self._requested_size = None
        self._size_timer.start()
        self.update()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._size_timer.start()

    def _request_frame_size(self) -> None:
        screen = self.screen_rect()
        ratio = self.devicePixelRatioF()
        size = (round(screen.width() * ratio), round(screen.height() * ratio))
        if size == self._requested_size:
            return
        self._requested_size = size
        self.command.emit({"type": "screencast_size", "width": size[0], "height": size[1]})

    def show_frame(self, data: str) -> None:
        image = QImage.fromData(base64.b64decode(data))
        if image.isNull():
            return
        image.setDevicePixelRatio(self.devicePixelRatioF())
        self._image = image
        self.update()

    def bezel(self) -> float:
        return 7.0 if self._mobile else 5.0

    def screen_rect(self) -> QRectF:
        bezel = self.bezel()
        ratio = self.devicePixelRatioF()
        available_width = self.width() - 2 * (MARGIN + bezel)
        available_height = self.height() - 2 * (MARGIN + bezel)
        scale = min(available_width / self._css_width, available_height / self._css_height, MAX_SCALE)
        scale = max(scale, 0.1)
        width = round(self._css_width * scale * ratio) / ratio
        height = round(self._css_height * scale * ratio) / ratio
        left = round((self.width() - width) / 2 * ratio) / ratio
        top = round((self.height() - height) / 2 * ratio) / ratio
        return QRectF(left, top, width, height)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        screen = self.screen_rect()
        bezel = self.bezel()
        body = screen.adjusted(-bezel, -bezel, bezel, bezel)
        body_radius = 16.0 if self._mobile else 8.0
        screen_radius = 10.0 if self._mobile else 3.0
        background = self.palette().color(QPalette.ColorRole.Window)
        dark = background.lightness() < 128
        frame = QColor("#2b2b36") if dark else QColor("#dcdce6")
        outline = QColor("#3a3a48") if dark else QColor("#c8c8d4")

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 70 if dark else 22))
        painter.drawRoundedRect(body.translated(0, 4), body_radius, body_radius)
        painter.setBrush(frame)
        painter.setPen(QPen(outline, 1))
        painter.drawRoundedRect(body, body_radius, body_radius)

        clip = QPainterPath()
        clip.addRoundedRect(screen, screen_radius, screen_radius)
        painter.setClipPath(clip)
        painter.fillRect(screen, QColor("#ffffff"))
        if self._image is not None:
            ratio = self.devicePixelRatioF()
            natural = QSizeF(self._image.width() / ratio, self._image.height() / ratio)
            if abs(natural.width() - screen.width()) <= 1 and abs(natural.height() - screen.height()) <= 1:
                painter.drawImage(screen.topLeft(), self._image)
            else:
                painter.drawImage(screen, self._image)
        painter.end()

    def _css_point(self, position: QPointF) -> tuple[int, int] | None:
        screen = self.screen_rect()
        if not screen.contains(position):
            return None
        x = (position.x() - screen.left()) * self._css_width / screen.width()
        y = (position.y() - screen.top()) * self._css_height / screen.height()
        return int(x), int(y)

    def _send_mouse(self, event: QMouseEvent, kind: str, click_count: int = 0) -> None:
        point = self._css_point(event.position())
        if point is None:
            return
        button = MOUSE_BUTTONS.get(event.button(), "none")
        if kind == "mouseMoved":
            button = "left" if event.buttons() & Qt.MouseButton.LeftButton else "none"
        self.command.emit(
            {
                "type": "mouse",
                "event": kind,
                "x": point[0],
                "y": point[1],
                "button": button,
                "click_count": click_count,
                "modifiers": modifier_names(event.modifiers()),
            }
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setFocus()
        self._send_mouse(event, "mousePressed", 1)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self._send_mouse(event, "mousePressed", 2)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._send_mouse(event, "mouseReleased", 1)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        now = time.monotonic()
        dragging = bool(event.buttons() & Qt.MouseButton.LeftButton)
        if not dragging and now - self._last_move < MOVE_INTERVAL:
            return
        self._last_move = now
        self._send_mouse(event, "mouseMoved")

    def wheelEvent(self, event: QWheelEvent) -> None:
        point = self._css_point(event.position())
        if point is None:
            return
        delta = event.angleDelta()
        direction = 1 if self.invert_scroll else -1
        self.command.emit(
            {
                "type": "mouse",
                "event": "mouseWheel",
                "x": point[0],
                "y": point[1],
                "delta_x": direction * delta.x(),
                "delta_y": direction * delta.y(),
            }
        )

    def set_invert_scroll(self, inverted: bool) -> None:
        self.invert_scroll = inverted
        QSettings().setValue(INVERT_SCROLL_KEY, inverted)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        command = self.key_command(event)
        if command is not None:
            self.command.emit(command)

    def key_command(self, event: QKeyEvent) -> dict[str, Any] | None:
        modifiers = modifier_names(event.modifiers())
        key = Qt.Key(event.key())
        if key in SPECIAL_KEYS:
            return {"type": "key", "key": "+".join([*modifiers, SPECIAL_KEYS[key]])}
        shortcut = [name for name in modifiers if name in ("Control", "Meta")]
        if shortcut and key == Qt.Key.Key_V:
            text = QGuiApplication.clipboard().text()
            return {"type": "text", "text": text} if text else None
        if shortcut and Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            return {"type": "key", "key": "+".join([*shortcut, chr(key).lower()])}
        text = event.text()
        if text and text.isprintable():
            return {"type": "text", "text": text}
        return None

    def focusNextPrevChild(self, _next: bool) -> bool:
        return False


class ViewerBar(QWidget):
    command = Signal(dict)

    def __init__(self, base_url: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._base_url = base_url.rstrip("/")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for icon_name, kind, tip in (
            ("back", "back", self.tr("Back")),
            ("forward", "forward", self.tr("Forward")),
            ("reload", "reload", self.tr("Reload")),
        ):
            button = IconButton("", icon_name, "ghost", lambda kind=kind: self.command.emit({"type": kind}))
            button.setToolTip(tip)
            layout.addWidget(button)
        self.address = QLineEdit()
        self.address.setPlaceholderText(self.tr("Type a URL or a path and press Enter"))
        self.address.returnPressed.connect(self._navigate)
        layout.addWidget(self.address, 1)
        self.invert_scroll = IconButton(self.tr("Invert scrolling"), "scroll", "ghost")
        self.invert_scroll.setCheckable(True)
        self.invert_scroll.setToolTip(
            self.tr("Scroll like on a touch screen: the page follows the direction of your fingers.")
        )
        layout.addWidget(self.invert_scroll)

    def set_location(self, url: str) -> None:
        if not self.address.hasFocus():
            self.address.setText(url)

    def _navigate(self) -> None:
        text = self.address.text().strip()
        if not text:
            return
        url = text if "://" in text else f"{self._base_url}/{text.lstrip('/')}"
        self.command.emit({"type": "navigate", "url": url})
        self.address.clearFocus()


class DevicePanel(QWidget):
    command = Signal(dict)

    def __init__(self, base_url: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.bar = ViewerBar(base_url)
        self.viewer = DeviceViewer()
        self.bar.invert_scroll.setChecked(self.viewer.invert_scroll)
        self.bar.invert_scroll.toggled.connect(self.viewer.set_invert_scroll)
        self.bar.command.connect(self.command.emit)
        self.viewer.command.connect(self.command.emit)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.bar)
        layout.addWidget(self.viewer, 1)
