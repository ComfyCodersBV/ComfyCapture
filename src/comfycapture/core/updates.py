from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from comfycapture import __version__

APP_NAME = "ComfyCapture"
GITHUB_REPOSITORY = "ComfyCodersBV/ComfyCapture"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPOSITORY}/releases/latest"
DEBIAN_INSTALL_DIR = Path("/opt/comfycapture")
CHECK_TIMEOUT_SECONDS = 5
DOWNLOAD_TIMEOUT_SECONDS = 60
CHUNK_BYTES = 256 * 1024
PREVIOUS_SUFFIX = ".previous"

Progress = Callable[[int, int], None]


class UpdateError(Exception):
    pass


class InstallKind(StrEnum):
    DEBIAN = "deb"
    LINUX_ARCHIVE = "linux"
    MACOS = "macos"
    WINDOWS = "windows"
    SOURCE = "source"


@dataclass(frozen=True, slots=True)
class Installation:
    kind: InstallKind
    location: Path
    executable: Path
    arch: str

    @property
    def can_update_in_place(self) -> bool:
        return self.kind is not InstallKind.SOURCE

    def asset_name(self, version: str) -> str:
        suffix = {
            InstallKind.DEBIAN: f"linux-{self.arch}.deb",
            InstallKind.LINUX_ARCHIVE: f"linux-{self.arch}.tar.gz",
            InstallKind.MACOS: f"macos-{self.arch}.zip",
            InstallKind.WINDOWS: f"windows-{self.arch}.zip",
        }.get(self.kind)
        if suffix is None:
            raise UpdateError("This installation cannot update itself.")
        return f"{APP_NAME}-{version}-{suffix}"


@dataclass(frozen=True, slots=True)
class Release:
    version: str
    page_url: str
    assets: dict[str, str]

    def asset_url(self, name: str) -> str:
        if name not in self.assets:
            raise UpdateError(f"Release {self.version} has no {name}.")
        return self.assets[name]


def parse_version(text: str) -> tuple[int, ...]:
    cleaned = text.strip().removeprefix("v")
    try:
        return tuple(int(part) for part in cleaned.split("."))
    except ValueError:
        return ()


def is_newer(candidate: str, current: str = __version__) -> bool:
    parsed = parse_version(candidate)
    return bool(parsed) and parsed > parse_version(current)


def release_from_document(document: dict[str, object]) -> Release | None:
    tag = str(document.get("tag_name") or "")
    if not parse_version(tag) or document.get("draft") or document.get("prerelease"):
        return None
    assets = {
        str(asset.get("name")): str(asset.get("browser_download_url"))
        for asset in document.get("assets") or []
        if isinstance(asset, dict)
    }
    return Release(tag.removeprefix("v"), str(document.get("html_url") or RELEASES_PAGE_URL), assets)


def request(url: str, accept: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"Accept": accept, "User-Agent": f"{APP_NAME}/{__version__}"})


def fetch_latest(url: str = LATEST_RELEASE_URL) -> Release | None:
    try:
        with urllib.request.urlopen(
            request(url, "application/vnd.github+json"), timeout=CHECK_TIMEOUT_SECONDS
        ) as response:
            document = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    return release_from_document(document)


def available_update() -> Release | None:
    release = fetch_latest()
    if release is None or not is_newer(release.version):
        return None
    return release


