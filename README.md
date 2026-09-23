# BrowsertestSuite

Record browser tests once, replay them on demand and on a schedule, and find out when a site breaks.
Desktop app (PySide6) for Ubuntu, macOS and Windows; headless runner for servers. Playwright is the
engine; recording uses an own injected recorder instead of `playwright codegen` (see `DECISIONS.md`).

Background and scope: `HANDOFF-browser-test-suite-CINF-19.md`.

## Development

```bash
uv sync --all-extras
uv run playwright install chromium

uv run browsertests-desktop      # desktop app
uv run browsertests --version    # CLI

uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

`core/` never imports Qt; `tests/test_core_isolation.py` enforces it. Browser tests run headless against
the pages in `tests/fixtures/site/`.

## Recording

1. Create a project (test attributes in order of preference, e.g. `data-testid, dusk`) and an environment.
2. Record new test: pick environment and device (desktop size or a mobile device). A Chromium window opens.
3. Click through the site. The toolbar at the bottom of the page adds assertions (visible, text, value,
   checked) and hovers; Esc cancels a pick.
4. Close the browser or press Stop. Review the steps, mark the test destructive if it changes data, and
   run Verify selectors: a headless replay that keeps only selectors that match the recorded element and
   drops ids that change between page loads.
5. Continue recording replays the saved steps in a visible browser, then keeps recording.

## Packaging

```bash
uv sync --all-extras --group package
uv run pyinstaller --noconfirm --clean --windowed --name BrowsertestSuite --collect-all playwright \
    --collect-data browsertests --copy-metadata browsertests --distpath dist --workpath build packaging/entry.py
```

The packaged app keeps its browsers under the user data directory and offers to download Chromium on
the first recording.
