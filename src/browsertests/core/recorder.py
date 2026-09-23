from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from importlib import resources
from typing import TYPE_CHECKING, Any

from browsertests.core.models import Step
from browsertests.core.sanitizer import RecordedEvent, StepBuilder

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Frame, Page

PICK_MODES = frozenset({"record", "assertVisible", "assertText", "assertValue", "assertChecked", "hover"})


def recorder_script() -> str:
    return resources.files("browsertests.core").joinpath("recorder.js").read_text(encoding="utf-8")


class Recorder:
    def __init__(
        self,
        context: BrowserContext,
        base_url: str,
        test_id_attributes: tuple[str, ...],
        mobile: bool = False,
        steps: Iterable[Step] = (),
        on_change: Callable[[tuple[Step, ...]], None] | None = None,
        toolbar: bool = True,
    ) -> None:
        self._context = context
        self._builder = StepBuilder(base_url, test_id_attributes, mobile=mobile, steps=steps)
        self._on_change = on_change
        self._pages: list[Page] = []
        self._config = {"testIdAttributes": list(test_id_attributes), "toolbar": toolbar}
        self.recording = False
        self.mode = "record"

    @property
    def steps(self) -> tuple[Step, ...]:
        return self._builder.steps

    def install(self) -> None:
        self._context.add_init_script(
            script=f"window.__btConfig = {json.dumps(self._config)};\n{recorder_script()}"
        )
        self._context.expose_binding("__btEmit", self._on_emit)
        self._context.expose_binding("__btState", lambda source: {"mode": self.mode})
        self._context.expose_binding("__btSetMode", self._on_set_mode)
        self._context.on("page", self.track)
        for page in self._context.pages:
            self.track(page)

    def track(self, page: Page) -> None:
        if page in self._pages:
            return
        self._pages.append(page)
        page.on("framenavigated", lambda frame: self._on_navigated(page, frame))

    def _page_index(self, page: Page | None) -> int:
        if page is None or page not in self._pages:
            return 0
        return self._pages.index(page)

    def _on_emit(self, source: dict[str, Any], payload: dict[str, Any]) -> None:
        if not self.recording or not isinstance(payload, dict):
            return
        event = RecordedEvent.from_payload(payload, self._page_index(source.get("page")))
        if self._builder.add(event):
            self._changed()

    def _on_set_mode(self, source: dict[str, Any], mode: str) -> None:
        if mode in PICK_MODES:
            self.mode = mode

    def _on_navigated(self, page: Page, frame: Frame) -> None:
        if not self.recording or frame != page.main_frame:
            return
        if self._builder.navigation(frame.url, time.time() * 1000, self._page_index(page)):
            self._changed()

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change(self._builder.steps)
