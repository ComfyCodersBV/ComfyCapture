"""IR to Pest browser tests (pestphp/pest-plugin-browser 5.x).

One-way. Targets use the step's primary selector, written as a Playwright selector the plugin passes
through (`[attr="value"]`, `internal:label=...`, `internal:role=...`). Placeholders become `env()` calls.
Steps the plugin cannot express (unknown steps, double clicks) make the export fail rather than be
dropped silently.
"""

from __future__ import annotations

import json
import re

from browsertests.core import selectors
from browsertests.core.models import Action, Device, Selector, SelectorKind, Step, Test
from browsertests.core.secrets import environment_key

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_:.-]*)\s*\}\}")
DEVICES = {
    "iPhone 15": "iPhone15",
    "iPhone 15 Pro": "iPhone15Pro",
    "iPhone 14 Pro": "iPhone14Pro",
    "iPhone SE": "iPhoneSE",
    "iPad Mini": "iPadMini",
    "iPad Pro 11": "iPadPro",
    "Pixel 7": "pixel7",
    "Galaxy S9+": "mobile",
    "Galaxy S24": "mobile",
}
UNSUPPORTED = {Action.UNKNOWN, Action.DBLCLICK}


class PestExportError(ValueError):
    pass


def php_string(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def text_selector(text: str) -> str:
    return json.dumps(text, ensure_ascii=False) + "s"


def selector_expression(selector: Selector) -> str:
    match selector.kind:
        case SelectorKind.TEST_ID:
            return f"[{selectors.css_identifier(selector.attribute or '')}={selectors.css_string(selector.value)}]"
        case SelectorKind.ID:
            return f"[id={selectors.css_string(selector.value)}]"
        case SelectorKind.LABEL:
            return f"internal:label={text_selector(selector.value)}"
        case SelectorKind.ROLE:
            return f"internal:role={selector.role}[name={text_selector(selector.value)}]"
        case SelectorKind.PLACEHOLDER:
            return f"internal:attr=[placeholder={text_selector(selector.value)}]"
        case SelectorKind.CSS:
            return selector.value


def environment_name(reference: str) -> str:
    if reference.startswith("secret:"):
        return environment_key(reference[len("secret:") :])
    return re.sub(r"[^A-Za-z0-9]", "_", reference).upper()


def value_expression(text: str) -> str:
    parts: list[str] = []
    position = 0
    for match in PLACEHOLDER.finditer(text):
        if match.start() > position:
            parts.append(php_string(text[position : match.start()]))
        parts.append(f"env({php_string(environment_name(match.group(1)))})")
        position = match.end()
    if position < len(text) or not parts:
        parts.append(php_string(text[position:]))
    return " . ".join(parts)


def device_calls(device: Device) -> str:
    if device.is_mobile:
        return f"->on()->{DEVICES.get(device.name or '', 'mobile')}()"
    if device.fullscreen:
        return ""
    return f"->resize({device.width}, {device.height})"


def action_call(step: Step) -> list[str]:
    target = php_string(selector_expression(step.target.primary)) if step.target else ""
    value = value_expression(step.value or "")
    match step.action:
        case Action.CLICK | Action.TAP:
            return [f"click({target})"]
        case Action.FILL:
            return [f"fill({target}, {value})"]
        case Action.PRESS:
            return [f"keys({target}, {value})"]
        case Action.CHECK:
            return [f"check({target})"]
        case Action.UNCHECK:
            return [f"uncheck({target})"]
        case Action.SELECT_OPTION:
            options = [option for option in (step.value or "").split(",") if option]
            if len(options) > 1:
                return [f"select({target}, [{', '.join(value_expression(option) for option in options)}])"]
            return [f"select({target}, {value})"]
        case Action.HOVER:
            return [f"hover({target})"]
        case Action.SET_INPUT_FILES:
            return [
                f"attach({target}, {value_expression(path)})"
                for path in (step.value or "").split(",")
                if path
            ]
        case Action.ASSERT_VISIBLE:
            return [f"assertVisible({target})"]
        case Action.ASSERT_TEXT:
            return [f"assertSeeIn({target}, {value})"]
        case Action.ASSERT_VALUE:
            return [f"assertValue({target}, {value})"]
        case Action.ASSERT_CHECKED:
            return [
                f"assertChecked({target})" if step.checked is not False else f"assertNotChecked({target})"
            ]
    return []


def render(test: Test) -> str:
    unsupported = [f"{step.id} ({step.action.value})" for step in test.steps if step.action in UNSUPPORTED]
    if unsupported:
        raise PestExportError(
            f"{test.name}: these steps cannot be written as a Pest browser test: {', '.join(unsupported)}."
        )

    blocks: list[list[str]] = []
    current: list[str] | None = None
    for step in test.steps:
        if step.action is Action.NAVIGATE:
            current = [f"$page = visit({value_expression(step.url or '/')}){device_calls(test.device)};"]
            blocks.append(current)
            continue
        if current is None:
            current = [f"$page = visit('/'){device_calls(test.device)};"]
            blocks.append(current)
        current.extend(action_call(step))

    body: list[str] = []
    for block in blocks:
        body.append("    " + block[0])
        calls = block[1:]
        if calls:
            body.append("")
            body.append("    $page->" + calls[0])
            body.extend("        ->" + call for call in calls[1:])
            body[-1] += ";"
        body.append("")
    if body and body[-1] == "":
        body.pop()

    groups = f"->group({', '.join(php_string(tag) for tag in test.tags)})" if test.tags else ""
    lines = [
        "<?php",
        "",
        "declare(strict_types=1);",
        "",
        f"it({php_string(test.name)}, function (): void {{",
        *body,
        f"}}){groups};",
        "",
    ]
    return "\n".join(lines)


def filename(test: Test) -> str:
    words = re.findall(r"[A-Za-z0-9]+", test.name)
    return "".join(word[:1].upper() + word[1:] for word in words) + "Test.php" if words else "BrowserTest.php"
