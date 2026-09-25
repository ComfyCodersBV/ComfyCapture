"""Recording session subprocess.

Run as `python -m comfycapture.core.session <payload.json>`. Writes JSON lines to stdout
(`status`, `replayed`, `steps`, `error`, `done`) and stops when it reads `stop` on stdin or when the
browser is closed. Keeping the browser in its own process keeps the desktop event loop free.
"""

from __future__ import annotations

import json
import queue
import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from comfycapture.core import ir, runner
from comfycapture.core.interactions import Interactions
from comfycapture.core.models import Device, EnvironmentConfig, SelectorKind, Step
from comfycapture.core.recorder import Recorder
from comfycapture.core.screencast import InputBridge, Screencast
from comfycapture.core.secrets import SecretStore
from comfycapture.core.window import WindowLock

POLL_MS = 100
VIEWER_POLL_MS = 15
VIEWER_RENDER_SCALE = 3


@dataclass(frozen=True, slots=True)
class SessionPayload:
    base_url: str
    test_id_attributes: tuple[str, ...]
    project_slug: str = ""
    start_path: str = "/"
    device: Device = field(default_factory=Device)
    environment: EnvironmentConfig = field(default_factory=EnvironmentConfig)
    steps: tuple[Step, ...] = ()
    variables: dict[str, str] = field(default_factory=dict)
    headless: bool = False
    viewer: bool = False
    selector_kinds: tuple[SelectorKind, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "test_id_attributes": list(self.test_id_attributes),
            "project_slug": self.project_slug,
            "start_path": self.start_path,
            "device": ir.device_to_dict(self.device),
            "environment": {
                "locale": self.environment.locale,
                "timezone": self.environment.timezone,
                "ignore_https_errors": self.environment.ignore_https_errors,
                "http_credentials": self.environment.http_credentials,
            },
            "steps": [ir.step_to_dict(step) for step in self.steps],
            "variables": self.variables,
            "headless": self.headless,
            "viewer": self.viewer,
            "selector_kinds": None
            if self.selector_kinds is None
            else [kind.value for kind in self.selector_kinds],
        }

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> SessionPayload:
        return cls(
            base_url=document["base_url"],
            test_id_attributes=tuple(document.get("test_id_attributes") or ("data-testid",)),
            project_slug=document.get("project_slug", ""),
            start_path=document.get("start_path") or "/",
            device=ir.device_from_dict(document.get("device")),
            environment=EnvironmentConfig(**(document.get("environment") or {})),
            steps=tuple(ir.step_from_dict(step) for step in document.get("steps", [])),
            variables=dict(document.get("variables") or {}),
            headless=bool(document.get("headless", False)),
            viewer=bool(document.get("viewer", False)),
            selector_kinds=None
            if document.get("selector_kinds") is None
            else tuple(SelectorKind(kind) for kind in document["selector_kinds"]),
        )


