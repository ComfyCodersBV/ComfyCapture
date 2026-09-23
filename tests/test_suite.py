from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from browsertests.core import db, ir, runner, suite
from browsertests.core.models import Environment, EnvironmentConfig, Project, RunStatus, Test

pytestmark = pytest.mark.browser


def step(document: dict) -> object:
    return ir.step_from_dict(document)


def target(kind: str, value: str, **extra) -> dict:
    return {"primary": {"kind": kind, "value": value, **extra}}


NAVIGATE = {"id": "n", "action": "navigate", "url": "/index.html"}
ADD = {"id": "a", "action": "click", "target": target("test_id", "add-to-cart", attribute="data-testid")}


def expect_text(step_id: str, element_id: str, text: str) -> dict:
    return {
        "id": step_id,
        "action": "assertText",
        "target": target("id", element_id),
        "value": text,
        "timeout_ms": 800,
    }


def make(name: str, *documents: dict, destructive: bool = False) -> Test:
    return Test(
        id=ir.new_test_id(),
        name=name,
        steps=tuple(step(document) for document in documents),
        destructive=destructive,
    )


@pytest.fixture
def seeded(tmp_path: Path, site_url: str):
    connection = db.connect(tmp_path / "suite.sqlite")
    project = db.ProjectRepository(connection).save(Project(None, "shop", "Shop"))
    environment = db.EnvironmentRepository(connection).save(
        Environment(None, project.id, "local", site_url, config=EnvironmentConfig(cookies=("consent=yes",)))
    )
    return connection, project, environment, db.TestRepository(connection)


def plan_for(project, environment, tests, tmp_path: Path, **extra) -> suite.SuitePlan:
    return suite.SuitePlan(project, environment, tuple(tests), tmp_path / "artifacts", retries=0, **extra)


def test_results_artifacts_and_destructive_guard(seeded, tmp_path: Path) -> None:
    connection, project, environment, tests = seeded
    passing = tests.save(project.id, make("adds", NAVIGATE, ADD, expect_text("t", "cart", "Cart: 1")))
    failing = tests.save(project.id, make("wrong total", NAVIGATE, ADD, expect_text("t", "cart", "Cart: 5")))
    order = tests.save(project.id, make("orders", NAVIGATE, destructive=True))
    execution = suite.SuiteRunner(
        plan_for(project, environment, (passing, failing, order), tmp_path), runner.VariableResolver()
    )

    results = {result.stored.test.name: result for result in execution.run()}

    assert results["adds"].status is RunStatus.PASSED
    assert results["wrong total"].status is RunStatus.FAILED
    assert results["wrong total"].failed_step_id == "t"
    assert (Path(results["wrong total"].artifact_path) / "trace.zip").is_file()
    assert results["orders"].status is RunStatus.SKIPPED
    assert "REFUSED" in results["orders"].message
    assert suite.exit_code(results.values()) == 1


def test_consent_cookie_setup_and_login_session_are_applied(seeded, tmp_path: Path) -> None:
    connection, project, environment, tests = seeded
    login = tests.save(
        project.id, make("login", NAVIGATE, {"id": "l", "action": "click", "target": target("id", "login")})
    )
    setup = tests.save(project.id, make("setup", NAVIGATE, ADD))
    checked = tests.save(
        project.id,
        make(
            "state",
            expect_text("c", "cart", "Cart: 1"),
            expect_text("k", "consent", "Consented"),
            expect_text("s", "session", "Signed in"),
        ),
    )
    plan = plan_for(project, environment, (checked,), tmp_path, setup=setup, login=login)

    [result] = suite.SuiteRunner(plan, runner.VariableResolver()).run()

    assert result.status is RunStatus.PASSED, result.message


def test_missing_variables_are_a_configuration_error(seeded, tmp_path: Path) -> None:
    connection, project, environment, tests = seeded
    needs = tests.save(project.id, make("needs", {"id": "n", "action": "navigate", "url": "/{{order_path}}"}))

    with pytest.raises(suite.ConfigurationError, match="order_path"):
        suite.SuiteRunner(plan_for(project, environment, (needs,), tmp_path), runner.VariableResolver()).run()


def test_cli_run_exit_codes_and_history(seeded, tmp_path: Path) -> None:
    connection, project, environment, tests = seeded
    tests.save(
        project.id,
        replace(make("adds", NAVIGATE, ADD, expect_text("t", "cart", "Cart: 1")), tags=("CINF-19",)),
    )
    tests.save(project.id, make("wrong total", NAVIGATE, expect_text("t", "cart", "Cart: 9")))
    database = str(tmp_path / "suite.sqlite")

    def cli(*arguments: str) -> subprocess.CompletedProcess:
        command = [sys.executable, "-m", "browsertests.cli", "--database", database, *arguments]
        return subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)

    tagged = cli("run", "--project", "shop", "--env", "local", "--tag", "cinf-19", "--jsonl")
    everything = cli("run", "--project", "shop", "--env", "local", "--retries", "0")
    unknown = cli("run", "--project", "shop", "--env", "production")

    summary = json.loads(tagged.stdout.splitlines()[-1])
    assert tagged.returncode == 0, tagged.stderr
    assert summary["counts"]["passed"] == 1
    assert everything.returncode == 1
    assert "FAIL" in everything.stdout
    assert unknown.returncode == 2
    assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 3
    assert connection.execute("SELECT COUNT(DISTINCT playwright_version) FROM runs").fetchone()[0] == 1


def test_exit_code_mapping() -> None:
    def result(status: RunStatus) -> suite.TestResult:
        return suite.TestResult(stored=None, status=status, duration_ms=0)

    assert suite.exit_code([result(RunStatus.PASSED), result(RunStatus.FLAKY)]) == 0
    assert suite.exit_code([result(RunStatus.PASSED), result(RunStatus.SKIPPED)]) == 2
    assert suite.exit_code([result(RunStatus.ERROR), result(RunStatus.FAILED)]) == 1


def test_old_artifacts_are_pruned(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from browsertests.core.models import RunRecord

    connection = db.connect(":memory:")
    project = db.ProjectRepository(connection).save(Project(None, "shop", "Shop"))
    environment = db.EnvironmentRepository(connection).save(
        Environment(None, project.id, "local", "http://x")
    )
    stored = db.TestRepository(connection).save(project.id, make("t", NAVIGATE))
    runs = db.RunRepository(connection)
    old, recent = tmp_path / "old", tmp_path / "recent"
    old.mkdir()
    recent.mkdir()
    for started, path in (("2026-01-01T00:00:00+00:00", old), ("2026-09-20T00:00:00+00:00", recent)):
        runs.add(
            RunRecord(
                None,
                stored.id,
                environment.id,
                RunStatus.FAILED,
                started,
                1,
                "1",
                "1",
                artifact_path=str(path),
            )
        )

    pruned = suite.prune_artifacts(runs, retention_days=14, now=datetime(2026, 9, 23, tzinfo=UTC))

    assert pruned == 1
    assert not old.exists()
    assert recent.exists()
