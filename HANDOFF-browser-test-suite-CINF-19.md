# Handoff — Browser Test Suite (CINF-19)

**Name:** BrowsertestSuite
**Repository:** `browsertests` · **Python package:** `browsertests`
**Application ID:** `nl.comfycoders.BrowserTests`
**Audience:** Claude Code, starting from an empty repository.
**Context:** ComfyCoders project. A NativePHP proof of concept exists; it is not a reference implementation and must not be ported.

---

## 1. Scope of this handoff

In scope:

- The **desktop application**: manage projects, record tests, edit them, run them locally.
- The **core library and headless runner**: replay tests without any GUI, on a server.
- **JSON export/import** of tests between installations.

Out of scope for this handoff:

- The **web interface** for scheduling and reporting on a server. It is a separate deliverable and a separate decision (standalone app vs ComfyConsole module). The CLI runner defined here is what that web interface will eventually invoke, so nothing here needs to change when it arrives.
- Pest export. Designed for here (§12), built later.

---

## 2. Goal

Record browser interactions once, replay them on demand and on a schedule, and find out when a site breaks. The recording is a thin wrapper around `playwright codegen`; the value of the product is everything around it — project management, a stable test format, editing, scheduled runs and reporting.

---

## 3. Hard requirements

- Desktop app runs on **Ubuntu Linux, macOS and Windows**.
- The runner additionally runs on **headless Ubuntu** with no display server.
- **Recording requires a display.** `codegen` opens a real browser plus the Inspector window. Running it under Xvfb on a server is technically possible and practically useless. Record on a desktop, replay anywhere. Do not build for headless recording.

---

## 4. Stack

| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.12+ | |
| GUI | **PySide6** (Qt 6, LGPL) | Same reasoning as FotoZeef: GTK4/PyGObject is not viable on Windows. |
| Browser automation | `playwright` (Python) | Ships its own Node driver, so `python -m playwright codegen` works from inside the app. |
| Packaging/deps | `uv` | Lockfile committed. |
| Persistence | SQLite via stdlib `sqlite3` | |
| Paths | `platformdirs` | |
| Secrets | `keyring` | OS keychain on desktop; see §9. |
| CLI | `argparse` (stdlib) | No Click. The CLI has four commands. |
| Lint/format | `ruff` | |
| Tests | `pytest` | |

### Conventions

- Full type hints everywhere, including return types. `from __future__ import annotations`.
- No comments. Docstrings only on public module-level APIs where the contract is non-obvious.
- Early returns over nested conditionals.
- `@dataclass(frozen=True, slots=True)` for value objects.
- Imports sorted (ruff).
- No global mutable state; dependencies passed into constructors.

---

## 5. Architecture

```
browsertests/
  core/              # No Qt imports. Ever.
    models.py        # Project, Environment, Test, Step, Target dataclasses
    db.py            # SQLite schema + repositories
    ir.py            # The test format: (de)serialisation, schema versioning, validation
    codegen.py       # Launch `playwright codegen`, capture output
    parser.py        # Python AST -> IR. The single riskiest module. See §7.
    runner.py        # IR -> Playwright execution, results, artifacts
    selectors.py     # Selector strategy and fallback resolution
    secrets.py       # Credential resolution (keyring / env / file)
    exchange.py      # JSON export/import
    pest.py          # IR -> Pest (later milestone)
  ui/                # PySide6
    main_window.py
    project_view.py
    test_editor.py
    run_view.py
  cli.py             # Headless entry point
  app.py             # Desktop entry point
```

`core` must import and run with no display server and without PySide6 installed. Enforce it with a test that imports every `core` module in a subprocess and asserts `PySide6` is absent from `sys.modules`. This is what makes the server runner possible; do not let a single Qt import leak in.

The server image ships `core` + `cli.py` only.

---

## 6. The intermediate representation (IR)

**This is the central design decision of the project. Everything else follows from it.**

