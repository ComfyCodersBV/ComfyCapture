"""Turns raw recorder events into IR steps.

Merges consecutive fills on one element, folds a click into the fill that follows it, collapses clicks
into a double click, maps clicks to taps on mobile, and keeps navigations only when the user caused them
directly (address bar, back button) rather than as a side effect of a recorded action.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlsplit

from browsertests.core import ir, selectors
from browsertests.core.models import Action, Step

NAVIGATION_GRACE_MS = 2500
SECRET_PLACEHOLDER = "{{secret:password}}"

EVENT_ACTIONS = {
    "click": Action.CLICK,
    "dblclick": Action.DBLCLICK,
    "fill": Action.FILL,
    "press": Action.PRESS,
    "check": Action.CHECK,
    "uncheck": Action.UNCHECK,
    "selectOption": Action.SELECT_OPTION,
    "hover": Action.HOVER,
    "setInputFiles": Action.SET_INPUT_FILES,
    "assertVisible": Action.ASSERT_VISIBLE,
    "assertText": Action.ASSERT_TEXT,
    "assertValue": Action.ASSERT_VALUE,
    "assertChecked": Action.ASSERT_CHECKED,
}


@dataclass(frozen=True, slots=True)
class RecordedEvent:
    type: str
    time: float
    url: str = ""
    top_frame: bool = True
    page_index: int = 0
    element_key: str | None = None
    tag: str | None = None
    candidates: tuple[Mapping[str, Any], ...] = ()
    value: str | None = None
    checked: bool | None = None
    sensitive: bool = False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any], page_index: int = 0) -> RecordedEvent:
        target = payload.get("target") or {}
        return cls(
            type=str(payload.get("type", "")),
            time=float(payload.get("time", 0)),
            url=str(payload.get("url", "")),
            top_frame=bool(payload.get("topFrame", True)),
            page_index=page_index,
            element_key=target.get("key"),
            tag=target.get("tag"),
            candidates=tuple(target.get("candidates", ())),
            value=None if payload.get("value") is None else str(payload.get("value")),
            checked=payload.get("checked"),
            sensitive=bool(payload.get("sensitive", False)),
        )


def relative_url(url: str, base_url: str) -> str:
    base = urlsplit(base_url)
    target = urlsplit(url)
    if (target.scheme, target.netloc) != (base.scheme, base.netloc):
        return url
    base_path = base.path.rstrip("/")
    path = target.path
    if base_path and path.startswith(base_path):
        path = path[len(base_path) :] or "/"
    result = path or "/"
    if target.query:
        result += f"?{target.query}"
    if target.fragment:
        result += f"#{target.fragment}"
    return result


class StepBuilder:
    def __init__(
        self,
        base_url: str,
        test_id_attributes: tuple[str, ...],
        mobile: bool = False,
        steps: Iterable[Step] = (),
        navigation_grace_ms: float = NAVIGATION_GRACE_MS,
    ) -> None:
        self._base_url = base_url
        self._test_id_attributes = test_id_attributes
        self._mobile = mobile
        self._grace = navigation_grace_ms
        self._steps: list[Step] = list(steps)
        self._keys: dict[str, str | None] = {}
        self._last_activity: float | None = None

    @property
    def steps(self) -> tuple[Step, ...]:
        return tuple(self._steps)

    def navigation(self, url: str, time: float, page_index: int = 0) -> bool:
        if page_index != 0 or not url.startswith(("http://", "https://")):
            return False
        caused = self._last_activity is not None and time - self._last_activity <= self._grace
        self._last_activity = time
        if caused:
            return False
        path = relative_url(url, self._base_url)
        last = self._steps[-1] if self._steps else None
        if last is not None and last.action is Action.NAVIGATE and last.url == path:
            return False
        self._append(Step(ir.new_step_id(), Action.NAVIGATE, url=path), None)
        return True

    def add(self, event: RecordedEvent) -> bool:
        action = EVENT_ACTIONS.get(event.type)
        if action is None:
            return False
        self._last_activity = event.time

        if not event.top_frame or event.page_index != 0:
            where = "inside an iframe" if not event.top_frame else "in a popup or new tab"
            self._append(self._unknown(event, f"{event.type} {where} on {event.url}"), None)
            return True

        target = selectors.target_from_candidates(event.candidates, self._test_id_attributes)
        if target is None:
            self._append(
                self._unknown(event, f"{event.type} on <{event.tag or '?'}> without a usable selector"), None
            )
            return True

        if action is Action.CLICK and self._mobile:
            action = Action.TAP

        step = Step(
            ir.new_step_id(),
            action,
            target=target,
            value=self._value(action, event),
            checked=event.checked if action is Action.ASSERT_CHECKED else None,
            note=self._note(action, event),
        )

        if action is Action.FILL:
            return self._add_fill(step, event.element_key)
        if action is Action.DBLCLICK:
            self._drop_trailing_clicks(event.element_key)
        self._append(step, event.element_key)
        return True

    def _add_fill(self, step: Step, key: str | None) -> bool:
        last = self._steps[-1] if self._steps else None
        if last is not None and key is not None and self._keys.get(last.id) == key:
            if last.action is Action.FILL:
                self._steps[-1] = replace(last, value=step.value, target=step.target, note=step.note)
                return True
            if last.action in (Action.CLICK, Action.TAP):
                self._steps[-1] = replace(step, id=last.id)
                return True
        self._append(step, key)
        return True

    def _drop_trailing_clicks(self, key: str | None) -> None:
        for _ in range(2):
            last = self._steps[-1] if self._steps else None
            if (
                last is None
                or last.action not in (Action.CLICK, Action.TAP)
                or self._keys.get(last.id) != key
            ):
                return
            self._steps.pop()

    def _append(self, step: Step, key: str | None) -> None:
        self._steps.append(step)
        self._keys[step.id] = key

    @staticmethod
    def _value(action: Action, event: RecordedEvent) -> str | None:
        if action is Action.FILL and event.sensitive:
            return SECRET_PLACEHOLDER
        if action in (
            Action.FILL,
            Action.PRESS,
            Action.SELECT_OPTION,
            Action.SET_INPUT_FILES,
            Action.ASSERT_TEXT,
            Action.ASSERT_VALUE,
        ):
            return event.value or ""
        return None

    @staticmethod
    def _note(action: Action, event: RecordedEvent) -> str | None:
        if action is Action.FILL and event.sensitive:
            return "Password field: point this at the right secret."
        if action is Action.SET_INPUT_FILES:
            return "Browsers do not reveal file paths: set the path to the file to upload."
        return None

    @staticmethod
    def _unknown(event: RecordedEvent, raw: str) -> Step:
        return Step(ir.new_step_id(), Action.UNKNOWN, raw=raw, note="Not replayable yet: needs attention.")
