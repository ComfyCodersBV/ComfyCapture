from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from comfycapture.core.models import Device
from comfycapture.core.session import SessionPayload

pytestmark = pytest.mark.browser

VIEWPORT = {"width": 800, "height": 600}


def centres(site_url: str) -> dict[str, tuple[int, int]]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT)
        page.goto(f"{site_url}/form.html")
        page.evaluate("document.getElementById('answer').textContent = 'no'")
        result = {}
        for name, selector in (("country", "#country"), ("danger", "#danger"), ("upload", "#upload")):
            box = page.locator(selector).bounding_box()
            result[name] = (int(box["x"] + box["width"] / 2), int(box["y"] + box["height"] / 2))
        browser.close()
    return result


class Session:
    def __init__(self, payload: SessionPayload, path: Path) -> None:
        path.write_text(json.dumps(payload.to_dict()))
        self.process = subprocess.Popen(
            [sys.executable, "-m", "comfycapture.core.session", str(path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        self.messages: queue.Queue[dict] = queue.Queue()
        self.steps: list[dict] = []
        self.seen: list[str] = []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.process.stdout:
            message = json.loads(line)
            if message["type"] != "frame":
                self.seen.append(json.dumps(message)[:160])
            if message["type"] in ("steps", "done"):
                self.steps = message["steps"]
            self.messages.put(message)

    def send(self, command: dict | str) -> None:
        self.process.stdin.write((command if isinstance(command, str) else json.dumps(command)) + "\n")
        self.process.stdin.flush()

    def click(self, point: tuple[int, int]) -> None:
        for event in ("mousePressed", "mouseReleased"):
            self.send(
                {
                    "type": "mouse",
                    "event": event,
                    "x": point[0],
                    "y": point[1],
                    "button": "left",
                    "click_count": 1,
                }
            )

    def wait_for(self, kind: str, timeout: float = 15) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = self.messages.get(timeout=0.2)
            except queue.Empty:
                continue
            if message["type"] == kind:
                return message
        raise AssertionError(f"no {kind} message; seen {self.seen}")


def test_viewer_select_dialog_and_upload_round_trip(site_url: str, tmp_path: Path) -> None:
    points = centres(site_url)
    upload = tmp_path / "invoice.pdf"
    upload.write_text("pdf")
    payload = SessionPayload(
        base_url=site_url,
        test_id_attributes=("data-testid",),
        start_path="/form.html",
        device=Device(width=800, height=600),
        viewer=True,
    )
    session = Session(payload, tmp_path / "payload.json")
    session.wait_for("frame")

    session.click(points["country"])
    select = session.wait_for("select")
    session.send({"type": "select_choice", "id": select["id"], "values": ["be"]})

    session.click(points["danger"])
    dialog = session.wait_for("dialog")
    session.send({"type": "dialog_reply", "id": dialog["id"], "accept": False})

    session.click(points["upload"])
    chooser = session.wait_for("filechooser")
    session.send({"type": "files", "id": chooser["id"], "paths": [str(upload)]})
    time.sleep(1.5)
    session.send("stop")
    session.process.wait(30)
    time.sleep(0.3)

    by_action = {step["action"]: step for step in session.steps}
    assert [option["value"] for option in select["options"]] == ["nl", "be"]
    assert by_action["selectOption"]["value"] == "be"
    assert dialog["kind"] == "confirm"
    assert "dismissed" in by_action["click"]["note"]
    assert by_action["setInputFiles"]["value"] == str(upload)
