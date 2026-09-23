from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

import platformdirs

from browsertests.core import ir
from browsertests.core.models import (
    Environment,
    EnvironmentConfig,
    Project,
    RunRecord,
    RunStatus,
    SelectorKind,
    StoredTest,
    Test,
    Variable,
)

APP_NAME = "BrowsertestSuite"
APP_AUTHOR = "ComfyCoders"

SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE projects (
        id                 INTEGER PRIMARY KEY,
        slug               TEXT NOT NULL UNIQUE,
        name               TEXT NOT NULL,
        test_id_attributes TEXT NOT NULL DEFAULT '["data-testid"]',
        created_at         TEXT NOT NULL
    );

    CREATE TABLE environments (
        id                INTEGER PRIMARY KEY,
        project_id        INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        name              TEXT NOT NULL,
        base_url          TEXT NOT NULL,
        allow_destructive INTEGER NOT NULL DEFAULT 0,
        config            TEXT NOT NULL,
        UNIQUE (project_id, name)
    );

    CREATE TABLE tests (
        id             INTEGER PRIMARY KEY,
        project_id     INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        uuid           TEXT NOT NULL UNIQUE,
        name           TEXT NOT NULL,
        destructive    INTEGER NOT NULL DEFAULT 0,
        ir             TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        updated_at     TEXT NOT NULL
    );

    CREATE TABLE test_tags (
        test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
        tag     TEXT NOT NULL,
        PRIMARY KEY (test_id, tag)
    );

    CREATE INDEX idx_test_tags_tag ON test_tags(tag);

    CREATE TABLE runs (
        id                 INTEGER PRIMARY KEY,
        test_id            INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
        environment_id     INTEGER NOT NULL REFERENCES environments(id) ON DELETE CASCADE,
        status             TEXT NOT NULL,
        started_at         TEXT NOT NULL,
        duration_ms        INTEGER NOT NULL,
        failed_step_id     TEXT NULL,
        message            TEXT NULL,
        artifact_path      TEXT NULL,
        playwright_version TEXT NOT NULL,
        browser_version    TEXT NOT NULL
    );

    CREATE TABLE variables (
        id         INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        name       TEXT NOT NULL,
        value      TEXT NULL,
        is_secret  INTEGER NOT NULL DEFAULT 0,
        UNIQUE (project_id, name)
    );
    """,
    """
    ALTER TABLE projects ADD COLUMN setup_test_uuid TEXT NULL;
    ALTER TABLE projects ADD COLUMN login_test_uuid TEXT NULL;
    CREATE INDEX idx_runs_test ON runs(test_id, started_at);
    """,
    """
    ALTER TABLE projects ADD COLUMN selector_kinds TEXT NOT NULL DEFAULT '["id", "label", "role", "placeholder"]';
    """,
)


def data_dir() -> Path:
    return Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR))


def default_database_path() -> Path:
    return data_dir() / "browsertests.sqlite"


def database_file(connection: sqlite3.Connection) -> Path | None:
    row = connection.execute("PRAGMA database_list").fetchone()
    return Path(row[2]) if row and row[2] else None


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrate(connection)
    return connection


def migrate(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    for index, script in enumerate(SCHEMA[version:], start=version + 1):
        with connection:
            connection.executescript(script)
            connection.execute(f"PRAGMA user_version = {index}")


def config_from_json(text: str) -> EnvironmentConfig:
    document = json.loads(text)
    known = {
        name: value for name, value in document.items() if name in EnvironmentConfig.__dataclass_fields__
    }
    known["cookies"] = tuple(known.get("cookies") or ())
    return EnvironmentConfig(**known)


class ProjectRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def all(self) -> list[Project]:
        rows = self._connection.execute("SELECT * FROM projects ORDER BY name COLLATE NOCASE").fetchall()
        return [self._hydrate(row) for row in rows]

    def get(self, project_id: int) -> Project | None:
        row = self._connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return self._hydrate(row) if row else None

    def by_slug(self, slug: str) -> Project | None:
        row = self._connection.execute("SELECT * FROM projects WHERE slug = ?", (slug,)).fetchone()
        return self._hydrate(row) if row else None

    def save(self, project: Project) -> Project:
        attributes = json.dumps(list(project.test_id_attributes))
        kinds = json.dumps([kind.value for kind in project.selector_kinds])
        values = (
            project.slug,
            project.name,
            attributes,
            project.setup_test_uuid,
            project.login_test_uuid,
            kinds,
        )
        with self._connection:
            if project.id is None:
                created_at = now()
                cursor = self._connection.execute(
                    "INSERT INTO projects (slug, name, test_id_attributes, setup_test_uuid, login_test_uuid, "
                    "selector_kinds, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (*values, created_at),
                )
                return replace(project, id=cursor.lastrowid, created_at=created_at)
            self._connection.execute(
                "UPDATE projects SET slug = ?, name = ?, test_id_attributes = ?, setup_test_uuid = ?, "
                "login_test_uuid = ?, selector_kinds = ? WHERE id = ?",
                (*values, project.id),
            )
        return project

    def delete(self, project_id: int) -> None:
        with self._connection:
            self._connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    @staticmethod
    def _hydrate(row: sqlite3.Row) -> Project:
        return Project(
            id=row["id"],
            slug=row["slug"],
            name=row["name"],
            test_id_attributes=tuple(json.loads(row["test_id_attributes"])),
            created_at=row["created_at"],
            setup_test_uuid=row["setup_test_uuid"],
            login_test_uuid=row["login_test_uuid"],
            selector_kinds=tuple(SelectorKind(kind) for kind in json.loads(row["selector_kinds"])),
        )


class EnvironmentRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def for_project(self, project_id: int) -> list[Environment]:
        rows = self._connection.execute(
            "SELECT * FROM environments WHERE project_id = ? ORDER BY name COLLATE NOCASE", (project_id,)
        ).fetchall()
        return [self._hydrate(row) for row in rows]

    def get(self, environment_id: int) -> Environment | None:
        row = self._connection.execute(
            "SELECT * FROM environments WHERE id = ?", (environment_id,)
        ).fetchone()
        return self._hydrate(row) if row else None

    def by_name(self, project_id: int, name: str) -> Environment | None:
        row = self._connection.execute(
            "SELECT * FROM environments WHERE project_id = ? AND name = ?", (project_id, name)
        ).fetchone()
        return self._hydrate(row) if row else None

    def save(self, environment: Environment) -> Environment:
        config = json.dumps(asdict(environment.config), sort_keys=True)
        values = (
            environment.project_id,
            environment.name,
            environment.base_url,
            int(environment.allow_destructive),
            config,
        )
        with self._connection:
            if environment.id is None:
                cursor = self._connection.execute(
                    "INSERT INTO environments (project_id, name, base_url, allow_destructive, config) "
                    "VALUES (?, ?, ?, ?, ?)",
                    values,
                )
                return Environment(
                    cursor.lastrowid,
                    environment.project_id,
                    environment.name,
                    environment.base_url,
                    environment.allow_destructive,
                    environment.config,
                )
            self._connection.execute(
                "UPDATE environments SET project_id = ?, name = ?, base_url = ?, allow_destructive = ?, "
                "config = ? WHERE id = ?",
                (*values, environment.id),
            )
        return environment

    def delete(self, environment_id: int) -> None:
        with self._connection:
            self._connection.execute("DELETE FROM environments WHERE id = ?", (environment_id,))

    @staticmethod
    def default_allow_destructive(name: str) -> bool:
        return name.strip().lower() == "staging"

    @staticmethod
    def _hydrate(row: sqlite3.Row) -> Environment:
        return Environment(
            id=row["id"],
            project_id=row["project_id"],
            name=row["name"],
            base_url=row["base_url"],
            allow_destructive=bool(row["allow_destructive"]),
            config=config_from_json(row["config"]),
        )


class TestRepository:
    __test__ = False

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def for_project(self, project_id: int, tags: tuple[str, ...] = ()) -> list[StoredTest]:
        query = "SELECT * FROM tests WHERE project_id = ?"
        parameters: list[object] = [project_id]
        for tag in ir.normalize_tags(tags):
            query += " AND id IN (SELECT test_id FROM test_tags WHERE tag = ?)"
            parameters.append(tag)
        query += " ORDER BY name COLLATE NOCASE"
        rows = self._connection.execute(query, parameters).fetchall()
        return [self._hydrate(row) for row in rows]

    def get(self, test_id: int) -> StoredTest | None:
        row = self._connection.execute("SELECT * FROM tests WHERE id = ?", (test_id,)).fetchone()
        return self._hydrate(row) if row else None

    def by_uuid(self, uuid: str) -> StoredTest | None:
        row = self._connection.execute("SELECT * FROM tests WHERE uuid = ?", (uuid,)).fetchone()
        return self._hydrate(row) if row else None

    def save(self, project_id: int, test: Test) -> StoredTest:
        test = replace(test, tags=ir.normalize_tags(test.tags))
        document = ir.dumps(test)
        updated_at = now()
        with self._connection:
            existing = self._connection.execute("SELECT id FROM tests WHERE uuid = ?", (test.id,)).fetchone()
            if existing is None:
                cursor = self._connection.execute(
                    "INSERT INTO tests (project_id, uuid, name, destructive, ir, schema_version, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        project_id,
                        test.id,
                        test.name,
                        int(test.destructive),
                        document,
                        ir.SCHEMA_VERSION,
                        updated_at,
                    ),
                )
                row_id = int(cursor.lastrowid or 0)
            else:
                row_id = existing["id"]
                self._connection.execute(
                    "UPDATE tests SET project_id = ?, name = ?, destructive = ?, ir = ?, schema_version = ?, "
                    "updated_at = ? WHERE id = ?",
                    (
                        project_id,
                        test.name,
                        int(test.destructive),
                        document,
                        ir.SCHEMA_VERSION,
                        updated_at,
                        row_id,
                    ),
                )
            self._connection.execute("DELETE FROM test_tags WHERE test_id = ?", (row_id,))
            self._connection.executemany(
                "INSERT INTO test_tags (test_id, tag) VALUES (?, ?)", [(row_id, tag) for tag in test.tags]
            )
        return StoredTest(row_id, project_id, test, updated_at)

    def delete(self, test_id: int) -> None:
        with self._connection:
            self._connection.execute("DELETE FROM tests WHERE id = ?", (test_id,))

    def tags(self, project_id: int) -> list[str]:
        rows = self._connection.execute(
            "SELECT DISTINCT tag FROM test_tags JOIN tests ON tests.id = test_tags.test_id "
            "WHERE tests.project_id = ? ORDER BY tag",
            (project_id,),
        ).fetchall()
        return [row["tag"] for row in rows]

    @staticmethod
    def _hydrate(row: sqlite3.Row) -> StoredTest:
        return StoredTest(row["id"], row["project_id"], ir.loads(row["ir"]), row["updated_at"])


class RunRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, run: RunRecord) -> RunRecord:
        with self._connection:
            cursor = self._connection.execute(
                "INSERT INTO runs (test_id, environment_id, status, started_at, duration_ms, failed_step_id, "
                "message, artifact_path, playwright_version, browser_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.test_id,
                    run.environment_id,
                    run.status.value,
                    run.started_at,
                    run.duration_ms,
                    run.failed_step_id,
                    run.message,
                    run.artifact_path,
                    run.playwright_version,
                    run.browser_version,
                ),
            )
        return replace(run, id=cursor.lastrowid)

    def for_test(self, test_id: int, limit: int = 20) -> list[RunRecord]:
        rows = self._connection.execute(
            "SELECT * FROM runs WHERE test_id = ? ORDER BY started_at DESC, id DESC LIMIT ?", (test_id, limit)
        ).fetchall()
        return [self._hydrate(row) for row in rows]

    def latest(self, test_ids: list[int]) -> dict[int, RunRecord]:
        if not test_ids:
            return {}
        placeholders = ", ".join("?" for _ in test_ids)
        rows = self._connection.execute(
            f"SELECT * FROM runs WHERE id IN (SELECT MAX(id) FROM runs WHERE test_id IN ({placeholders}) "
            "GROUP BY test_id)",
            test_ids,
        ).fetchall()
        return {row["test_id"]: self._hydrate(row) for row in rows}

    def with_artifacts_before(self, started_before: str) -> list[RunRecord]:
        rows = self._connection.execute(
            "SELECT * FROM runs WHERE artifact_path IS NOT NULL AND started_at < ?", (started_before,)
        ).fetchall()
        return [self._hydrate(row) for row in rows]

    def clear_artifact(self, run_id: int) -> None:
        with self._connection:
            self._connection.execute("UPDATE runs SET artifact_path = NULL WHERE id = ?", (run_id,))

    @staticmethod
    def _hydrate(row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            id=row["id"],
            test_id=row["test_id"],
            environment_id=row["environment_id"],
            status=RunStatus(row["status"]),
            started_at=row["started_at"],
            duration_ms=row["duration_ms"],
            playwright_version=row["playwright_version"],
            browser_version=row["browser_version"],
            failed_step_id=row["failed_step_id"],
            message=row["message"],
            artifact_path=row["artifact_path"],
        )


class VariableRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def for_project(self, project_id: int) -> list[Variable]:
        rows = self._connection.execute(
            "SELECT name, value, is_secret FROM variables WHERE project_id = ? ORDER BY name", (project_id,)
        ).fetchall()
        return [Variable(row["name"], row["value"], bool(row["is_secret"])) for row in rows]

    def values(self, project_id: int) -> dict[str, str]:
        return {
            variable.name: variable.value or ""
            for variable in self.for_project(project_id)
            if not variable.is_secret
        }

    def save(self, project_id: int, variable: Variable) -> None:
        value = None if variable.is_secret else (variable.value or "")
        with self._connection:
            self._connection.execute(
                "INSERT INTO variables (project_id, name, value, is_secret) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (project_id, name) DO UPDATE SET value = excluded.value, is_secret = excluded.is_secret",
                (project_id, variable.name, value, int(variable.is_secret)),
            )

    def delete(self, project_id: int, name: str) -> None:
        with self._connection:
            self._connection.execute(
                "DELETE FROM variables WHERE project_id = ? AND name = ?", (project_id, name)
            )
