# Releasing

Desktop builds are made by hand, one per OS, with the same command everywhere. CI only runs the tests
and, on a version tag, creates the GitLab release that links to the uploaded builds.

| OS      | Archive                                          |
|---------|--------------------------------------------------|
| Linux   | `ComfyCapture-<version>-linux-x86_64.tar.gz` |
| Ubuntu  | `ComfyCapture-<version>-linux-x86_64.deb`    |
| macOS   | `ComfyCapture-<version>-macos-arm64.zip`     |
| Windows | `ComfyCapture-<version>-windows-x86_64.zip`  |

The list of expected archives is `RELEASE_TARGETS` in `.gitlab-ci.yml`; the release job fails if one is
missing, so a release never goes out half-built.

## Quick: one line per machine

Needs git and a GitLab token with the `api` scope (your avatar → Preferences → Access tokens). The line
clones the repository with that token, checks out the release tag, installs uv when missing, builds,
smoke-tests and uploads. Replace the token and the tag.

**macOS** (Terminal; the first `git` call may ask to install the Xcode command line tools):

```bash
export GITLAB_TOKEN=glpat-XXXX TAG=v0.1.0; git clone -q "https://oauth2:$GITLAB_TOKEN@gitlab.comfycoders.nl/tranquil-tools/comfy-capture.git" ~/bt-release && cd ~/bt-release && git checkout -q $TAG && git show origin/main:packaging/release-build.sh | bash
```

**Windows** (PowerShell; install git first with `winget install Git.Git` if needed):

```powershell
$env:GITLAB_TOKEN="glpat-XXXX"; $tag="v0.1.0"; git clone -q "https://oauth2:$env:GITLAB_TOKEN@gitlab.comfycoders.nl/tranquil-tools/comfy-capture.git" "$HOME\bt-release"; cd "$HOME\bt-release"; git checkout -q $tag; git show origin/main:packaging/release-build.ps1 | Out-File -Encoding utf8 "$env:TEMP\release-build.ps1"; powershell -ExecutionPolicy Bypass -File "$env:TEMP\release-build.ps1"
```

Delete the `bt-release` folder afterwards: its git config contains the token. An Intel Mac builds
`macos-x86_64`, which the release job does not expect; build on Apple Silicon.

## Once per machine

1. Install git and [uv](https://docs.astral.sh/uv/getting-started/installation/):
   - Ubuntu / macOS: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
2. Clone: `git clone git@gitlab.comfycoders.nl:tranquil-tools/comfy-capture.git`
3. Create a GitLab personal access token with the `api` scope (Passbolt is the place to keep it) and make
   it available as `GITLAB_TOKEN` when uploading:
   - Ubuntu / macOS: `export GITLAB_TOKEN=...`
   - Windows (PowerShell): `$env:GITLAB_TOKEN = "..."`

Ubuntu additionally needs the Qt runtime libraries, which a desktop install already has:
`sudo apt install libgl1 libegl1 libxkbcommon0 libfontconfig1 libdbus-1-3`. The Linux build also makes
the `.deb`, which needs `dpkg-deb` (part of every Ubuntu install).

## Per release

On the development machine:

1. Bump `version` in `pyproject.toml` (skip for the very first release, 0.1.0), then `uv lock`.
2. Commit, tag and push both:
   ```bash
   git commit -am "Release 0.2.0"
   git tag v0.2.0
   git push origin main v0.2.0
   ```
   The tag pipeline's `release` job fails at this point because the builds are not uploaded yet. That
   is expected; it is retried in step 4.

On each OS (Linux, macOS, Windows), in the clone:

3. Check out the tag and build + upload:
   ```bash
   git fetch --tags && git checkout v0.2.0
   uv sync --all-extras --group package
   uv run --group package python packaging/build.py --upload
   ```
   The script refuses to upload unless the working tree is clean and HEAD carries the tag matching
   `pyproject.toml`. It builds with PyInstaller, runs a smoke test (the core subprocess must answer over
   stdout, the window must stay up for a few seconds), writes the archive plus a `.sha256` to `releases/`
   and uploads both to the package registry of this project. On Linux it also builds and uploads the
   `.deb`.

   Without `--upload` it is a local test build; that is also the way to check a change to packaging.

Once all three are uploaded:

4. In GitLab, open the tag's pipeline (Build → Pipelines) and retry the `release` job. It checks that
   every archive is in the registry and creates the release with links to them. After it, the
   `github-release` job copies the archives and checksums to a GitHub release of the same tag. Run it by
   hand if it stays skipped.

## Updates through GitHub

Installed apps check `https://api.github.com/repos/ComfyCodersBV/ComfyCapture/releases/latest` a few
seconds after start. When the tag there is newer than the app, a bar offers the update. "Update now"
downloads the archive for that OS, checks it against its `.sha256` and installs it:

- **Ubuntu (.deb)**: `pkexec apt-get install`, so one password prompt, then the app restarts.
- **Other Linux, macOS**: the app folder or `.app` is swapped for the new one (the old one is kept as
  `*.previous` until the next start), then the app restarts. The folder must be writable for the user.
- **Windows**: a small PowerShell script waits for the app to close, swaps the folder and starts it again.
- **From source** (`uv run`): only a link to the release page.

So a release reaches users only once it is on GitHub. Needed once:

1. A push mirror from GitLab to `github.com/ComfyCodersBV/ComfyCapture` (Settings → Repository →
   Mirroring repositories). The repository must be public: the app checks without a token.
2. A GitHub fine-grained token for that repository with *Contents: read and write*, stored in GitLab as
   the CI/CD variable `GITHUB_TOKEN` (masked, protected). Protected variables only reach protected
   tags, so protect `v*` under Settings → Repository → Protected tags. Without the variable the
   `github-release` job does not run.

A failed build on one OS can be rebuilt and re-uploaded with the same command; uploading the same file
name again adds a newer file to the package, and downloads always serve the newest.

## Installing a build

The builds are not signed yet, so each OS warns the first time.

- **Ubuntu**: `sudo apt install ./ComfyCapture-*.deb` (or open it in App Center). ComfyCapture then
  shows up in the app grid. Later versions arrive through the update bar; remove with
  `sudo apt remove comfycapture`.
- **Other Linux**: `tar xzf ComfyCapture-*.tar.gz` and run `ComfyCapture/ComfyCapture`.
- **macOS**: unzip, move `ComfyCapture.app` to Applications, then once:
  `xattr -dr com.apple.quarantine /Applications/ComfyCapture.app` (or right-click → Open).
- **Windows**: unzip anywhere and run `ComfyCapture\ComfyCapture.exe`; on the SmartScreen warning
  choose More info → Run anyway.

On the first recording the app offers to download Chromium (about 150 MB) into the user data directory;
no admin rights are needed.

## Upgrading Playwright

A Playwright bump changes the browser build and the recorder's environment. Treat it as its own task:
bump the pin in `pyproject.toml` and the image tag in `.gitlab-ci.yml` together, run the full test suite,
and do a local test build before releasing.