Tests are stored as structured data, not as generated Python. Code is a rendering target; the IR is the source of truth. Without this, editing is text editing and Pest export is impossible.

```json
{
  "schema_version": 1,
  "id": "0c9f…",
  "name": "Guest checkout",
  "description": "",
  "tags": ["CINF-19", "checkout"],
  "destructive": false,
  "steps": [
    {
      "id": "s1",
      "action": "goto",
      "url": "/products/42"
    },
    {
      "id": "s2",
      "action": "click",
      "target": {
        "primary": { "kind": "test_id", "value": "add-to-cart" },
        "fallbacks": [
          { "kind": "role", "role": "button", "name": "Add to cart" },
          { "kind": "css", "value": ".btn-cart" }
        ]
      }
    },
    {
      "id": "s3",
      "action": "fill",
      "target": { "primary": { "kind": "label", "value": "Email" }, "fallbacks": [] },
      "value": "{{customer_email}}"
    },
    {
      "id": "s4",
      "action": "expect",
      "assertion": "to_be_visible",
      "target": { "primary": { "kind": "test_id", "value": "order-confirmation" }, "fallbacks": [] }
    }
  ]
}
```

Rules:

- `schema_version` is present from day one. Write the migration path before you need it.
- Step `id`s are stable across edits. Results reference step ids, so renumbering breaks history.
- `tags` is a free-form ordered list of strings, carried in the IR so it survives export and import. Tests are recorded per ticket, so a ticket key is simply a tag. Detect the pattern `[A-Z]+-\d+` and render those tags differently in the UI, but do not give tickets their own field — a test often covers more than one ticket, and a ticket often needs more than one test. Tags drive run selection (`--tag CINF-19`) and filtering in the editor.
- `action` is a closed set: `goto`, `click`, `dblclick`, `fill`, `press`, `check`, `uncheck`, `select_option`, `hover`, `upload`, `expect`. Add to it deliberately; every action is code in three places (parser, runner, Pest renderer).
- `{{variable}}` placeholders in any `value`, resolved at run time from project variables and secrets. **Without variables the suite dies within a month** — order numbers, dates and stock levels change and every assertion on them breaks.
- No `wait_for_timeout` in the IR. Playwright locators auto-wait; a sleep is a bug report waiting to happen. If a real wait is needed, express it as `expect` with a timeout.

---

## 7. Recording

Flow:

1. User picks a project and environment, optionally a saved login state.
2. App runs `python -m playwright codegen --target python --output <tmp> [--load-storage=<state>] <base_url>` as a subprocess.
3. User records; the browser and Inspector are Playwright's own UI. Do not try to reimplement them.
4. On exit, parse the generated file into IR, show the parsed steps for review, save.

**The parser is the highest-risk component in this project.** Codegen emits code, not data, and its output format carries no stability guarantee.

- Parse with the stdlib **`ast` module**, never with regular expressions. The output is regular Python; walk the call chain on `page.…` and map each call to an action.
- Keep it in one module with a large corpus of recorded fixtures in `tests/fixtures/codegen/`, one per Playwright version and per action type.
- On an unrecognised call, do not silently drop the step: produce an `unknown` step carrying the raw source line, and show it in the editor as needing attention. Silent loss is much worse than a visible gap.
- **Pin the Playwright version** in the lockfile and test the parser against it in CI. Upgrading Playwright is a deliberate task with a fixture re-run, not a routine dependency bump.

---

## 8. Selector strategy

Text-based selectors are not acceptable as a primary target. `get_by_role("button", name="Inloggen")` breaks on a copy change, a translation or a designer touching a label — and it breaks silently, months later, in a scheduled run nobody is watching.

Priority order for a target's `primary`:

1. A dedicated test attribute: `data-testid`, `data-test`, `dusk`, whatever the project uses.
2. An **authored** `id` — unique per page, rarely changed. See the warning below.
3. `get_by_label` for form fields. Tied to the accessibility tree, more stable than visible text.
4. Role + accessible name.
5. CSS path. Last resort, recorded as a fallback only.

