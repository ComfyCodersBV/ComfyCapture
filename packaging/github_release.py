from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

GITHUB_REPOSITORY = "ComfyCodersBV/ComfyCapture"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPOSITORY}"
GITHUB_UPLOADS = f"https://uploads.github.com/repos/{GITHUB_REPOSITORY}"
TIMEOUT_SECONDS = 600


class ReleaseError(Exception):
    pass


def environment(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ReleaseError(f"{name} is not set.")
    return value


def github(method: str, url: str, token: str, body: bytes | None = None, content_type: str = "") -> object:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "comfycapture-release",
    }
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        payload = response.read()
    return json.loads(payload) if payload else None


def find_or_create_release(token: str, tag: str, commit: str, name: str, notes: str) -> dict[str, object]:
    try:
        release = github("GET", f"{GITHUB_API}/releases/tags/{tag}", token)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        document = {"tag_name": tag, "target_commitish": commit, "name": name, "body": notes}
        release = github(
            "POST", f"{GITHUB_API}/releases", token, json.dumps(document).encode(), "application/json"
        )
    if not isinstance(release, dict):
        raise ReleaseError("GitHub returned an unexpected release document.")
    return release


def registry_file(url: str, job_token: str) -> bytes:
    request = urllib.request.Request(url, headers={"JOB-TOKEN": job_token})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def main() -> int:
    try:
        token = environment("GITHUB_TOKEN")
        tag = environment("CI_COMMIT_TAG")
        commit = environment("CI_COMMIT_SHA")
        job_token = environment("CI_JOB_TOKEN")
        app_name = environment("APP_NAME")
        version = tag.removeprefix("v")
        registry = (
            f"{environment('CI_API_V4_URL')}/projects/{environment('CI_PROJECT_ID')}"
            f"/packages/generic/{environment('PACKAGE_NAME')}/{version}"
        )
        release = find_or_create_release(
            token,
            tag,
            commit,
            f"{app_name} {version}",
            f"{app_name} {version}. Download the archive for your OS below; see packaging/RELEASING.md for "
            "installing. Installed apps offer this update by themselves.",
        )
        existing = {
            str(asset.get("name")) for asset in release.get("assets") or [] if isinstance(asset, dict)
        }
        for target in environment("RELEASE_TARGETS").split():
            archive = f"{app_name}-{version}-{target}"
            for name in (archive, f"{archive}.sha256"):
                if name in existing:
                    print(f"    {name}: already on GitHub")
                    continue
                content = registry_file(f"{registry}/{name}", job_token)
                query = urllib.parse.urlencode({"name": name})
                github(
                    "POST",
                    f"{GITHUB_UPLOADS}/releases/{release['id']}/assets?{query}",
                    token,
                    content,
                    "application/octet-stream",
                )
                print(f"    {name}: uploaded")
    except (ReleaseError, urllib.error.URLError) as error:
        sys.stderr.write(f"GitHub release failed: {error}\n")
        return 1
    print(f"Published {release.get('html_url')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
