from __future__ import annotations

from dataclasses import replace

import pytest

from browsertests.core import db
from browsertests.core.models import Action, Environment, Project, Step, Test


@pytest.fixture
def connection():
    connection = db.connect(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def project(connection) -> Project:
    return db.ProjectRepository(connection).save(Project(None, "shop", "Shop", ("dusk", "data-testid")))


def make_test(test_id: str, tags: tuple[str, ...]) -> Test:
    return Test(id=test_id, name=test_id, tags=tags, steps=(Step("s1", Action.NAVIGATE, url="/"),))


def test_tag_filter_ands_tags(connection, project: Project) -> None:
    tests = db.TestRepository(connection)
    tests.save(project.id, make_test("a", ("CINF-19", "checkout")))
    tests.save(project.id, make_test("b", ("CINF-19",)))

    assert [stored.test.id for stored in tests.for_project(project.id, ("cinf-19",))] == ["a", "b"]
    assert [stored.test.id for stored in tests.for_project(project.id, ("CINF-19", "checkout"))] == ["a"]


def test_saving_rewrites_tag_index(connection, project: Project) -> None:
    tests = db.TestRepository(connection)
    stored = tests.save(project.id, make_test("a", ("old",)))
    tests.save(project.id, replace(stored.test, tags=("new",)))

    assert tests.tags(project.id) == ["new"]
    assert tests.get(stored.id).test.tags == ("new",)


def test_deleting_project_cascades(connection, project: Project) -> None:
    db.EnvironmentRepository(connection).save(
        Environment(None, project.id, "staging", "https://staging.test")
    )
    db.TestRepository(connection).save(project.id, make_test("a", ()))

    db.ProjectRepository(connection).delete(project.id)

    assert connection.execute("SELECT COUNT(*) FROM tests").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM environments").fetchone()[0] == 0


def test_only_staging_allows_destructive_by_default() -> None:
    assert db.EnvironmentRepository.default_allow_destructive(" Staging")
    assert not db.EnvironmentRepository.default_allow_destructive("production")


def test_migrate_is_idempotent(tmp_path) -> None:
    path = tmp_path / "suite.sqlite"
    db.connect(path).close()

    connection = db.connect(path)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == len(db.SCHEMA)