### Recording with a forced attribute

`playwright codegen --test-id-attribute=<attr>` changes what codegen emits: `get_by_test_id(...)` against that attribute instead of role/text. Configure it per project (`projects.test_id_attr`). For a project with no test attributes at all, set it to `id`.

Playwright accepts **one** test-id attribute at a time, so "use `dusk` when present, otherwise `id`" cannot be expressed in a single codegen flag. That is solved by the enrichment pass, not by the flag.

At run time the same attribute is applied with `playwright.selectors.set_test_id_attribute(...)` before any locator resolves.

### Target enrichment pass

**Build this in M1. It is what turns the priority list above from an intention into a mechanism.**

Immediately after recording, replay the steps once in headless mode and inspect the element that actually matched for each target. From the live DOM, build the full candidate list: every test attribute present, the `id`, the associated label, the role and accessible name, and a CSS path. Order them by the priority list and store them as `primary` + `fallbacks`.

The parser only sees generated code; it cannot know which other attributes the element carried. The enrichment pass has the DOM. It costs one extra headless run and it is the difference between a fallback chain that is data and one that is a guess. The runner code needed for it already exists.

### Not every `id` is trustworthy

An authored `id` is excellent. A framework-generated one looks identical and is a trap. Livewire, Filament, React and Vue emit ids like `:r3:`, `wire-8f2a1c`, `input-7`, `headlessui-menu-item-42`. They are unique on the page, they change on every render or release, and they will fail within weeks.

During enrichment, flag suspicious ids rather than trusting them: numeric-only, hash-like segments, known framework prefixes, or — the decisive check — **an id that differs between two loads of the same page**. Load the page twice in the enrichment pass and compare. A flagged id is demoted below the label and role candidates and marked in the editor so the author can decide.

### At run time

Try `primary`; on failure walk the fallbacks. If a fallback succeeds, the test passes but the run is recorded with a **selector drift warning** — the UI moved, and someone should look before the chain runs out.

---

## 9. Credentials and login state

Treat this as a security feature, not a convenience feature. A `storage_state` JSON is full account access in plain text.

- **Login state**: `context.storage_state(path=…)` produces cookies + localStorage. Store the file under `platformdirs.user_data_dir(...)/state/`, never in the project folder, never in the database as a blob, never in an export.
- **Login as a script**: also support a recorded login test that runs before the suite. Storage state expires; a replayable login does not. Offer both and default to the script.
- **Credentials** live in the OS keyring on the desktop (`keyring`), and on a server come from environment variables or a secrets file outside the repo. `core/secrets.py` is the only module that reads them; everything else asks it by name.
- Secrets are referenced in the IR as `{{secret:admin_password}}` and resolved at run time. The literal value never enters the IR, the database, a log line, an exported JSON or a Playwright trace.
- Traces and screenshots capture whatever is on screen. Mask password fields before capture, or accept that traces are sensitive artifacts and store them accordingly.

---

## 10. Projects, environments and safety

- A project has one or more **environments** (e.g. staging, production), each with a base URL. Tests store paths, not absolute URLs, so the same test runs against any environment.
- Per-environment settings: `http_credentials` (basic auth on staging), viewport/device emulation, locale, timezone, `ignore_https_errors`.
- **Destructive tests.** A recorded checkout places a real order. Every test carries a `destructive` flag, every environment carries `allow_destructive`. The runner refuses the combination and says so loudly. Default `allow_destructive` to false on any environment not named staging.
- **Cookie banners and consent dialogs** break recordings and every subsequent run. Support per-project setup steps that run before every test, plus a pre-seeded consent cookie in the environment config. Solve this in M2, not later — it will otherwise contaminate every recording made before it.

---

## 11. Exchange format (export/import)

