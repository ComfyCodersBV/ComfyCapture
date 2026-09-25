"""Headless recording shown in the desktop app.

`Screencast` streams the page as lossless PNG frames over the DevTools protocol; `InputBridge` replays the
viewer's mouse, touch and keyboard input into the page. Input sent this way is trusted, so the injected
recorder sees it exactly as it sees a user in a headed window.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, CDPSession, Page

MOUSE_BUTTONS = frozenset({"none", "left", "middle", "right"})
MOUSE_EVENTS = frozenset({"mousePressed", "mouseReleased", "mouseMoved", "mouseWheel"})
MODIFIER_BITS = {"Alt": 1, "Control": 2, "Meta": 4, "Shift": 8}


class Screencast:
    def __init__(
        self,
        context: BrowserContext,
        page: Page,
        emit: Callable[[dict[str, Any]], None],
        max_size: tuple[int, int],
        quality: int = 100,
    ) -> None:
        self._emit = emit
        self._quality = quality
        self._size = max_size
        self._session: CDPSession = context.new_cdp_session(page)
        self._session.on("Page.screencastFrame", self._on_frame)
        self._start()

    def _start(self) -> None:
        self._session.send(
            "Page.startScreencast",
            {
                "format": "png",
                "quality": self._quality,
                "maxWidth": self._size[0],
                "maxHeight": self._size[1],
            },
        )

    def resize(self, width: int, height: int) -> None:
        size = (max(64, width), max(64, height))
        if size == self._size:
            return
        self._size = size
        self.stop()
        self._start()

    def _on_frame(self, frame: dict[str, Any]) -> None:
        metadata = frame.get("metadata", {})
        self._emit(
            {
                "type": "frame",
                "data": frame.get("data", ""),
                "width": metadata.get("deviceWidth"),
                "height": metadata.get("deviceHeight"),
            }
        )
        try:
            self._session.send("Page.screencastFrameAck", {"sessionId": frame["sessionId"]})
        except Exception:
            return

    def stop(self) -> None:
        try:
            self._session.send("Page.stopScreencast")
        except Exception:
            return


def modifier_mask(modifiers: list[str]) -> int:
    return sum(MODIFIER_BITS.get(name, 0) for name in modifiers)


class InputBridge:
    def __init__(self, context: BrowserContext, page: Page, touch: bool) -> None:
        self._page = page
        self._touch = touch
        self._session: CDPSession = context.new_cdp_session(page)

    def handle(self, command: dict[str, Any]) -> None:
        kind = command.get("type")
        if kind == "mouse":
            self._mouse(command)
            return
        if kind == "text" and command.get("text"):
            self._session.send("Input.insertText", {"text": str(command["text"])})
            return
        if kind == "key" and command.get("key"):
            self._page.keyboard.press(str(command["key"]))
            return
        if kind == "navigate" and command.get("url"):
            self._page.goto(str(command["url"]))
            return
        if kind == "back":
            self._page.go_back()
            return
        if kind == "forward":
            self._page.go_forward()
            return
        if kind == "reload":
            self._page.reload()

    def _mouse(self, command: dict[str, Any]) -> None:
        event = command.get("event")
        if event not in MOUSE_EVENTS:
            return
        button = command.get("button", "none")
        parameters: dict[str, Any] = {
            "type": event,
            "x": int(command.get("x", 0)),
            "y": int(command.get("y", 0)),
            "button": button if button in MOUSE_BUTTONS else "none",
            "modifiers": modifier_mask(list(command.get("modifiers", []))),
            "clickCount": int(command.get("click_count", 0)),
        }
        if event == "mouseWheel":
            parameters["deltaX"] = float(command.get("delta_x", 0))
            parameters["deltaY"] = float(command.get("delta_y", 0))
        method = "Input.emulateTouchFromMouseEvent" if self._touch else "Input.dispatchMouseEvent"
        if self._touch and event == "mouseMoved" and parameters["button"] == "none":
            method = "Input.dispatchMouseEvent"
        self._session.send(method, parameters)
