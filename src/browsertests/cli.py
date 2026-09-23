from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from browsertests import __version__

EXIT_PASSED = 0
EXIT_FAILED = 1
EXIT_CONFIGURATION = 2
DATABASE_VARIABLE = "BROWSERTESTS_DATABASE"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="browsertests", description="Replay recorded browser tests.")
    parser.add_argument("--version", action="version", version=f"browsertests {__version__}")
    parser.add_argument(
        "--database", help=f"SQLite database (default: ${DATABASE_VARIABLE} or the user data dir)"
    )
    commands = parser.add_subparsers(dest="command")

    run = commands.add_parser("run", help="run tests against one environment")
    run.add_argument("--project", required=True, help="project slug")
    run.add_argument("--env", required=True, help="environment name")
    run.add_argument("--test", action="append", default=[], help="test uuid or exact name (repeatable)")
    run.add_argument("--tag", action="append", default=[], help="only tests with this tag (repeatable, ANDs)")
    run.add_argument("--headed", action="store_true", help="show the browser")
    run.add_argument("--retries", type=int, default=None, help="retries for a failing test (default 1)")
    run.add_argument("--workers", type=int, default=None, help="tests in parallel (default 2)")
    run.add_argument("--jsonl", action="store_true", help="machine-readable JSON lines on stdout")

    exporting = commands.add_parser("export", help="export tests as JSON files, one per test")
    exporting.add_argument("--project", required=True, help="project slug")
    exporting.add_argument(
        "--tag", action="append", default=[], help="only tests with this tag (repeatable, ANDs)"
    )
    exporting.add_argument("--out", required=True, help="directory to write the files to")

    importing = commands.add_parser("import", help="import exported JSON files")
    importing.add_argument("files", nargs="+", help="exported .json files")

    listing = commands.add_parser("list", help="list the tests of a project")
    listing.add_argument("--project", required=True, help="project slug")
    listing.add_argument(
        "--tag", action="append", default=[], help="only tests with this tag (repeatable, ANDs)"
    )
    return parser


def database_path(argument: str | None) -> Path:
    from browsertests.core import db

    if argument:
        return Path(argument)
    if os.environ.get(DATABASE_VARIABLE):
        return Path(os.environ[DATABASE_VARIABLE])
    return db.default_database_path()


def fail(message: str) -> int:
    sys.stderr.write(f"error: {message}\n")
    return EXIT_CONFIGURATION


def select_tests(stored: list[Any], names: list[str]) -> tuple[list[Any], list[str]]:
    if not names:
        return stored, []
    selected = [item for item in stored if item.test.id in names or item.test.name in names]
    found = {item.test.id for item in selected} | {item.test.name for item in selected}
    return selected, [name for name in names if name not in found]


def command_list(arguments: argparse.Namespace) -> int:
    from browsertests.core import db

    connection = db.connect(database_path(arguments.database))
    project = db.ProjectRepository(connection).by_slug(arguments.project)
    if project is None:
        return fail(f"unknown project {arguments.project!r}")
    for stored in db.TestRepository(connection).for_project(project.id or 0, tuple(arguments.tag)):
        role = ""
        if stored.test.id == project.setup_test_uuid:
            role = " [setup]"
        if stored.test.id == project.login_test_uuid:
            role = " [login]"
        tags = ", ".join(stored.test.tags)
        print(
            f"{stored.test.id}  {stored.test.name}{role}  ({stored.test.device.label}; {tags or 'no tags'})"
        )
    return EXIT_PASSED


