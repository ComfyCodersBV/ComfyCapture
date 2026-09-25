from __future__ import annotations

from dataclasses import replace

import pytest

from comfycapture.core import db
from comfycapture.core.models import Action, Environment, Project, Step, Test


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


def test_secret_values_never_reach_the_database(connection, project: Project) -> None:
    from comfycapture.core.models import Variable

    variables = db.VariableRepository(connection)
    variables.save(project.id, Variable("order", "42"))
    variables.save(project.id, Variable("admin_password", "hunter2", is_secret=True))
    variables.save(project.id, Variable("order", "43"))

    assert variables.values(project.id) == {"order": "43"}
    assert "hunter2" not in str(connection.execute("SELECT * FROM variables").fetchall())


def test_selector_kinds_round_trip(connection) -> None:
    from comfycapture.core.models import SelectorKind

    projects = db.ProjectRepository(connection)
    saved = projects.save(Project(None, "lean", "Lean", selector_kinds=(SelectorKind.LABEL,)))

    assert projects.get(saved.id).selector_kinds == (SelectorKind.LABEL,)


def test_secrets_come_from_environment_then_file(tmp_path) -> None:
    from comfycapture.core.secrets import SecretStore

    secrets = tmp_path / "secrets.env"
    secrets.write_text(
        "# server secrets\nCOMFYCAPTURE_SECRET_ADMIN_PASSWORD='from-file'\nCOMFYCAPTURE_SECRET_VOUCHER=abc\n"
    )
    environ = {"COMFYCAPTURE_SECRETS_FILE": str(secrets), "COMFYCAPTURE_SECRET_VOUCHER": "from-env"}
    store = SecretStore("shop", environ=environ, use_keyring=False)

    assert store.get("admin_password") == "from-file"
    assert store.get("voucher") == "from-env"
    assert store.get("missing") is None


def test_legacy_data_dir_moves_into_the_new_one_without_overwriting(tmp_path) -> None:
    legacy = tmp_path / "BrowsertestSuite"
    target = tmp_path / "ComfyCapture"
    (legacy / "artifacts" / "shop").mkdir(parents=True)
    (legacy / db.LEGACY_DATABASE_NAME).write_text("old database")
    (legacy / "browsers").mkdir()
    (target / "browsers").mkdir(parents=True)

    db.migrate_legacy_data_dir(legacy, target)

    assert (target / db.DATABASE_NAME).read_text() == "old database"
    assert (target / "artifacts" / "shop").is_dir()
    assert (legacy / "browsers").is_dir()
    assert not (legacy / db.LEGACY_DATABASE_NAME).exists()


def test_legacy_keyring_secret_moves_to_the_new_service(monkeypatch) -> None:
    import keyring
    from keyring.errors import PasswordDeleteError

    from comfycapture.core.secrets import SecretStore

    passwords = {("BrowsertestSuite/shop", "admin_password"): "hunter2"}

    def delete_password(service: str, name: str) -> None:
        if passwords.pop((service, name), None) is None:
            raise PasswordDeleteError(name)

    monkeypatch.setattr(keyring, "get_password", lambda service, name: passwords.get((service, name)))
    monkeypatch.setattr(
        keyring, "set_password", lambda service, name, value: passwords.update({(service, name): value})
    )
    monkeypatch.setattr(keyring, "delete_password", delete_password)
    store = SecretStore("shop", environ={})

    assert store.get("admin_password") == "hunter2"
    assert passwords == {("ComfyCapture/shop", "admin_password"): "hunter2"}
