from __future__ import annotations

import http.server
import json
import threading

from comfycapture.core import notify

RESULTS = [
    {"name": "Home", "status": "passed", "failed_step_id": None, "message": None},
    {"name": "Checkout", "status": "failed", "failed_step_id": "s4", "message": "No selector matched"},
]


def test_nothing_is_sent_when_everything_passed(tmp_path) -> None:
    marker = tmp_path / "called"
    body = notify.payload("shop", "staging", RESULTS[:1], 0)

    notify.notify(body, None, f"touch {marker}")

    assert not marker.exists()


def test_command_gets_summary_and_json(tmp_path) -> None:
    output = tmp_path / "out.json"
    body = notify.payload("shop", "staging", RESULTS, 1)

    problems = notify.notify(body, None, f'cat > {output}; echo "$COMFYCAPTURE_EXIT_CODE" >> {output}.code')

    assert problems == []
    assert json.loads(output.read_text())["results"][1]["name"] == "Checkout"
    assert (tmp_path / "out.json.code").read_text().strip() == "1"
    assert "FAILED Checkout at step s4: No selector matched" in body["text"]


def test_webhook_receives_slack_compatible_text() -> None:
    received: list[dict] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers["Content-Length"])
            received.append(json.loads(self.rfile.read(length)))
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()

    problems = notify.notify(
        notify.payload("shop", "staging", RESULTS, 1),
        f"http://127.0.0.1:{server.server_address[1]}/hook",
        None,
    )
    server.server_close()

    assert problems == []
    assert received[0]["text"].startswith("Browser tests for shop on staging: 1 of 2 need attention")