def command_run(arguments: argparse.Namespace) -> int:
    from browsertests.core import db, runner, suite
    from browsertests.core.secrets import SecretStore

    connection = db.connect(database_path(arguments.database))
    project = db.ProjectRepository(connection).by_slug(arguments.project)
    if project is None or project.id is None:
        return fail(f"unknown project {arguments.project!r}")
    environment = db.EnvironmentRepository(connection).by_name(project.id, arguments.env)
    if environment is None:
        return fail(f"project {project.slug!r} has no environment {arguments.env!r}")

    tests = db.TestRepository(connection)
    special = {project.setup_test_uuid, project.login_test_uuid} - {None}
    candidates = [
        stored
        for stored in tests.for_project(project.id, tuple(arguments.tag))
        if stored.test.id not in special or arguments.test
    ]
    selected, unknown = select_tests(candidates, arguments.test)
    if unknown:
        return fail("unknown test(s): " + ", ".join(unknown))
    if not selected:
        return fail("no tests match the selection")

    plan = suite.SuitePlan(
        project=project,
        environment=environment,
        tests=tuple(selected),
        artifact_root=db.data_dir() / "artifacts" / project.slug,
        setup=tests.by_uuid(project.setup_test_uuid) if project.setup_test_uuid else None,
        login=tests.by_uuid(project.login_test_uuid) if project.login_test_uuid else None,
        headed=arguments.headed,
        retries=suite.DEFAULT_RETRIES if arguments.retries is None else arguments.retries,
        workers=suite.DEFAULT_WORKERS if arguments.workers is None else arguments.workers,
    )
    variables = db.VariableRepository(connection).values(project.id)
    resolver = runner.VariableResolver(variables, SecretStore(project.slug).get)

    def emit(message: dict[str, Any]) -> None:
        if arguments.jsonl:
            sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            return
        if message.get("type") == "test_finished":
            print_result(message["result"])

    started_at = db.now()
    execution = suite.SuiteRunner(plan, resolver, emit)
    try:
        results = execution.run()
    except suite.ConfigurationError as error:
        return fail(str(error))

    runs = db.RunRepository(connection)
    suite.record_results(runs, environment, results, started_at, execution.browser_version)
    suite.prune_artifacts(runs)
    code = suite.exit_code(results)
    summary = {
        "type": "summary",
        "exit_code": code,
        "counts": {
            status: sum(1 for result in results if result.status.value == status)
            for status in ("passed", "flaky", "failed", "error", "skipped")
        },
        "playwright": suite.playwright_version(),
        "browser": execution.browser_version,
    }
    if arguments.jsonl:
        emit(summary)
    else:
        counts = ", ".join(f"{count} {status}" for status, count in summary["counts"].items() if count)
        print(f"\n{counts}  (Playwright {summary['playwright']}, Chromium {summary['browser']})")
    return code


def command_export(arguments: argparse.Namespace) -> int:
    from browsertests.core import db, exchange

    connection = db.connect(database_path(arguments.database))
    project = db.ProjectRepository(connection).by_slug(arguments.project)
    if project is None or project.id is None:
        return fail(f"unknown project {arguments.project!r}")
    tests = db.TestRepository(connection).for_project(project.id, tuple(arguments.tag))
    if not tests:
        return fail("no tests match the selection")
    directory = Path(arguments.out)
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in exchange.export_tests(connection, project, tests):
        (directory / name).write_text(text, encoding="utf-8")
        print(directory / name)
    return EXIT_PASSED


def command_import(arguments: argparse.Namespace) -> int:
    from browsertests.core import db, exchange
    from browsertests.core.secrets import SecretStore

    documents = []
    for file in arguments.files:
        try:
            documents.append(json.loads(Path(file).read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as error:
            return fail(f"{file}: {error}")
    connection = db.connect(database_path(arguments.database))
    try:
        reports = exchange.import_documents(
            connection, documents, lambda slug, name: SecretStore(slug).has(name)
        )
    except exchange.ExchangeError as error:
        return fail(str(error))
    for report in reports:
        print("\n".join(report.lines()))
    return EXIT_PASSED if all(report.ready for report in reports) else EXIT_CONFIGURATION


def print_result(result: dict[str, Any]) -> None:
    label = {"passed": "PASS", "flaky": "FLAKY", "failed": "FAIL", "error": "ERROR", "skipped": "SKIP"}[
        result["status"]
    ]
    seconds = result["duration_ms"] / 1000
    print(f"{label:<6} {result['name']}  ({seconds:.1f}s)")
    if result.get("message"):
        print(f"       {result['message']}")
    if result.get("artifact_path"):
        print(f"       trace: {result['artifact_path']}/trace.zip")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "run":
        return command_run(arguments)
    if arguments.command == "list":
        return command_list(arguments)
    if arguments.command == "export":
        return command_export(arguments)
    if arguments.command == "import":
        return command_import(arguments)
    parser.print_help()
    return EXIT_PASSED


if __name__ == "__main__":
    sys.exit(main())