For now, tests move between installations as **JSON files via explicit export and import buttons**. No git sync, no API push.

That is a fine v1 choice, but it makes the JSON file the interchange contract, so get the format right now — a later git sync or API push is only a different transport for the same file.

- Export = one or more tests plus the project's variable *names* and environment *shapes*.
- **Export never contains secrets, credentials or storage state.** It contains the names they are referenced by. Import lists what is missing and refuses to run until those are supplied.
- Export includes `schema_version`. Import validates it and refuses a newer version outright rather than guessing.
- Filenames: `<project>-<test>-<schema_version>.json`. Human-readable, diffable, stable key order.

---

## 12. Pest export

One-way, IR → Pest browser tests.

**There is an open MR against Pest v5 (authored by Johan) that adds codegen-based recording for Pest tests.** If it lands, the action vocabulary and the code shape it generates are the natural target for this renderer, and the mapping largely exists already. Read that MR before designing anything here.

Two consequences, in order of importance:

1. **Align the IR's action names with that MR now**, while the IR is still cheap to change. If both sides use the same vocabulary, the renderer is close to mechanical. If they drift, you maintain a translation table forever. This is the one piece of Pest work worth doing early — it is a naming decision, not an implementation.
2. **Do not couple anything to the MR's API until it is merged.** An open MR is not a stable target. Keep the renderer behind a small interface in `core/pest.py`, pin to whatever Pest version actually ships, and build it in M6 as planned.

There is no import path from Pest back into the IR. Do not promise one.

---

## 13. Runner

```
browsertests run --project <slug> --env staging [--test <id>] [--tag <tag>]… [--headed]
browsertests list --project <slug> [--tag <tag>]
browsertests import <file.json>
browsertests export --project <slug> [--tag <tag>] --out <dir>
```

`--tag` is repeatable and ANDs. `--tag CINF-19` is how a scheduled run or a CI job targets the tests belonging to one ticket.

- Exit codes: `0` all passed, `1` one or more failed, `2` configuration or credential error. A CI system and a systemd timer both need to distinguish these.
- **Retries**: configurable, default 1. A test that fails then passes is recorded as **flaky**, not as passed. Flakiness that hides is how a suite loses its audience.
- **Artifacts**: Playwright traces (`context.tracing.start(screenshots=True, snapshots=True, sources=True)`) are invaluable when debugging and cost megabytes per run. Capture on failure only by default. **Retention policy from day one** — keep N runs or N days, prune on every run. A server disk filling up silently is the predictable failure here.
- **Browser version pinning**: desktop and server must run the same Playwright browser build, or results differ for no visible reason. Pin it, and record the Playwright and browser version in every run record.
- Parallelism: one browser context per test, N workers. Each Chromium instance costs 300+ MB, so default N to 2 and make it configurable.

### Headless Ubuntu

Base the server image on `mcr.microsoft.com/playwright/python:v<pinned>`, which already carries the browsers and system libraries. Outside Docker, `playwright install --with-deps chromium` needs root — fine for a provisioned server, unacceptable for a packaged desktop app.

### Scheduling

Do not build a scheduler into the app. The runner is a CLI; scheduling is `systemd` timers or cron on the server and Task Scheduler on Windows. When the web interface arrives it invokes the same CLI.

---

## 14. Data model

