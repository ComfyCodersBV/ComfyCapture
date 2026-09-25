# ComfyCapture

Record browser tests once, replay them on demand and on a schedule, and find out when a site breaks.
Desktop app (PySide6) for Ubuntu, macOS and Windows; headless runner for servers. Playwright is the
engine; recording uses an own injected recorder instead of `playwright codegen` (see `DECISIONS.md`).

Background and scope: `HANDOFF-browser-test-suite-CINF-19.md`.

## Development

```bash
uv sync --all-extras
uv run playwright install chromium

uv run comfycapture-desktop      # desktop app
uv run comfycapture --version    # CLI

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

## Running

```bash
comfycapture list --project shop
comfycapture run --project shop --env staging                 # all tests
comfycapture run --project shop --env staging --tag CINF-19   # tags AND together
comfycapture run --project shop --env staging --test "Guest checkout" --headed
```

```bash
comfycapture export --project shop --tag CINF-19 --out exports/
comfycapture import exports/*.json    # exit 2 while variables or secrets are still missing
```

Exit codes: `0` passed, `1` a test failed, `2` configuration error. `--jsonl` gives machine-readable
output. Secrets come from `COMFYCAPTURE_SECRET_<NAME>` or the OS keyring; `COMFYCAPTURE_DATABASE`
points at another database.

## Translations

UI strings are English in the code and translated to Dutch in `src/comfycapture/ui/i18n/`. After changing
UI text: `uv run python packaging/update_translations.py`, translate the unfinished strings in Qt Linguist
(`uv run pyside6-linguist src/comfycapture/ui/i18n/comfycapture_nl.ts`), and run the script again.

## Packaging

Desktop builds are made by hand on each OS with one command; see `packaging/RELEASING.md`.

```bash
uv sync --all-extras --group package
uv run --group package python packaging/build.py
```
