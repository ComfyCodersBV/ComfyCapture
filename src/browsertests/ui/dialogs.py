from __future__ import annotations

import re

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from browsertests.core import ir
from browsertests.core.db import EnvironmentRepository
from browsertests.core.models import (
    DEFAULT_TEST_ID_ATTRIBUTES,
    Device,
    DeviceKind,
    Environment,
    EnvironmentConfig,
    Project,
    StoredTest,
)
from browsertests.ui.icons import icon
from browsertests.ui.widgets import IconButton, field_label, hint

DESKTOP_SIZES = ((1920, 1080), (1440, 900), (1280, 720))

MOBILE_DEVICES = ("iPhone 15", "iPhone SE", "Pixel 7", "Galaxy S24", "iPad Mini")
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def device_choices() -> list[Device]:
    fullscreen = [Device(DeviceKind.DESKTOP, fullscreen=True)]
    desktops = [Device(DeviceKind.DESKTOP, width=width, height=height) for width, height in DESKTOP_SIZES]
    mobiles = [Device(DeviceKind.MOBILE, name=name) for name in MOBILE_DEVICES]
    return fullscreen + desktops + mobiles


def split_list(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.split(",") if part.strip())


def normalize_base_url(text: str) -> str:
    return text.strip().rstrip("/")


class FormDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(520)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(24, 22, 24, 20)
        self.layout_.setSpacing(6)
        self.error = QLabel()
        self.error.setObjectName("Required")
        self.error.setWordWrap(True)
        self.error.hide()

    def set_heading(self, title: str, subtitle: str = "") -> None:
        self.setWindowTitle(title)
        heading = QLabel(title)
        heading.setObjectName("PageTitle")
        self.layout_.addWidget(heading)
        if subtitle:
            text = QLabel(subtitle)
            text.setObjectName("Muted")
            text.setWordWrap(True)
            self.layout_.addWidget(text)
        self.layout_.addSpacing(10)

    def add_field(self, label: str, widget: QWidget, required: bool, help_text: str = "") -> None:
        self.layout_.addWidget(field_label(label, required))
        self.layout_.addWidget(widget)
        if help_text:
            self.layout_.addWidget(hint(help_text))
        self.layout_.addSpacing(8)

    def add_widget(self, widget: QWidget) -> None:
        self.layout_.addWidget(widget)
        self.layout_.addSpacing(4)

    def finish_layout(self, accept_text: str, accept_icon: str = "check") -> None:
        self.layout_.addStretch()
        self.layout_.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(IconButton(self.tr("Cancel"), variant="ghost", on_click=self.reject))
        self.accept_button = IconButton(accept_text, accept_icon, "primary", self._accept)
        self.accept_button.setDefault(True)
        buttons.addWidget(self.accept_button)
        self.layout_.addSpacing(8)
        self.layout_.addLayout(buttons)

    def validate(self) -> tuple[str, QWidget] | None:
        return None

    def _accept(self) -> None:
        for field in self.findChildren(QLineEdit):
            field.setProperty("invalid", False)
            field.style().polish(field)
        problem = self.validate()
        if problem is None:
            self.accept()
            return
        message, widget = problem
        widget.setProperty("invalid", True)
        widget.style().polish(widget)
        widget.setFocus()
        self.error.setText(message)
        self.error.show()


class ProjectDialog(FormDialog):
    def __init__(
        self,
        project: Project | None = None,
        parent: QWidget | None = None,
        tests: list[StoredTest] | None = None,
    ) -> None:
        super().__init__(parent)
        self.set_heading(
            self.tr("Edit project") if project else self.tr("New project"),
            self.tr("A project groups the environments and tests of one website or application."),
        )
        self._project = project
        self.name = QLineEdit(project.name if project else "")
        self.name.setPlaceholderText(self.tr("e.g. ComfyConsole"))
        self.slug = QLineEdit(project.slug if project else "")
        self.slug.setPlaceholderText("comfyconsole")
        attributes = project.test_id_attributes if project else DEFAULT_TEST_ID_ATTRIBUTES
        self.attributes = QLineEdit(", ".join(attributes))
        if project is None:
            self.name.textChanged.connect(lambda text: self.slug.setText(slugify(text)))
        self.add_field(self.tr("Name"), self.name, required=True)
        self.add_field(
            self.tr("Slug"),
            self.slug,
            required=True,
            help_text=self.tr("Used on the command line: browsertests run --project <slug>."),
        )
        self.add_field(
            self.tr("Test attributes"),
            self.attributes,
            required=False,
            help_text=self.tr(
                "Attributes developers put on elements for tests, most preferred first. The defaults cover "
                "the common conventions (Cypress, Laravel Dusk, Livewire, form field names); ids, labels "
                "and roles are always used as well."
            ),
        )
        self.setup_test = self._test_choice(tests or [], project.setup_test_uuid if project else None)
        self.login_test = self._test_choice(tests or [], project.login_test_uuid if project else None)
        if tests:
            self.add_field(
                self.tr("Setup test"),
                self.setup_test,
                required=False,
                help_text=self.tr(
                    "Runs before every test in the same browser, e.g. accepting the cookie banner."
                ),
            )
            self.add_field(
                self.tr("Login test"),
                self.login_test,
                required=False,
                help_text=self.tr(
                    "Runs once before a run; every test then starts logged in with its session."
                ),
            )
        self.finish_layout(self.tr("Save project"))

    def _test_choice(self, tests: list[StoredTest], selected: str | None) -> QComboBox:
        choice = QComboBox()
        choice.addItem(self.tr("None"), None)
        for stored in tests:
            choice.addItem(stored.test.name, stored.test.id)
        index = choice.findData(selected)
        choice.setCurrentIndex(max(0, index))
        return choice

    def validate(self) -> tuple[str, QWidget] | None:
        if not self.name.text().strip():
            return self.tr("A project needs a name."), self.name
        if not SLUG_PATTERN.fullmatch(self.slug.text().strip()):
            return self.tr("The slug may only contain lowercase letters, digits and dashes."), self.slug
        return None

    def result_project(self) -> Project:
        attributes = split_list(self.attributes.text()) or DEFAULT_TEST_ID_ATTRIBUTES
        return Project(
            id=self._project.id if self._project else None,
            slug=self.slug.text().strip(),
            name=self.name.text().strip(),
            test_id_attributes=attributes,
            created_at=self._project.created_at if self._project else "",
            setup_test_uuid=self.setup_test.currentData(),
            login_test_uuid=self.login_test.currentData(),
        )


