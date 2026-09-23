"""Build, smoke-test and archive the desktop app for the current OS; optionally upload it to GitLab.

    uv run --group package python packaging/build.py            # build + smoke test + archive
    uv run --group package python packaging/build.py --upload   # also upload to the package registry

See packaging/RELEASING.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
RELEASES = ROOT / "releases"
APP_NAME = "BrowsertestSuite"
BUNDLE_ID = "nl.comfycoders.BrowserTests"
PACKAGE_NAME = "browsertests"
GITLAB_URL = "https://gitlab.comfycoders.nl"
GITLAB_PROJECT = "tranquil-tools/browsertest-suite"
SMOKE_SECONDS = 6


class BuildError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Target:
    system: str
    arch: str

    @property
    def archive_name(self) -> str:
        extension = "tar.gz" if self.system == "linux" else "zip"
        return f"{APP_NAME}-{version()}-{self.system}-{self.arch}.{extension}"

    @property
    def bundle(self) -> Path:
        if self.system == "macos":
            return DIST / f"{APP_NAME}.app"
        return DIST / APP_NAME

    @property
    def executable(self) -> Path:
        if self.system == "macos":
            return self.bundle / "Contents" / "MacOS" / APP_NAME
        if self.system == "windows":
            return self.bundle / f"{APP_NAME}.exe"
        return self.bundle / APP_NAME


def current_target() -> Target:
    systems = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}
    system = systems.get(platform.system())
    if system is None:
        raise BuildError(f"Unsupported OS: {platform.system()}")
    machine = platform.machine().lower()
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(machine, machine)
    return Target(system, arch)


def version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def git(*arguments: str) -> str:
    result = subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, text=True, check=False)
    return result.stdout.strip()


def check_repository(require_release: bool) -> list[str]:
    problems: list[str] = []
    if git("status", "--porcelain"):
        problems.append("the working tree has uncommitted changes")
    tag = f"v{version()}"
    if tag not in git("tag", "--points-at", "HEAD").splitlines():
        problems.append(f"HEAD is not tagged {tag}")
    if require_release and problems:
        raise BuildError("Refusing to upload: " + "; ".join(problems) + ".")
    return problems


def step(message: str) -> None:
    print(f"==> {message}", flush=True)


def run_pyinstaller(target: Target) -> None:
    shutil.rmtree(DIST, ignore_errors=True)
    shutil.rmtree(BUILD, ignore_errors=True)
    arguments = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        APP_NAME,
        "--collect-all",
        "playwright",
        "--collect-data",
        "browsertests",
        "--collect-submodules",
        "browsertests",
        "--copy-metadata",
        "browsertests",
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD),
        "--specpath",
        str(BUILD),
    ]
    if target.system == "macos":
        arguments += ["--osx-bundle-identifier", BUNDLE_ID]
    arguments.append(str(ROOT / "packaging" / "entry.py"))
    subprocess.run(arguments, cwd=ROOT, check=True)
    if not target.executable.is_file():
        raise BuildError(f"PyInstaller did not produce {target.executable}")


def smoke_test(target: Target) -> None:
    result = subprocess.run(
        [str(target.executable), "--core", "browsertests.core.health"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if result.returncode != 0 or not lines:
        raise BuildError(f"Core health check failed ({result.returncode}): {result.stderr.strip()}")
    report = json.loads(lines[-1])
    if report.get("version") != version():
        raise BuildError(f"Frozen app reports version {report.get('version')}, expected {version()}")
    print(f"    core: {report}")

    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    process = subprocess.Popen([str(target.executable)], env=environment)
    time.sleep(SMOKE_SECONDS)
    exit_code = process.poll()
    if exit_code is not None:
        raise BuildError(f"The desktop window exited during start-up with code {exit_code}")
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
    print(f"    desktop: still running after {SMOKE_SECONDS}s")


def archive(target: Target) -> Path:
    RELEASES.mkdir(exist_ok=True)
    destination = RELEASES / target.archive_name
    destination.unlink(missing_ok=True)
    if target.system == "linux":
        with tarfile.open(destination, "w:gz") as tar:
            tar.add(target.bundle, arcname=target.bundle.name)
    if target.system == "macos":
        subprocess.run(
            ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(target.bundle), str(destination)],
            check=True,
        )
    if target.system == "windows":
        shutil.make_archive(str(destination.with_suffix("")), "zip", DIST, target.bundle.name)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    checksum = destination.with_name(destination.name + ".sha256")
    checksum.write_text(f"{digest}  {destination.name}\n", encoding="utf-8")
    return destination


def upload(path: Path) -> str:
    token = os.environ.get("GITLAB_TOKEN")
    if not token:
        raise BuildError("Set GITLAB_TOKEN to a personal access token with the api scope.")
    project = urllib.parse.quote(GITLAB_PROJECT, safe="")
    url = f"{GITLAB_URL}/api/v4/projects/{project}/packages/generic/{PACKAGE_NAME}/{version()}/{path.name}"
    request = urllib.request.Request(
        url, data=path.read_bytes(), method="PUT", headers={"PRIVATE-TOKEN": token}
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        if response.status not in (200, 201):
            raise BuildError(f"Upload of {path.name} failed with HTTP {response.status}")
    return url


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the BrowsertestSuite desktop app for this OS.")
    parser.add_argument(
        "--upload", action="store_true", help="upload the archive to the GitLab package registry"
    )
    parser.add_argument("--skip-build", action="store_true", help="reuse dist/ from a previous build")
    arguments = parser.parse_args()

    try:
        target = current_target()
        step(f"{APP_NAME} {version()} for {target.system}-{target.arch}")
        for problem in check_repository(require_release=arguments.upload):
            print(f"    warning: {problem} (fine for a test build, not for a release)")
        if not arguments.skip_build:
            step("PyInstaller")
            run_pyinstaller(target)
        step("Smoke test")
        smoke_test(target)
        step("Archive")
        path = archive(target)
        print(f"    {path}")
        if arguments.upload:
            step("Upload")
            for file in (path, path.with_name(path.name + ".sha256")):
                print(f"    {upload(file)}")
    except (BuildError, subprocess.CalledProcessError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
