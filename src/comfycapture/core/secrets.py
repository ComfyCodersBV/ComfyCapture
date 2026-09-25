"""The only module that reads credentials.

Desktop: the OS keyring, service `ComfyCapture/<project slug>`. Server: environment variables
`COMFYCAPTURE_SECRET_<NAME>` (upper-cased, non-alphanumerics as `_`), or a file named by
`COMFYCAPTURE_SECRETS_FILE` with `COMFYCAPTURE_SECRET_<NAME>=value` lines. Environment beats file beats
keyring.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

SERVICE_PREFIX = "ComfyCapture"
LEGACY_SERVICE_PREFIX = "BrowsertestSuite"


SECRETS_FILE_VARIABLE = "COMFYCAPTURE_SECRETS_FILE"


def environment_key(name: str) -> str:
    return "COMFYCAPTURE_SECRET_" + re.sub(r"[^A-Za-z0-9]", "_", name).upper()


def read_secrets_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class SecretStore:
    def __init__(
        self, project_slug: str, environ: Mapping[str, str] | None = None, use_keyring: bool = True
    ) -> None:
        self._service = f"{SERVICE_PREFIX}/{project_slug}"
        self._legacy_service = f"{LEGACY_SERVICE_PREFIX}/{project_slug}"
        self._environ = os.environ if environ is None else environ
        self._use_keyring = use_keyring

    def get(self, name: str) -> str | None:
        key = environment_key(name)
        value = self._environ.get(key)
        if value is not None:
            return value
        secrets_file = self._environ.get(SECRETS_FILE_VARIABLE)
        if secrets_file:
            value = read_secrets_file(secrets_file).get(key)
            if value is not None:
                return value
        if not self._use_keyring:
            return None
        try:
            import keyring

            value = keyring.get_password(self._service, name)
            if value is not None:
                return value
            return self._migrate_legacy(name)
        except Exception:
            return None

    def _migrate_legacy(self, name: str) -> str | None:
        import keyring

        value = keyring.get_password(self._legacy_service, name)
        if value is None:
            return None
        try:
            keyring.set_password(self._service, name, value)
            keyring.delete_password(self._legacy_service, name)
        except Exception:
            return value
        return value

    def set(self, name: str, value: str) -> None:
        import keyring

        keyring.set_password(self._service, name, value)

    def delete(self, name: str) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        for service in (self._service, self._legacy_service):
            try:
                keyring.delete_password(service, name)
            except PasswordDeleteError:
                continue

    def has(self, name: str) -> bool:
        return self.get(name) is not None
