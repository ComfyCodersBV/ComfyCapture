from __future__ import annotations

import json
import subprocess
import sys

import pytest

from comfycapture.core import db, exchange, ir
from comfycapture.core.models import Action, Environment, EnvironmentConfig, Project, Step, Test, Variable


def source_installation():
    connection = db.connect(":memory:")
    login = Test(id=ir.new_test_id(), name="Log in", steps=(Step("s1", Action.NAVIGATE, url="/login"),))
    checkout = Test(
        id=ir.new_test_id(),
        name="Guest checkout",
        tags=("CINF-19",),
        steps=(
            Step("s1", Action.NAVIGATE, url="/{{locale}}/cart"),
            Step("s2", Action.NAVIGATE, url="/pay?code={{secret:voucher}}"),
        ),
    )
    projects = db.ProjectRepository(connection)
    project = projects.save(Project(None, "shop", "Shop", ("dusk",), login_test_uuid=login.id))
    db.EnvironmentRepository(connection).save(
        Environment(
            None,
            project.id,
            "staging",
            "https://staging.shop.test",
            True,
            EnvironmentConfig(http_credentials="basic"),
        )
    )
    variables = db.VariableRepository(connection)
    variables.save(project.id, Variable("locale", "nl"))
    variables.save(project.id, Variable("voucher", "TOPSECRET", is_secret=True))
    tests = db.TestRepository(connection)
    tests.save(project.id, login)
    stored = tests.save(project.id, checkout)
    return connection, project, stored


def test_export_contains_names_but_never_values() -> None:
    connection, project, stored = source_installation()

    [(name, text)] = exchange.export_tests(connection, project, [stored])

    assert name == "shop-guest-checkout-v1.json"
    assert "TOPSECRET" not in text
    assert '"nl"' not in text
    document = json.loads(text)
    assert {variable["name"] for variable in document["variables"]} == {"locale", "voucher"}
    assert document["environments"][0]["http_credentials_secret"] == "basic"


def test_import_into_a_fresh_installation_reports_what_is_missing() -> None:
    connection, project, stored = source_installation()
    [(_, text)] = exchange.export_tests(connection, project, [stored])
    target = db.connect(":memory:")

    [report] = exchange.import_documents(target, [json.loads(text)], lambda slug, name: name == "basic")

    assert report.created_project
    assert report.tests_added == ["Guest checkout"]
    assert report.environments_added == ["staging"]
    assert report.missing_variables == ["locale"]
    assert report.missing_secrets == ["voucher"]
    assert report.missing_tests and report.missing_tests[0].startswith("login")
    assert not report.ready
    imported = db.TestRepository(target).by_uuid(stored.test.id)
    assert imported.test == stored.test


def test_reimport_updates_instead_of_duplicating() -> None:
    connection, project, stored = source_installation()
    [(_, text)] = exchange.export_tests(connection, project, [stored])

    [report] = exchange.import_documents(connection, [json.loads(text)], lambda slug, name: True)

    assert report.tests_updated == ["Guest checkout"]
    assert report.environments_added == []
    assert len(db.TestRepository(connection).for_project(project.id)) == 2


def test_legacy_export_format_is_still_imported() -> None:
    connection, project, stored = source_installation()
    [(_, text)] = exchange.export_tests(connection, project, [stored])
    document = json.loads(text)
    document["format"] = "browsertests-export"

    [report] = exchange.import_documents(db.connect(":memory:"), [document], lambda slug, name: True)

    assert report.project == "shop"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda document: document.update(schema_version=ir.SCHEMA_VERSION + 1), "newer|supports up to"),
        (lambda document: document.update(format="something"), "Not a ComfyCapture"),
        (lambda document: document["test"]["steps"].append({"id": "x", "action": "teleport"}), "invalid"),
    ],
)
def test_invalid_exports_are_refused(change, message) -> None:
    connection, project, stored = source_installation()
    [(_, text)] = exchange.export_tests(connection, project, [stored])
    document = json.loads(text)
    change(document)

    with pytest.raises(exchange.ExchangeError, match=message):
        exchange.import_documents(db.connect(":memory:"), [document], lambda slug, name: True)


def test_cli_export_then_import(tmp_path) -> None:
    source = tmp_path / "source.sqlite"
    connection = db.connect(source)
    project = db.ProjectRepository(connection).save(Project(None, "shop", "Shop"))
    db.TestRepository(connection).save(
        project.id, Test(id=ir.new_test_id(), name="Home", steps=(Step("s1", Action.NAVIGATE, url="/"),))
    )
    out = tmp_path / "export"

    def cli(database, *arguments):
        command = [sys.executable, "-m", "comfycapture.cli", "--database", str(database), *arguments]
        return subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)

    exported = cli(source, "export", "--project", "shop", "--out", str(out))
    imported = cli(tmp_path / "target.sqlite", "import", *[str(path) for path in out.glob("*.json")])

    assert exported.returncode == 0, exported.stderr
    assert imported.returncode == 0, imported.stderr
    assert "Added tests: Home" in imported.stdout
