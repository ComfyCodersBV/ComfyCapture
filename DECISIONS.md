# Decisions — deviations from the CINF-19 handoff

The handoff (`HANDOFF-browser-test-suite-CINF-19.md`) remains the reference. This file records where the
implementation deliberately differs, and why.

## D1 — Own recorder instead of `playwright codegen`

Playwright stays the automation engine (auto-wait, locators, tracing, pinned browsers, Docker image).
Recording no longer goes through `codegen` + AST parsing.

- A recorder script is injected with `context.add_init_script` and reports user actions through
  `context.expose_binding`.
- Selector candidates are read from the live DOM at the moment of the action: every configured test
  attribute, the `id`, the label, role + accessible name, placeholder and a CSS path.
- A headless verification replay after recording checks every candidate with real Playwright locators,
  drops candidates that do not resolve to the same element, and compares ids with the recording
  (recording = load one, verification = load two) to flag unstable ids.
- "Record from here": the session replays the saved steps in the same browser context, then keeps the
  recorder open for further steps.
- Assertions are picked with a small in-page toolbar (shadow DOM, excluded from recording).

Why: codegen accepts one test-id attribute, cannot see the DOM, cannot continue after a replay, and its
output (Python code or the undocumented `--target=jsonl`) carries no stability guarantee.

Consequence: `core/codegen.py` and `core/parser.py` from §5 are replaced by `core/recorder.js`,
`core/session.py` (recording subprocess), `core/sanitizer.py` (events → steps) and `core/verify.py`.

## D2 — Action vocabulary aligned with the Pest recorder MR

Action names follow Playwright's recorder vocabulary, as used by pestphp/pest-plugin-browser#222:

`navigate`, `click`, `dblclick`, `tap`, `fill`, `press`, `check`, `uncheck`, `selectOption`, `hover`,
`setInputFiles`, `assertVisible`, `assertText`, `assertValue`, `assertChecked`, plus `unknown`.

This replaces `goto`, `select_option`, `upload` and the generic `expect` + `assertion` from §6.

## D3 — Device profile per test

A test carries a `device` in the IR: `{"kind": "desktop", "width": 1440, "height": 900}` or
`{"kind": "mobile", "name": "iPhone 13"}` (a Playwright device descriptor). Recording and replay use the
same emulation. On mobile, clicks are recorded as `tap` and replayed with touch enabled. One test = one
profile; mobile flows usually differ (hamburger menus), so a test is not replayed on both.

## D4 — Several test attributes per project

With the own recorder there is no single-flag limit, so `projects.test_id_attributes` is an ordered JSON
list (e.g. `["data-testid", "dusk", "data-test"]`). A `test_id` selector stores its attribute, and is
replayed as a CSS attribute selector, so `set_test_id_attribute` is not needed.

## D5 — Tag normalisation

Tags are trimmed and de-duplicated; ticket-like tags (`[A-Za-z]+-\d+`) are upper-cased
(`cinf-19` → `CINF-19`). Answers open decision 4 minimally; autocomplete comes with the editor.

## D6 — Packaging

PyInstaller, one-folder builds per OS (`packaging/entry.py`). Browsers are not bundled: the desktop app
runs `playwright install chromium` in user space on first use. CI is GitLab (`.gitlab-ci.yml`); the
macOS and Windows jobs use GitLab SaaS runner tags and need those runners to be available.

Frozen builds set `PLAYWRIGHT_BROWSERS_PATH` to `<user data dir>/browsers`, so browsers survive app
updates and never need write access to the install directory.
