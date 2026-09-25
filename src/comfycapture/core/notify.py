"""Failure notifications, independent of the channel.

A webhook receives a JSON body whose `text` field Slack- and Mattermost-style incoming webhooks show as
is; the other fields carry the details for anything else. A command runs with the summary in environment
variables and the full JSON on stdin, which covers mail, ticket systems and anything scriptable.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from collections.abc import Iterable
from typing import Any

from comfycapture.core.models import RunStatus

WEBHOOK_VARIABLE = "COMFYCAPTURE_NOTIFY_WEBHOOK"
COMMAND_VARIABLE = "COMFYCAPTURE_NOTIFY_COMMAND"
TIMEOUT_SECONDS = 30
PROBLEMS = (RunStatus.FAILED, RunStatus.ERROR, RunStatus.SKIPPED, RunStatus.FLAKY)


def summary_text(project: str, environment: str, results: Iterable[dict[str, Any]], exit_code: int) -> str:
    items = list(results)
    failing = [item for item in items if item["status"] in {status.value for status in PROBLEMS}]
    headline = f"Browser tests for {project} on {environment}: " + (
        "all passed" if exit_code == 0 else f"{len(failing)} of {len(items)} need attention"
    )
    lines = [headline]
    for item in failing:
        detail = f" at step {item['failed_step_id']}" if item.get("failed_step_id") else ""
        message = f": {item['message']}" if item.get("message") else ""
        lines.append(f"- {item['status'].upper()} {item['name']}{detail}{message}")
    return "\n".join(lines)


def payload(project: str, environment: str, results: list[dict[str, Any]], exit_code: int) -> dict[str, Any]:
    return {
        "text": summary_text(project, environment, results, exit_code),
        "project": project,
        "environment": environment,
        "exit_code": exit_code,
        "results": results,
    }


def send_webhook(url: str, body: dict[str, Any]) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS):
        return


def run_command(command: str, body: dict[str, Any]) -> None:
    environment = {
        **os.environ,
        "COMFYCAPTURE_EXIT_CODE": str(body["exit_code"]),
        "COMFYCAPTURE_PROJECT": str(body["project"]),
        "COMFYCAPTURE_ENVIRONMENT": str(body["environment"]),
        "COMFYCAPTURE_SUMMARY": str(body["text"]),
    }
    subprocess.run(
        command,
        shell=True,
        input=json.dumps(body),
        text=True,
        env=environment,
        timeout=TIMEOUT_SECONDS,
        check=False,
    )


def notify(body: dict[str, Any], webhook: str | None, command: str | None, always: bool = False) -> list[str]:
    if body["exit_code"] == 0 and not always:
        return []
    problems: list[str] = []
    if webhook:
        try:
            send_webhook(webhook, body)
        except Exception as error:
            problems.append(f"webhook failed: {error}")
    if command:
        try:
            run_command(command, body)
        except Exception as error:
            problems.append(f"notify command failed: {error}")
    return problems
