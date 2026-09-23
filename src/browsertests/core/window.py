"""Keeps a headed recording window at the size of the chosen device.

Playwright cannot make a browser window non-resizable, so the lock sizes the window around the emulated
viewport through the Chrome DevTools Protocol and restores that size whenever the window is maximised,
made full screen or resized. Chromium refuses windows narrower than about 500 pixels; for a phone the
lock keeps the size Chromium accepted, and the strip beside the emulated viewport is not part of the page.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, CDPSession, Page

NORMAL = "normal"


def window_chrome(browser: Browser) -> tuple[int, int]:
    context = browser.new_context(no_viewport=True)
    try:
        page = context.new_page()
        width, height = page.evaluate(
            "[window.outerWidth - window.innerWidth, window.outerHeight - window.innerHeight]"
        )
        return int(width), int(height)
    finally:
        context.close()


class WindowLock:
    def __init__(self, session: CDPSession, window_id: int, width: int, height: int) -> None:
        self._session = session
        self._window_id = window_id
        self._width = width
        self._height = height

    @classmethod
    def create(
        cls, browser: Browser, context: BrowserContext, page: Page, viewport: tuple[int, int]
    ) -> WindowLock | None:
        try:
            chrome_width, chrome_height = window_chrome(browser)
            session = context.new_cdp_session(page)
            window = session.send("Browser.getWindowForTarget")
            lock = cls(
                session, int(window["windowId"]), viewport[0] + chrome_width, viewport[1] + chrome_height
            )
            lock.enforce()
            lock.accept_clamped_size()
        except Exception:
            return None
        return lock

    def accept_clamped_size(self) -> None:
        bounds = self._session.send("Browser.getWindowBounds", {"windowId": self._window_id})["bounds"]
        self._width = int(bounds.get("width", self._width))
        self._height = int(bounds.get("height", self._height))

    def enforce(self) -> None:
        try:
            bounds: dict[str, Any] = self._session.send(
                "Browser.getWindowBounds", {"windowId": self._window_id}
            )["bounds"]
        except Exception:
            return
        if bounds.get("windowState") == NORMAL and (bounds.get("width"), bounds.get("height")) == (
            self._width,
            self._height,
        ):
            return
        if bounds.get("windowState") != NORMAL:
            self._set({"windowState": NORMAL})
        self._set({"width": self._width, "height": self._height})

    def _set(self, bounds: dict[str, Any]) -> None:
        try:
            self._session.send("Browser.setWindowBounds", {"windowId": self._window_id, "bounds": bounds})
        except Exception:
            return