def current_arch() -> str:
    machine = platform.machine().lower()
    return {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(machine, machine)


def detect_installation(
    executable: Path | None = None, system: str | None = None, frozen: bool | None = None
) -> Installation:
    executable = (executable or Path(sys.executable)).resolve()
    system = system or platform.system()
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    arch = current_arch()
    if not frozen:
        return Installation(InstallKind.SOURCE, executable.parent, executable, arch)
    if system == "Darwin":
        return Installation(InstallKind.MACOS, executable.parents[2], executable, arch)
    if system == "Windows":
        return Installation(InstallKind.WINDOWS, executable.parent, executable, arch)
    if executable.parent == DEBIAN_INSTALL_DIR:
        return Installation(InstallKind.DEBIAN, executable.parent, executable, arch)
    return Installation(InstallKind.LINUX_ARCHIVE, executable.parent, executable, arch)


def download(url: str, destination: Path, progress: Progress | None = None) -> Path:
    with (
        urllib.request.urlopen(
            request(url, "application/octet-stream"), timeout=DOWNLOAD_TIMEOUT_SECONDS
        ) as response,
        destination.open("wb") as file,
    ):
        total = int(response.headers.get("Content-Length") or 0)
        received = 0
        while chunk := response.read(CHUNK_BYTES):
            file.write(chunk)
            received += len(chunk)
            if progress is not None:
                progress(received, total)
    return destination


def expected_digest(checksum_text: str) -> str:
    parts = checksum_text.split()
    if not parts or len(parts[0]) != 64:
        raise UpdateError("The checksum file is not a sha256 checksum.")
    return parts[0].lower()


def verify(path: Path, digest: str) -> None:
    hasher = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(CHUNK_BYTES):
            hasher.update(chunk)
    if hasher.hexdigest() != digest:
        raise UpdateError("The download does not match its checksum; nothing was changed.")


def fetch_verified(
    release: Release, installation: Installation, directory: Path, progress: Progress | None = None
) -> Path:
    name = installation.asset_name(release.version)
    checksum = download(release.asset_url(name + ".sha256"), directory / (name + ".sha256"))
    archive = download(release.asset_url(name), directory / name, progress)
    verify(archive, expected_digest(checksum.read_text(encoding="utf-8")))
    return archive


def ensure_writable(installation: Installation) -> None:
    if installation.kind is InstallKind.DEBIAN:
        return
    parent = installation.location.parent
    if not os.access(parent, os.W_OK) or not os.access(installation.location, os.W_OK):
        raise UpdateError(
            f"{installation.location} is not writable for this user; download the new version by hand."
        )


def extract(archive: Path, installation: Installation) -> Path:
    staging = Path(tempfile.mkdtemp(prefix=".comfycapture-update-", dir=installation.location.parent))
    if installation.kind is InstallKind.MACOS:
        subprocess.run(["ditto", "-x", "-k", str(archive), str(staging)], check=True)
    elif installation.kind is InstallKind.LINUX_ARCHIVE:
        with tarfile.open(archive) as tar:
            tar.extractall(staging, filter="data")
    else:
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(staging)
    extracted = staging / installation.location.name
    if not extracted.exists():
        candidates = [path for path in staging.iterdir() if path.name.startswith(APP_NAME)]
        if len(candidates) != 1:
            raise UpdateError("The download does not contain the app.")
        extracted = candidates[0]
    return extracted


def previous_location(installation: Installation) -> Path:
    return installation.location.with_name(installation.location.name + PREVIOUS_SUFFIX)


def swap(installation: Installation, replacement: Path) -> None:
    previous = previous_location(installation)
    shutil.rmtree(previous, ignore_errors=True)
    installation.location.rename(previous)
    try:
        replacement.rename(installation.location)
    except OSError:
        previous.rename(installation.location)
        raise
    shutil.rmtree(replacement.parent, ignore_errors=True)


def powershell_string(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def windows_script(process_id: int, replacement: Path, installation: Installation) -> str:
    target = powershell_string(installation.location)
    previous = powershell_string(previous_location(installation))
    staging = powershell_string(replacement.parent)
    return "\n".join(
        [
            f"Wait-Process -Id {process_id} -ErrorAction SilentlyContinue",
            "Start-Sleep -Seconds 1",
            f"Remove-Item -LiteralPath {previous} -Recurse -Force -ErrorAction SilentlyContinue",
            f"Move-Item -LiteralPath {target} -Destination {previous}",
            f"Move-Item -LiteralPath {powershell_string(replacement)} -Destination {target}",
            f"Start-Process -FilePath {powershell_string(installation.executable)}",
            f"Remove-Item -LiteralPath {staging} -Recurse -Force -ErrorAction SilentlyContinue",
        ]
    )


def install(archive: Path, installation: Installation) -> list[str]:
    if installation.kind is InstallKind.DEBIAN:
        result = subprocess.run(
            ["pkexec", "apt-get", "install", "-y", "--allow-downgrades", str(archive)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise UpdateError(result.stderr.strip() or "Installing the package was cancelled.")
        return [str(installation.executable)]
    ensure_writable(installation)
    replacement = extract(archive, installation)
    if installation.kind is InstallKind.WINDOWS:
        script = replacement.parent / "update.ps1"
        script.write_text(windows_script(os.getpid(), replacement, installation), encoding="utf-8")
        return [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(script),
        ]
    swap(installation, replacement)
    if installation.kind is InstallKind.MACOS:
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(installation.location)], check=False)
        return ["open", "-n", str(installation.location)]
    return [str(installation.executable)]


def remove_previous(installation: Installation | None = None) -> None:
    installation = installation or detect_installation()
    if installation.can_update_in_place:
        shutil.rmtree(previous_location(installation), ignore_errors=True)
