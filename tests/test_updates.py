from __future__ import annotations

import functools
import hashlib
import http.server
import tarfile
import threading
from pathlib import Path

import pytest

from comfycapture.core import updates
from comfycapture.core.updates import Installation, InstallKind, Release


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def served(tmp_path: Path):
    directory = tmp_path / "served"
    directory.mkdir()
    handler = functools.partial(QuietHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield directory, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def linux_installation(root: Path) -> Installation:
    location = root / "apps" / "ComfyCapture"
    location.mkdir(parents=True)
    (location / "ComfyCapture").write_text("old", encoding="utf-8")
    return Installation(InstallKind.LINUX_ARCHIVE, location, location / "ComfyCapture", "x86_64")


def publish(directory: Path, base_url: str, version: str, content: str, digest: str | None = None) -> Release:
    build = directory / "build" / "ComfyCapture"
    build.mkdir(parents=True)
    (build / "ComfyCapture").write_text(content, encoding="utf-8")
    name = f"ComfyCapture-{version}-linux-x86_64.tar.gz"
    with tarfile.open(directory / name, "w:gz") as tar:
        tar.add(build, arcname="ComfyCapture")
    checksum = digest or hashlib.sha256((directory / name).read_bytes()).hexdigest()
    (directory / f"{name}.sha256").write_text(f"{checksum}  {name}\n", encoding="utf-8")
    return Release(
        version,
        "https://example.test/releases",
        {name: f"{base_url}/{name}", f"{name}.sha256": f"{base_url}/{name}.sha256"},
    )


def test_only_a_higher_version_is_an_update() -> None:
    assert updates.is_newer("v0.3.0", "0.2.1")
    assert updates.is_newer("0.10.0", "0.9.9")
    assert not updates.is_newer("v0.2.1", "0.2.1")
    assert not updates.is_newer("nightly", "0.2.1")


def test_drafts_and_prereleases_are_ignored() -> None:
    document = {"tag_name": "v1.0.0", "html_url": "https://x", "assets": [], "prerelease": True}

    assert updates.release_from_document(document) is None
    assert updates.release_from_document({**document, "prerelease": False}).version == "1.0.0"


@pytest.mark.parametrize(
    ("executable", "system", "kind", "location"),
    [
        ("/opt/comfycapture/ComfyCapture", "Linux", InstallKind.DEBIAN, "/opt/comfycapture"),
        ("/home/u/ComfyCapture/ComfyCapture", "Linux", InstallKind.LINUX_ARCHIVE, "/home/u/ComfyCapture"),
        (
            "/Applications/ComfyCapture.app/Contents/MacOS/ComfyCapture",
            "Darwin",
            InstallKind.MACOS,
            "/Applications/ComfyCapture.app",
        ),
    ],
)
def test_the_installation_kind_follows_the_executable(executable, system, kind, location) -> None:
    installation = updates.detect_installation(Path(executable), system, frozen=True)

    assert installation.kind is kind
    assert installation.location == Path(location)


def test_a_source_checkout_does_not_update_itself() -> None:
    installation = updates.detect_installation(Path("/usr/bin/python3"), "Linux", frozen=False)

    assert not installation.can_update_in_place
    with pytest.raises(updates.UpdateError):
        installation.asset_name("1.0.0")


def test_an_update_replaces_the_app_and_keeps_the_previous_one_until_cleanup(served, tmp_path) -> None:
    directory, base_url = served
    installation = linux_installation(tmp_path)
    release = publish(directory, base_url, "9.0.0", "new")
    downloads = tmp_path / "downloads"
    downloads.mkdir()

    archive = updates.fetch_verified(release, installation, downloads)
    command = updates.install(archive, installation)

    assert command == [str(installation.executable)]
    assert installation.executable.read_text(encoding="utf-8") == "new"
    assert (updates.previous_location(installation) / "ComfyCapture").read_text(encoding="utf-8") == "old"
    assert sorted(path.name for path in installation.location.parent.iterdir()) == [
        "ComfyCapture",
        "ComfyCapture.previous",
    ]

    updates.remove_previous(installation)

    assert not updates.previous_location(installation).exists()


def test_a_checksum_mismatch_changes_nothing(served, tmp_path) -> None:
    directory, base_url = served
    installation = linux_installation(tmp_path)
    release = publish(directory, base_url, "9.0.0", "new", digest="0" * 64)
    downloads = tmp_path / "downloads"
    downloads.mkdir()

    with pytest.raises(updates.UpdateError, match="checksum"):
        updates.fetch_verified(release, installation, downloads)

    assert installation.executable.read_text(encoding="utf-8") == "old"


def test_the_windows_script_quotes_paths() -> None:
    location = Path("C:/Users/o'brien/ComfyCapture")
    installation = Installation(InstallKind.WINDOWS, location, location / "ComfyCapture.exe", "x86_64")

    script = updates.windows_script(42, Path("C:/Users/o'brien/.stage/ComfyCapture"), installation)

    assert "Wait-Process -Id 42" in script
    assert "o''brien" in script
