from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Action(StrEnum):
    NAVIGATE = "navigate"
    CLICK = "click"
    DBLCLICK = "dblclick"
    TAP = "tap"
    FILL = "fill"
    PRESS = "press"
    CHECK = "check"
    UNCHECK = "uncheck"
    SELECT_OPTION = "selectOption"
    HOVER = "hover"
    SET_INPUT_FILES = "setInputFiles"
    ASSERT_VISIBLE = "assertVisible"
    ASSERT_TEXT = "assertText"
    ASSERT_VALUE = "assertValue"
    ASSERT_CHECKED = "assertChecked"
    UNKNOWN = "unknown"


TARGETED_ACTIONS = frozenset(action for action in Action if action not in (Action.NAVIGATE, Action.UNKNOWN))
VALUE_ACTIONS = frozenset(
    {
        Action.FILL,
        Action.PRESS,
        Action.SELECT_OPTION,
        Action.SET_INPUT_FILES,
        Action.ASSERT_TEXT,
        Action.ASSERT_VALUE,
    }
)


DEFAULT_TEST_ID_ATTRIBUTES = ("data-testid", "data-test", "data-cy", "data-qa", "dusk", "wire:model", "name")


class SelectorKind(StrEnum):
    TEST_ID = "test_id"
    ID = "id"
    LABEL = "label"
    ROLE = "role"
    PLACEHOLDER = "placeholder"
    CSS = "css"


class DeviceKind(StrEnum):
    DESKTOP = "desktop"
    MOBILE = "mobile"


@dataclass(frozen=True, slots=True)
class Selector:
    kind: SelectorKind
    value: str
    attribute: str | None = None
    role: str | None = None
    suspicious: bool = False


@dataclass(frozen=True, slots=True)
class Target:
    primary: Selector
    fallbacks: tuple[Selector, ...] = ()

    @property
    def candidates(self) -> tuple[Selector, ...]:
        return (self.primary, *self.fallbacks)


@dataclass(frozen=True, slots=True)
class Step:
    id: str
    action: Action
    target: Target | None = None
    url: str | None = None
    value: str | None = None
    checked: bool | None = None
    timeout_ms: int | None = None
    raw: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Device:
    kind: DeviceKind = DeviceKind.DESKTOP
    name: str | None = None
    width: int = 1440
    height: int = 900
    fullscreen: bool = False

    @property
    def is_mobile(self) -> bool:
        return self.kind is DeviceKind.MOBILE

    @property
    def label(self) -> str:
        if self.is_mobile:
            return self.name or "mobile"
        if self.fullscreen:
            return f"desktop full screen ({self.width}x{self.height})"
        return f"desktop {self.width}x{self.height}"


@dataclass(frozen=True, slots=True)
class Test:
    __test__ = False

    id: str
    name: str
    steps: tuple[Step, ...] = ()
    description: str = ""
    tags: tuple[str, ...] = ()
    destructive: bool = False
    device: Device = field(default_factory=Device)


@dataclass(frozen=True, slots=True)
class Project:
    id: int | None
    slug: str
    name: str
    test_id_attributes: tuple[str, ...] = DEFAULT_TEST_ID_ATTRIBUTES
    created_at: str = ""
    setup_test_uuid: str | None = None
    login_test_uuid: str | None = None


@dataclass(frozen=True, slots=True)
class EnvironmentConfig:
    locale: str | None = None
    timezone: str | None = None
    ignore_https_errors: bool = False
    http_credentials: str | None = None
    cookies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Environment:
    id: int | None
    project_id: int
    name: str
    base_url: str
    allow_destructive: bool = False
    config: EnvironmentConfig = field(default_factory=EnvironmentConfig)


@dataclass(frozen=True, slots=True)
class StoredTest:
    id: int
    project_id: int
    test: Test
    updated_at: str


class RunStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    FLAKY = "flaky"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class RunRecord:
    id: int | None
    test_id: int
    environment_id: int
    status: RunStatus
    started_at: str
    duration_ms: int
    playwright_version: str
    browser_version: str
    failed_step_id: str | None = None
    message: str | None = None
    artifact_path: str | None = None
