from __future__ import annotations

from comfycapture.core.models import Action
from comfycapture.core.sanitizer import RecordedEvent, StepBuilder, relative_url

BASE = "https://shop.test/nl"


def event(kind: str, time: float, key: str = "k1", value: str | None = None, **extra) -> RecordedEvent:
    return RecordedEvent(
        type=kind,
        time=time,
        element_key=key,
        tag="input",
        candidates=({"kind": "id", "value": key},),
        value=value,
        **extra,
    )


def test_click_then_typing_becomes_one_fill() -> None:
    builder = StepBuilder(BASE, ())
    builder.add(event("click", 0))
    builder.add(event("fill", 10, value="j"))
    builder.add(event("fill", 20, value="jane"))

    assert [(step.action, step.value) for step in builder.steps] == [(Action.FILL, "jane")]


def test_fills_on_different_elements_stay_separate() -> None:
    builder = StepBuilder(BASE, ())
    builder.add(event("fill", 0, key="a", value="1"))
    builder.add(event("fill", 10, key="b", value="2"))
    builder.add(event("fill", 20, key="a", value="3"))

    assert [step.value for step in builder.steps] == ["1", "2", "3"]


def test_double_click_replaces_its_clicks() -> None:
    builder = StepBuilder(BASE, ())
    builder.add(event("click", 0, key="other"))
    builder.add(event("click", 10))
    builder.add(event("dblclick", 20))

    assert [step.action for step in builder.steps] == [Action.CLICK, Action.DBLCLICK]


def test_navigation_caused_by_an_action_is_dropped() -> None:
    builder = StepBuilder(BASE, (), navigation_grace_ms=1000)
    builder.navigation("https://shop.test/nl/", 0)
    builder.add(event("click", 5000))
    builder.navigation("https://shop.test/nl/cart", 5400)
    builder.navigation("https://shop.test/nl/account?tab=orders", 9000)

    assert [step.url for step in builder.steps if step.action is Action.NAVIGATE] == [
        "/",
        "/account?tab=orders",
    ]


def test_events_outside_the_main_page_become_unknown_steps() -> None:
    builder = StepBuilder(BASE, ())
    builder.add(event("click", 0, top_frame=False))
    builder.add(event("click", 10, page_index=1))

    assert [step.action for step in builder.steps] == [Action.UNKNOWN, Action.UNKNOWN]
    assert "iframe" in builder.steps[0].raw


def test_password_values_never_enter_the_step() -> None:
    builder = StepBuilder(BASE, ())
    builder.add(event("fill", 0, value="", sensitive=True))

    assert builder.steps[0].value == "{{secret:password}}"


def test_relative_url_keeps_foreign_hosts_absolute() -> None:
    assert relative_url("https://shop.test/nl/products?id=4#top", BASE) == "/products?id=4#top"
    assert relative_url("https://pay.example/checkout", BASE) == "https://pay.example/checkout"


def test_base_url_trailing_slash_does_not_matter() -> None:
    from comfycapture.core.runner import absolute_url

    assert absolute_url("/login", "https://shop.test/") == absolute_url("/login", "https://shop.test")
    assert relative_url("https://shop.test/nl/cart", "https://shop.test/nl/") == "/cart"


def test_cookie_banner_clicks_are_flagged() -> None:
    builder = StepBuilder(BASE, (), mobile=True)
    builder.add(event("click", 0, key="CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll"))
    builder.add(event("click", 10, key="add-to-cart"))

    assert "Cookie banner" in (builder.steps[0].note or "")
    assert builder.steps[1].note is None


def test_navigation_outside_the_environment_is_flagged() -> None:
    builder = StepBuilder(BASE, ())
    builder.navigation("https://shop.test/nl/", 0)
    builder.navigation("https://other.example/nl", 10_000)

    assert builder.steps[0].note is None
    assert "Leaves the environment" in (builder.steps[1].note or "")


def test_late_click_into_the_field_being_typed_in_is_ignored() -> None:
    builder = StepBuilder(BASE, (), mobile=True)
    builder.add(event("fill", 0, value="ja"))
    builder.add(event("click", 300))
    builder.add(event("fill", 400, value="jane"))

    assert [(step.action, step.value) for step in builder.steps] == [(Action.FILL, "jane")]


def test_requested_navigation_is_recorded_even_right_after_an_action() -> None:
    builder = StepBuilder(BASE, (), navigation_grace_ms=1000)
    builder.add(event("click", 0))
    builder.navigation("https://shop.test/nl/cart", 200, requested=True)

    assert builder.steps[-1].url == "/cart"
