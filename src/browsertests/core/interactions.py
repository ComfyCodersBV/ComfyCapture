"""Browser prompts that need the person recording: native select menus, dialogs and file choosers.

The page asks, the session sends a request to the desktop, the desktop answers with a command. A
headless page cannot show these itself, and in a headed window Playwright would dismiss dialogs.
"""

from __future__ import annotations

import itertools
import queue
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.sync_api import Dialog, FileChooser, Frame, Page

    from browsertests.core.recorder import Recorder

Emit = Callable[[dict[str, Any]], None]
REPLY_POLL_SECONDS = 0.1
DISMISSED_NOTE = "A {kind} dialog was dismissed while recording; a replay always accepts dialogs."


class Interactions:
    def __init__(
        self,
        recorder: Recorder,
        emit: Emit,
        replies: queue.Queue[dict[str, Any]] | None = None,
        stop: threading.Event | None = None,
    ) -> None:
        self._recorder = recorder
        self._emit = emit
        self._replies = replies if replies is not None else queue.Queue()
        self._stop = stop or threading.Event()
        self._counter = itertools.count(1)
        self._selects: dict[str, Frame] = {}
        self._dialogs: dict[str, Dialog] = {}
        self._choosers: dict[str, FileChooser] = {}

    def watch(self, page: Page, viewer: bool) -> None:
        page.on("dialog", self._on_dialog)
        if viewer:
            page.on("filechooser", self._on_file_chooser)

    def on_select(self, frame: Frame, request: dict[str, Any]) -> None:
        self._selects[str(request.get("id"))] = frame
        self._emit({"type": "select", **request})

    def _on_dialog(self, dialog: Dialog) -> None:
        identifier = f"dialog-{next(self._counter)}"
        self._dialogs[identifier] = dialog
        self._emit(
            {
                "type": "dialog",
                "id": identifier,
                "kind": dialog.type,
                "message": dialog.message,
                "default": dialog.default_value,
            }
        )
        while identifier in self._dialogs:
            if self._stop.is_set():
                self._reply(identifier, False, None)
                return
            try:
                reply = self._replies.get(timeout=REPLY_POLL_SECONDS)
            except queue.Empty:
                continue
            self._reply(str(reply.get("id", "")), bool(reply.get("accept")), reply.get("text"))

    def _on_file_chooser(self, chooser: FileChooser) -> None:
        identifier = f"files-{next(self._counter)}"
        self._choosers[identifier] = chooser
        self._emit({"type": "filechooser", "id": identifier, "multiple": chooser.is_multiple()})

    def handle(self, command: dict[str, Any]) -> bool:
        kind = command.get("type")
        identifier = str(command.get("id", ""))
        if kind == "select_choice":
            self._choose(identifier, [str(value) for value in command.get("values", [])])
            return True
        if kind == "dialog_reply":
            self._reply(identifier, bool(command.get("accept")), command.get("text"))
            return True
        if kind == "files":
            self._files(identifier, [str(path) for path in command.get("paths", [])])
            return True
        return False

    def _choose(self, identifier: str, values: list[str]) -> None:
        frame = self._selects.pop(identifier, None)
        if frame is None:
            return
        handle = frame.evaluate_handle("id => window.__btPending[id]", identifier).as_element()
        if values and handle is not None:
            handle.select_option(values)
        frame.evaluate("id => { delete window.__btPending[id]; }", identifier)

    def _reply(self, identifier: str, accept: bool, text: Any) -> None:
        dialog = self._dialogs.pop(identifier, None)
        if dialog is None:
            return
        if accept:
            dialog.accept(str(text) if text is not None and dialog.type == "prompt" else None)
            return
        dialog.dismiss()
        if dialog.type in ("confirm", "prompt", "beforeunload"):
            self._recorder.note_last_step(DISMISSED_NOTE.format(kind=dialog.type))

    def _files(self, identifier: str, paths: list[str]) -> None:
        chooser = self._choosers.pop(identifier, None)
        if chooser is None or not paths:
            return
        self._recorder.expect_upload(paths)
        chooser.set_files(paths)
