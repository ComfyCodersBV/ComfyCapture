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

The default is desktop full screen (`"fullscreen": true`): the recording window starts maximised and the
page follows it; the size measured at the end of the recording is stored and used for replay.

A fixed size or a mobile device is recorded in the app itself: the browser runs headless with the
device emulation, `core/screencast.py` streams the page over the DevTools protocol, and the desktop
shows it centred in a device frame (`ui/device_viewer.py`), forwarding mouse, touch and keyboard input.
A headed Chromium window cannot be narrower than about 500 pixels and always draws the emulated
viewport in its top-left corner, which made phone recordings look broken. Known gaps of the viewer:
native `<select>` popups, file choosers and `alert`/`confirm` dialogs are not shown yet.

## D4 — Several test attributes per project

With the own recorder there is no single-flag limit, so `projects.test_id_attributes` is an ordered JSON
list. The default covers the common conventions: `data-testid, data-test, data-cy, data-qa, dusk,
wire:model, name`. A configured attribute also matches its modifier variants (`wire:model` matches
`wire:model.live`). A `test_id` selector stores the actual attribute and is replayed as an escaped CSS
attribute selector, so `set_test_id_attribute` is not needed.

Id, label, role + name and placeholder are selector strategies, not attributes, so they are separate
per-project switches (`projects.selector_kinds`, all on by default). A test attribute and the CSS path
are always kept, so an element never ends up without a selector.

## D5 — Tag normalisation

Tags are trimmed and de-duplicated; ticket-like tags (`[A-Za-z]+-\d+`) are upper-cased
(`cinf-19` → `CINF-19`). Answers open decision 4 minimally; autocomplete comes with the editor.

## D6 — Packaging

PyInstaller, one-folder builds per OS, made by hand with `packaging/build.py` (build, smoke test,
archive, upload to the GitLab package registry); see `packaging/RELEASING.md`. No macOS or Windows
runners: CI only tests, and on a version tag creates the release that links to the uploaded builds.
Browsers are not bundled: the desktop app runs `playwright install chromium` in user space on first use.

Frozen builds set `PLAYWRIGHT_BROWSERS_PATH` to `<user data dir>/browsers`, so browsers survive app
updates and never need write access to the install directory.

## D7 — UI theme and languages

Own Qt stylesheet built from light and dark colour tokens (`ui/theme.py`), following the system scheme
unless the user picks one in Settings. English source strings, Dutch translation in
`ui/i18n/browsertests_nl.ts`; `packaging/update_translations.py` refreshes and compiles it.

## D8 — Runs, setup and login (M2)

- Exit codes: `0` everything passed (flaky counts as passed but is reported), `1` at least one test
  failed, `2` configuration problem: unknown project/environment/test, missing variable or secret,
  a failing login test, or a destructive test refused on a protected environment.
- Setup and login are ordinary recorded tests, chosen per project. The setup test runs before every
  test in the same page (cookie banner, locale switch). The login test runs once per run; its session
  (`storage_state`) is kept in memory and handed to every test context, so it never lands on disk.
  Saved storage-state files (§9, "login state") are not built; the login test covers that need.
- Consent cookies are set per environment before every test.
- Traces and a full-page screenshot (password fields masked) are kept for a final failure only, under
  `<user data dir>/artifacts/<project>/`. Artifacts older than 14 days are pruned after every run.
