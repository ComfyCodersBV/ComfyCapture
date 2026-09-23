"""JSON exchange of tests between installations.

One file per test, `<project>-<test>-v<schema>.json`, carrying the test's IR plus the shape of its
project: settings, environment shapes and variable names. Values of variables, secrets, credentials and
login state never leave the installation; an import reports what the receiving side still has to supply.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from browsertests.core import db, ir
from browsertests.core.models import (
    OPTIONAL_SELECTOR_KINDS,
    Environment,
    EnvironmentConfig,
    Project,
    SelectorKind,
    StoredTest,
    Variable,
)

FORMAT = "browsertests-export"
SECRET_PREFIX = "secret:"

Document = dict[str, Any]


class ExchangeError(ValueError):
    pass


@dataclass(slots=True)
class ImportReport:
    project: str
    created_project: bool = False
    environments_added: list[str] = field(default_factory=list)
    tests_added: list[str] = field(default_factory=list)
    tests_updated: list[str] = field(default_factory=list)
    missing_variables: list[str] = field(default_factory=list)
    missing_secrets: list[str] = field(default_factory=list)
    missing_tests: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not (self.missing_variables or self.missing_secrets or self.missing_tests)

    def lines(self) -> list[str]:
        result = [f"Project {self.project}" + (" (created)" if self.created_project else "")]
        if self.tests_added:
            result.append("Added tests: " + ", ".join(self.tests_added))
        if self.tests_updated:
            result.append("Updated tests: " + ", ".join(self.tests_updated))
        if self.environments_added:
            result.append("Added environments: " + ", ".join(self.environments_added))
        if self.missing_variables:
            result.append("Variables to fill in: " + ", ".join(self.missing_variables))
        if self.missing_secrets:
            result.append("Secrets to add: " + ", ".join(self.missing_secrets))
        if self.missing_tests:
            result.append("Setup or login tests not in this import: " + ", ".join(self.missing_tests))
        return result


def slug_part(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "test"


def filename(project: Project, stored: StoredTest) -> str:
    return f"{project.slug}-{slug_part(stored.test.name)}-v{ir.SCHEMA_VERSION}.json"


def environment_shape(environment: Environment) -> Document:
    config = environment.config
    return {
        "name": environment.name,
        "base_url": environment.base_url,
        "allow_destructive": environment.allow_destructive,
        "locale": config.locale,
        "timezone": config.timezone,
        "ignore_https_errors": config.ignore_https_errors,
        "http_credentials_secret": config.http_credentials,
        "cookies": list(config.cookies),
    }


def export_document(
    project: Project, environments: Iterable[Environment], variables: Iterable[Variable], stored: StoredTest
) -> Document:
    return {
        "format": FORMAT,
        "schema_version": ir.SCHEMA_VERSION,
        "project": {
            "slug": project.slug,
            "name": project.name,
            "test_id_attributes": list(project.test_id_attributes),
            "selector_kinds": [kind.value for kind in project.selector_kinds],
            "setup_test": project.setup_test_uuid,
            "login_test": project.login_test_uuid,
        },
        "environments": [environment_shape(environment) for environment in environments],
        "variables": [{"name": variable.name, "secret": variable.is_secret} for variable in variables],
        "test": ir.to_document(stored.test),
    }


def dumps(document: Document) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def export_tests(
    connection: sqlite3.Connection, project: Project, tests: Iterable[StoredTest]
) -> list[tuple[str, str]]:
    project_id = project.id or 0
    environments = db.EnvironmentRepository(connection).for_project(project_id)
    variables = db.VariableRepository(connection).for_project(project_id)
    return [
        (filename(project, stored), dumps(export_document(project, environments, variables, stored)))
        for stored in tests
    ]


def validate(document: Any) -> Document:
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise ExchangeError("Not a BrowsertestSuite export file.")
    version = document.get("schema_version")
    if not isinstance(version, int):
        raise ExchangeError("The export has no schema_version.")
    if version > ir.SCHEMA_VERSION:
        raise ExchangeError(
            f"The export uses schema version {version}; this installation supports up to {ir.SCHEMA_VERSION}. "
            "Update BrowsertestSuite first."
        )
    if not isinstance(document.get("project"), dict) or not document["project"].get("slug"):
        raise ExchangeError("The export has no project.")
    try:
        ir.from_document(document.get("test") or {})
    except ir.InvalidDocumentError as error:
        raise ExchangeError(f"The test in the export is invalid: {error}") from error
    return document


def import_documents(
    connection: sqlite3.Connection,
    documents: Iterable[Document],
    secret_available: Callable[[str, str], bool],
) -> list[ImportReport]:
    reports: dict[str, ImportReport] = {}
    references: dict[str, set[str]] = {}
    for raw in documents:
        document = validate(raw)
        project = ensure_project(connection, document, reports)
        report = reports[project.slug]
        add_environments(connection, project, document.get("environments", []), report)
        stored = store_test(connection, project, document["test"], report)
        references.setdefault(project.slug, set()).update(ir.placeholders(stored.test))
        for variable in document.get("variables", []):
            prefix = SECRET_PREFIX if variable.get("secret") else ""
            references[project.slug].add(prefix + str(variable.get("name")))
    for slug, report in reports.items():
        complete(connection, slug, report, references.get(slug, set()), secret_available)
    return list(reports.values())


def ensure_project(
    connection: sqlite3.Connection, document: Document, reports: dict[str, ImportReport]
) -> Project:
    shape = document["project"]
    projects = db.ProjectRepository(connection)
    slug = str(shape["slug"])
    project = projects.by_slug(slug)
    if slug not in reports:
        reports[slug] = ImportReport(project=slug)
    if project is not None:
        return project
    kinds = tuple(
        SelectorKind(kind)
        for kind in shape.get("selector_kinds") or [kind.value for kind in OPTIONAL_SELECTOR_KINDS]
    )
    project = projects.save(
        Project(
            id=None,
            slug=slug,
            name=str(shape.get("name") or slug),
            test_id_attributes=tuple(shape.get("test_id_attributes") or ("data-testid",)),
            selector_kinds=kinds,
            setup_test_uuid=shape.get("setup_test"),
            login_test_uuid=shape.get("login_test"),
        )
    )
    reports[slug].created_project = True
    return project


def add_environments(
    connection: sqlite3.Connection, project: Project, shapes: list[Document], report: ImportReport
) -> None:
    environments = db.EnvironmentRepository(connection)
    project_id = project.id or 0
    for shape in shapes:
        name = str(shape.get("name", "")).strip()
        if not name or environments.by_name(project_id, name) is not None:
            continue
        environments.save(
            Environment(
                id=None,
                project_id=project_id,
                name=name,
                base_url=str(shape.get("base_url", "")),
                allow_destructive=bool(shape.get("allow_destructive", False)),
                config=EnvironmentConfig(
                    locale=shape.get("locale"),
                    timezone=shape.get("timezone"),
                    ignore_https_errors=bool(shape.get("ignore_https_errors", False)),
                    http_credentials=shape.get("http_credentials_secret"),
                    cookies=tuple(shape.get("cookies") or ()),
                ),
            )
        )
        report.environments_added.append(name)


def store_test(
    connection: sqlite3.Connection, project: Project, document: Document, report: ImportReport
) -> StoredTest:
    tests = db.TestRepository(connection)
    test = ir.from_document(document)
    existing = tests.by_uuid(test.id)
    stored = tests.save(project.id or 0, test)
    (report.tests_updated if existing else report.tests_added).append(test.name)
    return stored


def complete(
    connection: sqlite3.Connection,
    slug: str,
    report: ImportReport,
    references: set[str],
    secret_available: Callable[[str, str], bool],
) -> None:
    project = db.ProjectRepository(connection).by_slug(slug)
    if project is None or project.id is None:
        return
    for environment in db.EnvironmentRepository(connection).for_project(project.id):
        if environment.config.http_credentials:
            references.add(SECRET_PREFIX + environment.config.http_credentials)
    defined = {
        variable.name: variable for variable in db.VariableRepository(connection).for_project(project.id)
    }
    for reference in sorted(references):
        if reference.startswith(SECRET_PREFIX):
            name = reference[len(SECRET_PREFIX) :]
            if not secret_available(slug, name):
                report.missing_secrets.append(name)
            continue
        if reference not in defined:
            report.missing_variables.append(reference)
    tests = db.TestRepository(connection)
    for label, uuid in (("setup", project.setup_test_uuid), ("login", project.login_test_uuid)):
        if uuid and tests.by_uuid(uuid) is None:
            report.missing_tests.append(f"{label} ({uuid})")
