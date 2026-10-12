"""Build, smoke-test and archive the desktop app for the current OS; optionally upload it to GitLab.

    uv run --group package python packaging/build.py            # build + smoke test + archive
    uv run --group package python packaging/build.py --upload   # also upload to the package registry

On macOS the app is signed when a Developer ID certificate is in the keychain, and notarized for
--upload or --notarize.

See packaging/RELEASING.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
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
APP_NAME = "ComfyCapture"
BUNDLE_ID = "nl.comfycoders.ComfyCapture"
PACKAGE_NAME = "comfycapture"
GITLAB_URL = "https://gitlab.comfycoders.nl"
GITLAB_PROJECT = "tranquil-tools/comfy-capture"
SMOKE_SECONDS = 6
MARK = ROOT / "src" / "comfycapture" / "ui" / "assets" / "mark.svg"
DEBIAN_INSTALL_DIR = Path("opt") / PACKAGE_NAME
DEBIAN_ARCHITECTURES = {"x86_64": "amd64", "arm64": "arm64"}
DEBIAN_DEPENDS = "libgl1, libegl1, libxkbcommon0, libfontconfig1, libdbus-1-3, libxcb1"
DEBIAN_MAINTAINER = "ComfyCoders <info@comfycoders.nl>"
ENTITLEMENTS = ROOT / "packaging" / "entitlements.plist"
NOTARY_PROFILE = "comfycapture"
NOTARY_TIMEOUT = "30m"
MACH_O_MAGICS = {
    bytes.fromhex(magic) for magic in ("feedface", "feedfacf", "cefaedfe", "cffaedfe", "cafebabe", "bebafeca")
}


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
    def debian_package_name(self) -> str:
        return f"{APP_NAME}-{version()}-{self.system}-{self.arch}.deb"

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
        "comfycapture",
        "--collect-submodules",
        "comfycapture",
        "--copy-metadata",
        "comfycapture",
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
        [str(target.executable), "--core", "comfycapture.core.health"],
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


def signing_identity() -> str | None:
    configured = os.environ.get("MACOS_SIGNING_IDENTITY")
    if configured:
        return configured
    result = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"], capture_output=True, text=True, check=False
    )
    identities = list(dict.fromkeys(re.findall(r'"(Developer ID Application: [^"]+)"', result.stdout)))
    if len(identities) > 1:
        raise BuildError("Several Developer ID certificates found; pick one with MACOS_SIGNING_IDENTITY.")
    return identities[0] if identities else None


def is_mach_o(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    with path.open("rb") as file:
        return file.read(4) in MACH_O_MAGICS


def codesign(path: Path, identity: str) -> None:
    result = subprocess.run(
        [
            "codesign",
            "--force",
            "--timestamp",
            "--options",
            "runtime",
            "--entitlements",
            str(ENTITLEMENTS),
            "--sign",
            identity,
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise BuildError(f"Signing {path} failed: {result.stderr.strip()}")


def deepest_first(paths: list[Path]) -> list[Path]:
    return sorted(paths, key=lambda path: len(path.parts), reverse=True)


def sign(target: Target, identity: str) -> None:
    contents = target.bundle / "Contents"
    binaries = deepest_first([path for path in contents.rglob("*") if is_mach_o(path)])
    frameworks = deepest_first(
        [path for path in contents.rglob("*.framework") if path.is_dir() and not path.is_symlink()]
    )
    for path in [*binaries, *frameworks, target.bundle]:
        codesign(path, identity)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(target.bundle)], check=True)
    print(f"    signed {len(binaries)} binaries and {len(frameworks)} frameworks as {identity}")


def notarize(target: Target) -> None:
    profile = os.environ.get("MACOS_NOTARY_PROFILE", NOTARY_PROFILE)
    submission = BUILD / f"{APP_NAME}-notarization.zip"
    submission.unlink(missing_ok=True)
    subprocess.run(["ditto", "-c", "-k", "--keepParent", str(target.bundle), str(submission)], check=True)
    result = subprocess.run(
        [
            "xcrun",
            "notarytool",
            "submit",
            str(submission),
            "--keychain-profile",
            profile,
            "--wait",
            "--timeout",
            NOTARY_TIMEOUT,
            "--output-format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError:
        response = {}
    status = response.get("status")
    if status != "Accepted":
        submission_id = response.get("id")
        if submission_id:
            subprocess.run(
                ["xcrun", "notarytool", "log", submission_id, "--keychain-profile", profile], check=False
            )
        raise BuildError(f"Notarization failed ({status or result.stderr.strip()}); see the log above.")
    subprocess.run(["xcrun", "stapler", "staple", str(target.bundle)], check=True)
    subprocess.run(["spctl", "--assess", "--type", "execute", "--verbose", str(target.bundle)], check=True)


def write_checksum(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum = path.with_name(path.name + ".sha256")
    checksum.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    return checksum


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
    write_checksum(destination)
    return destination


def desktop_entry() -> str:
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={APP_NAME}",
        "Comment=Record browser tests once, replay them on demand and on a schedule",
        f"Exec=/{DEBIAN_INSTALL_DIR / APP_NAME}",
        f"Icon={BUNDLE_ID}",
        "Terminal=false",
        "Categories=Development;",
        f"StartupWMClass={APP_NAME}",
    ]
    return "\n".join(lines) + "\n"


def debian_control(target: Target, installed_kilobytes: int) -> str:
    lines = [
        f"Package: {PACKAGE_NAME}",
        f"Version: {version()}",
        f"Architecture: {DEBIAN_ARCHITECTURES[target.arch]}",
        f"Maintainer: {DEBIAN_MAINTAINER}",
        f"Depends: {DEBIAN_DEPENDS}",
        f"Installed-Size: {installed_kilobytes}",
        "Section: devel",
        "Priority: optional",
        f"Description: {APP_NAME} desktop app",
        " Record browser tests once, replay them on demand and on a schedule.",
    ]
    return "\n".join(lines) + "\n"


def debian_package(target: Target) -> Path:
    staging = BUILD / "deb"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(target.bundle, staging / DEBIAN_INSTALL_DIR, symlinks=True)

    applications = staging / "usr" / "share" / "applications"
    applications.mkdir(parents=True)
    (applications / f"{BUNDLE_ID}.desktop").write_text(desktop_entry(), encoding="utf-8")

    icons = staging / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps"
    icons.mkdir(parents=True)
    shutil.copyfile(MARK, icons / f"{BUNDLE_ID}.svg")

    installed_bytes = sum(path.stat().st_size for path in staging.rglob("*") if path.is_file())
    control = staging / "DEBIAN"
    control.mkdir()
    (control / "control").write_text(debian_control(target, installed_bytes // 1024 + 1), encoding="utf-8")

    for path in [staging, *staging.rglob("*")]:
        if path.is_symlink():
            continue
        executable = path.is_dir() or path.stat().st_mode & 0o100
        path.chmod(0o755 if executable else 0o644)

    destination = RELEASES / target.debian_package_name
    destination.unlink(missing_ok=True)
    subprocess.run(
        ["dpkg-deb", "--build", "--root-owner-group", str(staging), str(destination)],
        check=True,
    )
    write_checksum(destination)
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
    parser = argparse.ArgumentParser(description="Build the ComfyCapture desktop app for this OS.")
    parser.add_argument(
        "--upload", action="store_true", help="upload the archive to the GitLab package registry"
    )
    parser.add_argument("--skip-build", action="store_true", help="reuse dist/ from a previous build")
    parser.add_argument("--notarize", action="store_true", help="notarize the macOS app without uploading")
    arguments = parser.parse_args()

    try:
        target = current_target()
        step(f"{APP_NAME} {version()} for {target.system}-{target.arch}")
        for problem in check_repository(require_release=arguments.upload):
            print(f"    warning: {problem} (fine for a test build, not for a release)")
        identity = signing_identity() if target.system == "macos" else None
        notarizing = target.system == "macos" and (arguments.upload or arguments.notarize)
        if notarizing and identity is None:
            raise BuildError("Cannot notarize: no Developer ID Application certificate in the keychain.")
        if not arguments.skip_build:
            step("PyInstaller")
            run_pyinstaller(target)
        if identity is not None:
            step("Sign")
            sign(target, identity)
        step("Smoke test")
        smoke_test(target)
        if notarizing:
            step("Notarize")
            notarize(target)
        step("Archive")
        paths = [archive(target)]
        if target.system == "linux":
            step("Debian package")
            paths.append(debian_package(target))
        for path in paths:
            print(f"    {path}")
        if arguments.upload:
            step("Upload")
            for path in paths:
                for file in (path, path.with_name(path.name + ".sha256")):
                    print(f"    {upload(file)}")
    except (BuildError, subprocess.CalledProcessError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