```sql
CREATE TABLE projects (
    id           INTEGER PRIMARY KEY,
    slug         TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    test_id_attr TEXT NOT NULL DEFAULT 'data-testid',
    created_at   TEXT NOT NULL
);

CREATE TABLE environments (
    id               INTEGER PRIMARY KEY,
    project_id       INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    base_url         TEXT NOT NULL,
    allow_destructive INTEGER NOT NULL DEFAULT 0,
    config           TEXT NOT NULL,   -- JSON: viewport, locale, timezone, http_credentials ref
    UNIQUE (project_id, name)
);

CREATE TABLE tests (
    id           INTEGER PRIMARY KEY,
    project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    uuid         TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    destructive  INTEGER NOT NULL DEFAULT 0,
    ir           TEXT NOT NULL,       -- the JSON document from §6
    schema_version INTEGER NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE test_tags (
    test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    tag     TEXT NOT NULL,
    PRIMARY KEY (test_id, tag)
);

CREATE INDEX idx_test_tags_tag ON test_tags(tag);

CREATE TABLE runs (
    id             INTEGER PRIMARY KEY,
    test_id        INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    environment_id INTEGER NOT NULL REFERENCES environments(id) ON DELETE CASCADE,
    status         TEXT NOT NULL,     -- passed | failed | flaky | error | skipped
    started_at     TEXT NOT NULL,
    duration_ms    INTEGER NOT NULL,
    failed_step_id TEXT NULL,
    message        TEXT NULL,
    artifact_path  TEXT NULL,
    playwright_version TEXT NOT NULL,
    browser_version    TEXT NOT NULL
);

CREATE TABLE variables (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    value      TEXT NULL,             -- NULL when it resolves from the keyring
    is_secret  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (project_id, name)
);
```

Database: `platformdirs.user_data_dir("BrowsertestSuite", "ComfyCoders")` / `browsertests.sqlite`.
Secret *values* are never stored in this database. `variables.value` stays NULL when `is_secret = 1`.
`tests.ir` is the source of truth for tags; `test_tags` is a derived index for querying and is rewritten whenever a test is saved.

---

## 15. Localisation

The application UI ships in **English and Dutch**.

- Source strings in **English**, wrapped in `self.tr(...)`. Dutch is the first translation.
- `pylupdate6` → `.ts` → Qt Linguist → `lrelease` → `.qm`, bundled as Qt resources.
- Language follows `QLocale.system()` with a manual override in settings.
- **Runner output, log lines, error messages and artifact contents stay English and untranslated.** They end up in logs, traces and reports read by developers. Only the UI chrome around them is translated. Do not route runner messages through `tr()`.

---

## 16. Build order

- **M0 — Skeleton.** Repo, `uv`, ruff, pytest, CI matrix (ubuntu/macos/windows), empty PySide6 window plus a working `browsertests --version` CLI, packaged and launched on all three platforms. Prove packaging before writing features.
- **M1 — Projects and recording.** Projects, environments, launch codegen with the project's test-id attribute, AST parser → IR with its fixture corpus, **target enrichment pass**, tags, save to SQLite. Review screen after recording, showing flagged ids and unknown steps.
- **M2 — Running.** Runner, headed and headless, results persisted, artifacts on failure, setup steps and consent-cookie handling, destructive guard.
- **M3 — Editing.** Step list, edit values and selectors, reorder, delete, re-record a single step, project variables.
- **M4 — Exchange.** JSON export/import with secret exclusion and schema validation.
- **M5 — Server.** Docker image, headless runner, retries and flaky classification, artifact retention, scheduling documentation, failure notifications.
- **M6 — Pest export.**

Each milestone ends with something installable and usable.

---

## 17. Out of scope

- Headless recording.
- Visual regression / screenshot diffing.
- Load or performance testing.
- Importing existing Pest or Playwright test files.
- Anything that edits the site under test.

---

## 18. Open decisions

1. **Web interface: standalone project or ComfyConsole module.** Decide on ownership and tenancy, not on load — the heavy component is the runner, which is a separate worker either way. If customer tests will ever run here, ComfyConsole already has auth and tenancy; if it stays internal, standalone is faster.
2. **Notification channels** on failure: email, Slack, Linear issue?
3. **Default parallelism** and whether a single run may span multiple environments.
4. **Tag vocabulary.** Free-form, or a controlled list per project? Free-form is assumed; it degrades into typos (`CINF-19` vs `cinf-19`) without at least case normalisation and autocomplete.
