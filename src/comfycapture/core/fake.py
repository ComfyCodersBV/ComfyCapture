from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from faker import Faker

PREFIX = "fake:"
DEFAULT_LOCALE = "nl_NL"


@dataclass(frozen=True, slots=True)
class FakeKind:
    python: str
    php: str


KINDS: dict[str, FakeKind] = {
    "name": FakeKind("name", "name()"),
    "first_name": FakeKind("first_name", "firstName()"),
    "last_name": FakeKind("last_name", "lastName()"),
    "email": FakeKind("safe_email", "safeEmail()"),
    "phone": FakeKind("phone_number", "phoneNumber()"),
    "company": FakeKind("company", "company()"),
    "street": FakeKind("street_name", "streetName()"),
    "house_number": FakeKind("building_number", "buildingNumber()"),
    "postcode": FakeKind("postcode", "postcode()"),
    "city": FakeKind("city", "city()"),
    "word": FakeKind("word", "word()"),
    "sentence": FakeKind("sentence", "sentence()"),
    "number": FakeKind("random_int", "numberBetween(1000, 9999)"),
    "uuid": FakeKind("uuid4", "uuid()"),
}


class UnknownFakeKindError(ValueError):
    pass


def is_reference(name: str) -> bool:
    return name.startswith(PREFIX)


def kind_of(name: str) -> FakeKind:
    kind_name = name[len(PREFIX) :].split(":", 1)[0]
    if kind_name not in KINDS:
        raise UnknownFakeKindError(
            f"Fake value {kind_name!r} does not exist; choose one of {', '.join(KINDS)}."
        )
    return KINDS[kind_name]


def reference(kind_name: str) -> str:
    return "{{" + PREFIX + kind_name + "}}"


def faker_locale(locale: str | None) -> str:
    if not locale:
        return DEFAULT_LOCALE
    return locale.replace("-", "_")


class FakeValues:
    def __init__(self, locale: str | None = None) -> None:
        self._locale = faker_locale(locale)
        self._faker: Faker | None = None
        self._values: dict[str, str] = {}

    def value(self, name: str) -> str:
        kind = kind_of(name)
        if name not in self._values:
            self._values[name] = str(self._generate(kind))
        return self._values[name]

    def _generate(self, kind: FakeKind) -> object:
        generator = self._generator()
        if kind.python == "random_int":
            return generator.random_int(1000, 9999)
        return getattr(generator, kind.python)()

    def _generator(self) -> Faker:
        if self._faker is not None:
            return self._faker
        from faker import Faker

        try:
            self._faker = Faker(self._locale)
        except AttributeError:
            self._faker = Faker(DEFAULT_LOCALE)
        return self._faker