class EnvironmentDialog(FormDialog):
    def __init__(
        self, project_id: int, environment: Environment | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.set_heading(
            self.tr("Edit environment") if environment else self.tr("New environment"),
            self.tr("Tests store paths, not full URLs, so the same test runs against every environment."),
        )
        self._project_id = project_id
        self._environment = environment
        config = environment.config if environment else EnvironmentConfig()
        self.name = QLineEdit(environment.name if environment else "staging")
        self.base_url = QLineEdit(environment.base_url if environment else "")
        self.base_url.setPlaceholderText("https://staging.example.com")
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
        self.cookies = QLineEdit("; ".join(config.cookies))
        self.cookies.setPlaceholderText("CookieConsent=true; locale=nl")
        self.http_credentials = QLineEdit(config.http_credentials or "")
        self.http_credentials.setPlaceholderText("staging_basic_auth")
        self.add_field(self.tr("Name"), self.name, required=True)
        self.add_field(
            self.tr("Base URL"),
            self.base_url,
            required=True,
            help_text=self.tr("With or without a trailing slash, both work."),
        )
        self.add_widget(self.allow_destructive)
        self.add_widget(hint(self.tr("Only staging allows destructive tests by default.")))
        self.layout_.addSpacing(8)
        self.add_field(self.tr("Locale"), self.locale, required=False)
        self.add_field(self.tr("Timezone"), self.timezone, required=False)
        self.add_field(
            self.tr("Cookies"),
            self.cookies,
            required=False,
            help_text=self.tr(
                "Set before every test, e.g. a consent cookie so the cookie banner never appears. "
                "Separate cookies with a semicolon."
            ),
        )
        self.add_field(
            self.tr("Basic auth secret"),
            self.http_credentials,
            required=False,
            help_text=self.tr("Name of a secret holding user:password, for HTTP basic auth on staging."),
        )
        self.add_widget(self.ignore_https_errors)
        self.finish_layout(self.tr("Save environment"))

    def validate(self) -> tuple[str, QWidget] | None:
        if not self.name.text().strip():
            return self.tr("An environment needs a name."), self.name
        if not re.match(r"^https?://[^/\s]+", self.base_url.text().strip()):
            return self.tr("The base URL must start with http:// or https://."), self.base_url
        return None

    def result_environment(self) -> Environment:
        return Environment(
            id=self._environment.id if self._environment else None,
            project_id=self._project_id,
            name=self.name.text().strip(),
            base_url=normalize_base_url(self.base_url.text()),
            allow_destructive=self.allow_destructive.isChecked(),
            config=EnvironmentConfig(
                locale=self.locale.text().strip() or None,
                timezone=self.timezone.text().strip() or None,
                ignore_https_errors=self.ignore_https_errors.isChecked(),
                http_credentials=self.http_credentials.text().strip() or None,
                cookies=tuple(part.strip() for part in self.cookies.text().split(";") if "=" in part),
            ),
        )


class RecordSetupDialog(FormDialog):
    def __init__(self, environments: list[Environment], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.set_heading(
            self.tr("Record a new test"),
            self.tr("A browser opens on the start page. Everything you click and type becomes a step."),
        )
        self.name = QLineEdit()
        self.name.setPlaceholderText(self.tr("e.g. Guest checkout"))
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("CINF-19, checkout")
        self.environment = QComboBox()
        for environment in environments:
            self.environment.addItem(f"{environment.name}  ·  {environment.base_url}", environment.id)
        self.device = QComboBox()
        for device in device_choices():
            label = self.tr("Desktop, full screen") if device.fullscreen else device.label
            glyph = "phone" if device.is_mobile else "monitor"
            self.device.addItem(icon(glyph, self.palette().text().color().name(), 16), label, device)
        self.start_path = QLineEdit("/")
        self.add_field(self.tr("Name"), self.name, required=True)
        self.add_field(self.tr("Environment"), self.environment, required=True)
        self.add_field(
            self.tr("Device"),
            self.device,
            required=True,
            help_text=self.tr(
                "Full screen opens a normal browser window that the page follows. A fixed size or a mobile "
                "device is shown inside the app, centred in a device frame, and the test replays at that size."
            ),
        )
        self.add_field(self.tr("Start path"), self.start_path, required=False)
        self.add_field(
            self.tr("Tags"),
            self.tags,
            required=False,
            help_text=self.tr("Comma separated. Ticket keys such as CINF-19 are recognised."),
        )
        self.finish_layout(self.tr("Start recording"), "record")

    def validate(self) -> tuple[str, QWidget] | None:
        if not self.name.text().strip():
            return self.tr("A test needs a name."), self.name
        if self.environment.currentData() is None:
            return self.tr("Add an environment to this project first."), self.environment
        return None

    def environment_id(self) -> int:
        return int(self.environment.currentData())

    def selected_device(self) -> Device:
        return self.device.currentData()

    def test_tags(self) -> tuple[str, ...]:
        return ir.normalize_tags(split_list(self.tags.text()))
