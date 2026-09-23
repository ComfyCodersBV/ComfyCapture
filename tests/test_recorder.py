from __future__ import annotations

import json
import subprocess
import sys
import time

import pytest

from browsertests.core import ir, runner, verify
from browsertests.core.models import Action, Device, DeviceKind, EnvironmentConfig, SelectorKind
from browsertests.core.recorder import Recorder
from browsertests.core.session import SessionPayload

pytestmark = pytest.mark.browser

ATTRIBUTES = ("dusk", "data-testid")


def wait_for_steps(page, recorder: Recorder, count: int) -> None:
    deadline = time.monotonic() + 5
    while len(recorder.steps) < count and time.monotonic() < deadline:
        page.wait_for_timeout(50)
    page.wait_for_timeout(100)


def pick(page, mode: str, locator) -> None:
    page.locator(f"bt-recorder button[data-mode={mode}]").click()
    page.wait_for_timeout(50)
    locator.click()


def record_checkout(browser, site_url: str):
    context = browser.new_context()
    recorder = Recorder(context, site_url, ATTRIBUTES)
    recorder.install()
    page = context.new_page()
    recorder.recording = True

    page.goto(f"{site_url}/index.html")
    page.get_by_test_id("add-to-cart").click()
    page.locator(".generated").click()
    pick(page, "assertText", page.locator("#cart"))
    page.get_by_text("Checkout").click()
    page.wait_for_url("**/form.html")

    page.get_by_label("Email").click()
    page.get_by_label("Email").fill("jane@example.com")
    page.get_by_label("Password").fill("hunter2")
    page.get_by_label("I agree").check()
    page.get_by_label("Country").select_option("be")
    page.get_by_role("button", name="Place order").click()
    page.wait_for_url("**/done.html*")
    pick(page, "assertVisible", page.get_by_test_id("thanks"))
    wait_for_steps(page, recorder, 11)

    steps = recorder.steps
    context.close()
    return steps


def test_recording_produces_ranked_steps(browser, site_url: str) -> None:
    steps = record_checkout(browser, site_url)

    assert [step.action for step in steps] == [
        Action.NAVIGATE,
        Action.CLICK,
        Action.CLICK,
        Action.ASSERT_TEXT,
        Action.CLICK,
        Action.FILL,
        Action.FILL,
        Action.CHECK,
        Action.SELECT_OPTION,
        Action.CLICK,
        Action.ASSERT_VISIBLE,
    ]
    navigate, add, _, assert_text, to_form, email, password, _, country, _, thanks = steps
    assert navigate.url == "/index.html"
    assert (add.target.primary.kind, add.target.primary.value) == (SelectorKind.TEST_ID, "add-to-cart")
    assert assert_text.value == "Cart: 1"
    assert to_form.target.primary.attribute == "dusk"
    assert email.value == "jane@example.com"
    assert email.target.primary.kind is SelectorKind.ID
    assert password.value == "{{secret:password}}"
    assert "hunter2" not in json.dumps([ir.step_to_dict(step) for step in steps])
    assert country.value == "be"
    assert thanks.target.primary.value == "thanks"


def test_verification_drops_ids_that_change_between_loads(browser, site_url: str) -> None:
    steps = record_checkout(browser, site_url)
    context = browser.new_context()
    resolver = runner.VariableResolver(secrets=lambda name: "secret-value")

    result = verify.verify(context.new_page(), steps, site_url, resolver, ATTRIBUTES, timeout_ms=3000)
    context.close()

    assert result.failed is None, result.failed
    generated = result.steps[2]
    assert all(selector.kind is not SelectorKind.ID for selector in generated.target.candidates)
    assert "changed between page loads" in (generated.note or "")


def test_mobile_clicks_are_recorded_as_taps(playwright, browser, site_url: str) -> None:
    device = Device(kind=DeviceKind.MOBILE, name="iPhone 13")
    context = browser.new_context(**runner.context_options(playwright, device, EnvironmentConfig()))
    recorder = Recorder(context, site_url, ATTRIBUTES, mobile=True)
    recorder.install()
    page = context.new_page()
    recorder.recording = True

    page.goto(f"{site_url}/index.html")
    page.get_by_test_id("add-to-cart").tap()
    wait_for_steps(page, recorder, 2)
    context.close()

    assert [step.action for step in recorder.steps] == [Action.NAVIGATE, Action.TAP]


def test_session_replays_saved_steps_before_recording(site_url: str, tmp_path) -> None:
    prefix = (
        ir.step_from_dict({"id": "s1", "action": "navigate", "url": "/index.html"}),
        ir.step_from_dict(
            {
                "id": "s2",
                "action": "click",
                "target": {
                    "primary": {"kind": "test_id", "attribute": "data-testid", "value": "add-to-cart"}
                },
            }
        ),
    )
    payload = SessionPayload(base_url=site_url, test_id_attributes=ATTRIBUTES, steps=prefix, headless=True)
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(payload.to_dict()))

    process = subprocess.run(
        [sys.executable, "-m", "browsertests.core.session", str(path)],
        input="stop\n",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    messages = [json.loads(line) for line in process.stdout.splitlines()]

    assert process.returncode == 0, process.stderr
    assert [message["outcome"]["passed"] for message in messages if message["type"] == "replayed"] == [
        True,
        True,
    ]
    assert messages[-1]["type"] == "done"
    assert [step["id"] for step in messages[-1]["steps"]] == ["s1", "s2"]
