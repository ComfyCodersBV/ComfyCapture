from __future__ import annotations

import functools
import http.server
import importlib.util
import os
import threading
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

SITE = Path(__file__).parent / "fixtures" / "site"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
collect_ignore = [] if importlib.util.find_spec("PySide6") else ["test_ui.py"]


LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


@pytest.fixture(autouse=True)
def prevent_stray_requests(monkeypatch):
    original = urllib.request.urlopen

    def guarded(request, *args, **kwargs):
        url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
        if urllib.parse.urlsplit(url).hostname not in LOCAL_HOSTS:
            raise AssertionError(f"Tests must not reach the outside world: {url}")
        return original(request, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", guarded)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture(scope="session")
def site_url():
    handler = functools.partial(QuietHandler, directory=str(SITE))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def playwright():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as instance:
        yield instance


@pytest.fixture(scope="module")
def browser(playwright):
    try:
        browser = playwright.chromium.launch(headless=True)
    except Exception as error:
        pytest.skip(f"Chromium is not installed: {error}")
    yield browser
    browser.close()
