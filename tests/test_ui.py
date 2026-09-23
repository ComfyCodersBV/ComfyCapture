from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from browsertests.core import db, ir
from browsertests.core.models import Action, Environment, Project, Step, Test
from browsertests.ui.dialogs import RecordSetupDialog
from browsertests.ui.main_window import MainWindow
from browsertests.ui.test_editor import ReviewDialog

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def seeded():
    connection = db.connect(":memory:")
    project = db.ProjectRepository(connection).save(Project(None, "shop", "Shop"))
    environment = db.EnvironmentRepository(connection).save(
        Environment(None, project.id, "staging", "https://staging.test")
    )
    test = Test(
        id=ir.new_test_id(),
        name="Checkout",
        tags=("CINF-19",),
        steps=(Step("s1", Action.NAVIGATE, url="/"), Step("s2", Action.UNKNOWN, raw="drag")),
    )
    db.TestRepository(connection).save(project.id, test)
    return connection, project, environment, test


def test_main_window_lists_projects_and_tests(application, seeded) -> None:
    connection, *_ = seeded

    window = MainWindow(connection)

    assert window.project_list.count() == 1
    assert window.project_view.test_table.rowCount() == 1
    window.project_view.tag_filter.setText("other")
    assert window.project_view.test_table.rowCount() == 0


def test_review_dialog_edits_the_test(application, seeded) -> None:
    _, project, environment, test = seeded
    dialog = ReviewDialog(test, project, environment)

    dialog.table.selectRow(1)
    dialog._remove()
    dialog.tags.setText("cinf-19, smoke")

    result = dialog.result_test()
    assert [step.id for step in result.steps] == ["s1"]
    assert result.tags == ("CINF-19", "smoke")


def test_review_refuses_to_verify_destructive_test_on_protected_environment(
    application, seeded, monkeypatch
) -> None:
    _, project, environment, test = seeded
    warnings = []
    monkeypatch.setattr(
        "browsertests.ui.test_editor.QMessageBox.warning", lambda *args: warnings.append(args)
    )
    dialog = ReviewDialog(test, project, Environment(9, project.id, "production", "https://shop.test"))
    dialog.destructive.setChecked(True)

    dialog._verify()

    assert warnings
    assert dialog._verifier is None


def test_record_setup_offers_desktop_and_mobile(application, seeded) -> None:
    _, _, environment, _ = seeded
    dialog = RecordSetupDialog([environment])

    labels = [dialog.device.itemText(index) for index in range(dialog.device.count())]

    assert "desktop 1440x900" in labels
    assert "iPhone 15" in labels


def test_dutch_translation_is_bundled_and_loads(application, monkeypatch) -> None:
    from browsertests.ui import translations

    monkeypatch.setattr(translations, "preferred_language", lambda: "nl")

    translator = translations.install_translator(application)

    try:
        assert translator is not None
        assert translator.translate("MainWindow", "Settings") == "Instellingen"
    finally:
        application.removeTranslator(translator)


@pytest.mark.browser
def test_run_dialog_shows_live_results(application, tmp_path, site_url) -> None:
    import time

    from browsertests.ui.run_view import RunDialog

    connection = db.connect(tmp_path / "suite.sqlite")
    project = db.ProjectRepository(connection).save(Project(None, "shop", "Shop"))
    environment = db.EnvironmentRepository(connection).save(Environment(None, project.id, "local", site_url))
    passing = db.TestRepository(connection).save(
        project.id,
        Test(id=ir.new_test_id(), name="home", steps=(Step("s1", Action.NAVIGATE, url="/index.html"),)),
    )
    dialog = RunDialog(project, environment, [passing], tmp_path / "suite.sqlite")

    dialog._start()
    deadline = time.monotonic() + 60
    while dialog._process is not None and dialog._process._process.state().name != "NotRunning":
        application.processEvents()
        time.sleep(0.05)
        assert time.monotonic() < deadline
    application.processEvents()

    assert "Passed" in dialog.table.item(0, 0).text()
    assert db.RunRepository(connection).latest([passing.id])[passing.id].status.value == "passed"


def test_variables_dialog_reports_references_that_are_not_defined(application, seeded, monkeypatch) -> None:
    from browsertests.core.models import Variable
    from browsertests.ui.variables_dialog import VariablesDialog

    connection, project, _, test = seeded
    db.TestRepository(connection).save(
        project.id,
        Test(
            id=ir.new_test_id(),
            name="login",
            steps=(Step("s1", Action.NAVIGATE, url="/{{locale}}/login?pw={{secret:admin_password}}"),),
        ),
    )
    db.VariableRepository(connection).save(project.id, Variable("locale", "nl"))
    monkeypatch.setattr("browsertests.ui.variables_dialog.SecretStore.has", lambda self, name: False)

    dialog = VariablesDialog(connection, project)

    assert dialog.table.rowCount() == 1
    assert "secret:admin_password" in dialog.missing.text()
    assert "locale" not in dialog.missing.text()


def test_tag_completer_completes_the_last_tag_only(application) -> None:
    from PySide6.QtWidgets import QLineEdit

    from browsertests.ui.widgets import TagCompleter

    field = QLineEdit("CINF-19, che")
    completer = TagCompleter(["checkout", "CINF-20"], field)
    field.setCompleter(completer)
    index = completer.model().index(0, 0)

    assert completer.splitPath(field.text()) == ["che"]
    assert completer.pathFromIndex(index) == "CINF-19, checkout"


def test_step_dialog_edits_value_and_promotes_a_fallback(application) -> None:
    from browsertests.core.models import Selector, SelectorKind, Target, Variable
    from browsertests.ui.step_dialog import StepDialog

    step = Step(
        "s2",
        Action.FILL,
        target=Target(
            Selector(SelectorKind.ID, "wire-8f2a1c", suspicious=True),
            (Selector(SelectorKind.LABEL, "Email"),),
        ),
        value="jane@example.com",
        note="Password field: point this at the right secret.",
    )
    dialog = StepDialog(step, [Variable("customer_email")])

    dialog.value.setText("{{customer_email}}")
    dialog.selectors.setCurrentRow(1)
    dialog._make_primary()
    dialog.resolved.setChecked(True)
    result = dialog.result_step()

    assert result.id == "s2"
    assert result.value == "{{customer_email}}"
    assert result.target.primary.value == "Email"
    assert result.note is None


def test_step_dialog_turns_an_unknown_step_into_a_click(application) -> None:
    from browsertests.core.models import Selector, SelectorKind
    from browsertests.ui.step_dialog import StepDialog

    dialog = StepDialog(Step("s9", Action.UNKNOWN, raw="click inside an iframe"), [])
    dialog.action.setCurrentIndex(dialog.action.findData(Action.CLICK))

    assert dialog.validate() is not None
    dialog._add_selector(Selector(SelectorKind.CSS, "#pay"))
    assert dialog.validate() is None
    assert dialog.result_step().raw is None
