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