def emit(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def outcome_to_dict(outcome: runner.StepOutcome) -> dict[str, Any]:
    return {
        "step_id": outcome.step_id,
        "passed": outcome.passed,
        "duration_ms": outcome.duration_ms,
        "selector_index": outcome.selector_index,
        "message": outcome.message,
    }


def watch_stdin(
    commands: queue.Queue[dict[str, Any]],
    stop: threading.Event,
    replies: queue.Queue[dict[str, Any]] | None = None,
) -> None:
    for line in sys.stdin:
        text = line.strip()
        if text == "stop":
            break
        try:
            command = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(command, dict):
            continue
        if command.get("type") == "dialog_reply" and replies is not None:
            replies.put(command)
            continue
        commands.put(command)
    stop.set()


def drain(
    commands: queue.Queue[dict[str, Any]],
    bridge: InputBridge | None,
    recorder: Recorder,
    screencast: Screencast | None = None,
    interactions: Interactions | None = None,
) -> None:
    while True:
        try:
            command = commands.get_nowait()
        except queue.Empty:
            return
        try:
            if interactions is not None and interactions.handle(command):
                continue
            if bridge is None:
                continue
            if command.get("type") == "screencast_size" and screencast is not None:
                screencast.resize(int(command.get("width", 0)), int(command.get("height", 0)))
                continue
            if command.get("type") == "navigate" and command.get("url"):
                recorder.request_navigation(str(command["url"]))
            bridge.handle(command)
        except Exception as error:
            emit({"type": "error", "message": runner.first_line(str(error))})


def record(
    payload: SessionPayload,
    stop: threading.Event,
    commands: queue.Queue[dict[str, Any]] | None = None,
    replies: queue.Queue[dict[str, Any]] | None = None,
) -> tuple[Step, ...]:
    from playwright.sync_api import sync_playwright

    secrets = SecretStore(payload.project_slug)
    resolver = runner.VariableResolver(payload.variables, secrets.get)

    commands = commands if commands is not None else queue.Queue()
    fullscreen = payload.device.fullscreen and not payload.device.is_mobile
    viewer = payload.viewer and not fullscreen
    with sync_playwright() as playwright:
        arguments = ["--start-maximized"] if fullscreen else []
        if viewer:
            arguments.append(f"--force-device-scale-factor={VIEWER_RENDER_SCALE}")
        browser = playwright.chromium.launch(headless=payload.headless or viewer, args=arguments)
        options = runner.context_options(
            playwright, payload.device, payload.environment, fit_window=fullscreen
        )
        context = browser.new_context(**options)
        recorder = Recorder(
            context,
            payload.base_url,
            payload.test_id_attributes,
            mobile=payload.device.is_mobile,
            steps=payload.steps,
            selector_kinds=payload.selector_kinds,
            viewer=viewer,
            on_select=lambda frame, request: interactions.on_select(frame, request),
            on_cursor=lambda cursor: emit({"type": "cursor", "cursor": cursor}),
            on_change=lambda steps: emit(
                {"type": "steps", "steps": [ir.step_to_dict(step) for step in steps]}
            ),
        )
        interactions = Interactions(recorder, emit, replies, stop)
        recorder.install()
        page = context.new_page()
        interactions.watch(page, viewer)
        context.on(
            "page",
            lambda opened: (
                emit(
                    {
                        "type": "notice",
                        "message": "The site opened a new tab or popup. Actions there are not recorded yet.",
                    }
                )
                if opened != page
                else None
            ),
        )

        lock = None
        bridge = None
        screencast = None
        if viewer:
            size = options.get("viewport") or {"width": payload.device.width, "height": payload.device.height}
            screencast = Screencast(context, page, emit, (size["width"] * 2, size["height"] * 2))
            bridge = InputBridge(context, page, touch=bool(options.get("has_touch")))
            page.on(
                "framenavigated",
                lambda frame: (
                    emit({"type": "location", "url": frame.url}) if frame == page.main_frame else None
                ),
            )
            emit(
                {
                    "type": "viewer",
                    "width": size["width"],
                    "height": size["height"],
                    "mobile": payload.device.is_mobile,
                }
            )
        if not fullscreen and not payload.headless and not viewer:
            viewport = options.get("viewport") or {
                "width": payload.device.width,
                "height": payload.device.height,
            }
            lock = WindowLock.create(browser, context, page, (viewport["width"], viewport["height"]))

        if payload.steps:
            emit({"type": "status", "status": "replaying"})
            outcomes = runner.replay(
                page,
                payload.steps,
                payload.base_url,
                resolver,
                on_step=lambda outcome: emit({"type": "replayed", "outcome": outcome_to_dict(outcome)}),
            )
            if outcomes and not outcomes[-1].passed:
                emit(
                    {
                        "type": "error",
                        "message": f"Replay failed at step {outcomes[-1].step_id}: {outcomes[-1].message}",
                    }
                )
            recorder.recording = True
        else:
            recorder.recording = True
            page.goto(runner.absolute_url(payload.start_path, payload.base_url))

        emit({"type": "status", "status": "recording"})
        emit({"type": "steps", "steps": [ir.step_to_dict(step) for step in recorder.steps]})

        while not stop.is_set() and browser.is_connected():
            open_pages = [candidate for candidate in context.pages if not candidate.is_closed()]
            if not open_pages:
                break
            try:
                open_pages[0].wait_for_timeout(VIEWER_POLL_MS if viewer else POLL_MS)
            except Exception:
                continue
            drain(commands, bridge, recorder, screencast, interactions)
            if lock is not None:
                lock.enforce()

        steps = recorder.steps
        if screencast is not None:
            screencast.stop()
        if fullscreen and recorder.viewport is not None:
            emit({"type": "viewport", "width": recorder.viewport[0], "height": recorder.viewport[1]})
        if browser.is_connected():
            browser.close()
        return steps


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        sys.stderr.write("usage: python -m comfycapture.core.session <payload.json>\n")
        return 2
    payload = SessionPayload.from_dict(json.loads(Path(arguments[0]).read_text(encoding="utf-8")))
    stop = threading.Event()
    commands: queue.Queue[dict[str, Any]] = queue.Queue()
    replies: queue.Queue[dict[str, Any]] = queue.Queue()
    threading.Thread(target=watch_stdin, args=(commands, stop, replies), daemon=True).start()
    try:
        steps = record(payload, stop, commands, replies)
    except Exception as error:
        emit({"type": "error", "message": runner.first_line(str(error)), "fatal": True})
        return 1
    emit({"type": "done", "steps": [ir.step_to_dict(step) for step in steps]})
    return 0


if __name__ == "__main__":
    sys.exit(main())
