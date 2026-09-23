"""The only module that reads credentials.

Desktop: the OS keyring, service `BrowsertestSuite/<project slug>`. Server: environment variables
`BROWSERTESTS_SECRET_<NAME>` (upper-cased, non-alphanumerics as `_`), which win over the keyring.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

SERVICE_PREFIX = "BrowsertestSuite"


def environment_key(name: str) -> str:
    return "BROWSERTESTS_SECRET_" + re.sub(r"[^A-Za-z0-9]", "_", name).upper()


class SecretStore:
    def __init__(
        self, project_slug: str, environ: Mapping[str, str] | None = None, use_keyring: bool = True
    ) -> None:
        self._service = f"{SERVICE_PREFIX}/{project_slug}"
        self._environ = os.environ if environ is None else environ
        self._use_keyring = use_keyring

    def get(self, name: str) -> str | None:
        value = self._environ.get(environment_key(name))
        if value is not None:
            return value
        if not self._use_keyring:
            return None
        try:
            import keyring

            return keyring.get_password(self._service, name)
        except Exception:
            return None

    def set(self, name: str, value: str) -> None:
        import keyring

        keyring.set_password(self._service, name, value)

    def delete(self, name: str) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        try:
            keyring.delete_password(self._service, name)
        except PasswordDeleteError:
            return

    def has(self, name: str) -> bool:
        return self.get(name) is not None
