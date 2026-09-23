from __future__ import annotations

import re

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QWidget,
)

from browsertests.core import ir
from browsertests.core.db import EnvironmentRepository
from browsertests.core.models import Device, DeviceKind, Environment, EnvironmentConfig, Project

DESKTOP_SIZES = ((1440, 900), (1280, 720), (1920, 1080))
MOBILE_DEVICES = ("iPhone 15", "iPhone SE", "Pixel 7", "Galaxy S24", "iPad Mini")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def device_choices() -> list[Device]:
    desktops = [Device(DeviceKind.DESKTOP, width=width, height=height) for width, height in DESKTOP_SIZES]
    mobiles = [Device(DeviceKind.MOBILE, name=name) for name in MOBILE_DEVICES]
    return desktops + mobiles


def split_list(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.split(",") if part.strip())


class FormDialog(QDialog):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.form = QFormLayout(self)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)

    def finish_layout(self) -> None:
        self.form.addRow(self.buttons)
        self.setMinimumWidth(460)

    def validate(self) -> str | None:
        return None

    def _accept(self) -> None:
        problem = self.validate()
        if problem is not None:
            QMessageBox.warning(self, self.windowTitle(), problem)
            return
        self.accept()


class ProjectDialog(FormDialog):
    def __init__(self, project: Project | None = None, parent: QWidget | None = None) -> None:
        super().__init__(self.tr("Project"), parent)
        self._project = project
        self.name = QLineEdit(project.name if project else "")
        self.slug = QLineEdit(project.slug if project else "")
        self.attributes = QLineEdit(", ".join(project.test_id_attributes) if project else "data-testid, dusk")
        self.attributes.setToolTip(self.tr("Test attributes in order of preference, comma separated."))
        if project is None:
            self.name.textChanged.connect(lambda text: self.slug.setText(slugify(text)))
        self.form.addRow(self.tr("Name"), self.name)
        self.form.addRow(self.tr("Slug"), self.slug)
        self.form.addRow(self.tr("Test attributes"), self.attributes)
        self.finish_layout()

    def validate(self) -> str | None:
        if not self.name.text().strip():
            return self.tr("A project needs a name.")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.slug.text().strip()):
            return self.tr("The slug may only contain lowercase letters, digits and dashes.")
        return None

    def result_project(self) -> Project:
        attributes = split_list(self.attributes.text()) or ("data-testid",)
        return Project(
            id=self._project.id if self._project else None,
            slug=self.slug.text().strip(),
            name=self.name.text().strip(),
            test_id_attributes=attributes,
            created_at=self._project.created_at if self._project else "",
        )


class EnvironmentDialog(FormDialog):
    def __init__(
        self, project_id: int, environment: Environment | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(self.tr("Environment"), parent)
        self._project_id = project_id
        self._environment = environment
        config = environment.config if environment else EnvironmentConfig()
        self.name = QLineEdit(environment.name if environment else "staging")
        self.base_url = QLineEdit(environment.base_url if environment else "https://")
        self.allow_destructive = QCheckBox(self.tr("Allow destructive tests (orders, e-mails, payments)"))
        self.allow_destructive.setChecked(
            environment.allow_destructive
            if environment
            else EnvironmentRepository.default_allow_destructive("staging")
        )
        if environment is None:
            self.name.textChanged.connect(
                lambda text: self.allow_destructive.setChecked(
                    EnvironmentRepository.default_allow_destructive(text)
                )
            )
        self.locale = QLineEdit(config.locale or "")
        self.locale.setPlaceholderText("nl-NL")
        self.timezone = QLineEdit(config.timezone or "")
        self.timezone.setPlaceholderText("Europe/Amsterdam")
        self.ignore_https_errors = QCheckBox(self.tr("Ignore HTTPS certificate errors"))
        self.ignore_https_errors.setChecked(config.ignore_https_errors)
        self.form.addRow(self.tr("Name"), self.name)
        self.form.addRow(self.tr("Base URL"), self.base_url)
        self.form.addRow("", self.allow_destructive)
        self.form.addRow(self.tr("Locale"), self.locale)
        self.form.addRow(self.tr("Timezone"), self.timezone)
        self.form.addRow("", self.ignore_https_errors)
        self.finish_layout()

    def validate(self) -> str | None:
        if not self.name.text().strip():
            return self.tr("An environment needs a name.")
        if not re.match(r"^https?://[^/\s]+", self.base_url.text().strip()):
            return self.tr("The base URL must start with http:// or https://.")
        return None

    def result_environment(self) -> Environment:
        existing = self._environment.config if self._environment else EnvironmentConfig()
        return Environment(
            id=self._environment.id if self._environment else None,
            project_id=self._project_id,
            name=self.name.text().strip(),
            base_url=self.base_url.text().strip().rstrip("/"),
            allow_destructive=self.allow_destructive.isChecked(),
            config=EnvironmentConfig(
                locale=self.locale.text().strip() or None,
                timezone=self.timezone.text().strip() or None,
                ignore_https_errors=self.ignore_https_errors.isChecked(),
                http_credentials=existing.http_credentials,
            ),
        )


class RecordSetupDialog(FormDialog):
    def __init__(self, environments: list[Environment], parent: QWidget | None = None) -> None:
        super().__init__(self.tr("Record a new test"), parent)
        self.name = QLineEdit()
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("CINF-19, checkout")
        self.environment = QComboBox()
        for environment in environments:
            self.environment.addItem(f"{environment.name} — {environment.base_url}", environment.id)
        self.device = QComboBox()
        for device in device_choices():
            self.device.addItem(device.label, device)
        self.start_path = QLineEdit("/")
        self.form.addRow(self.tr("Name"), self.name)
        self.form.addRow(self.tr("Tags"), self.tags)
        self.form.addRow(self.tr("Environment"), self.environment)
        self.form.addRow(self.tr("Device"), self.device)
        self.form.addRow(self.tr("Start path"), self.start_path)
        self.finish_layout()

    def validate(self) -> str | None:
        if not self.name.text().strip():
            return self.tr("A test needs a name.")
        if self.environment.currentData() is None:
            return self.tr("Add an environment to this project first.")
        return None

    def environment_id(self) -> int:
        return int(self.environment.currentData())

    def selected_device(self) -> Device:
        return self.device.currentData()

    def test_tags(self) -> tuple[str, ...]:
        return ir.normalize_tags(split_list(self.tags.text()))
