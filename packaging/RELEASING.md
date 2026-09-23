# Releasing

Desktop builds are made by hand, one per OS, with the same command everywhere. CI only runs the tests
and, on a version tag, creates the GitLab release that links to the uploaded builds.

| OS      | Archive                                          |
|---------|--------------------------------------------------|
| Linux   | `BrowsertestSuite-<version>-linux-x86_64.tar.gz` |
| macOS   | `BrowsertestSuite-<version>-macos-arm64.zip`     |
| Windows | `BrowsertestSuite-<version>-windows-x86_64.zip`  |

The list of expected archives is `RELEASE_TARGETS` in `.gitlab-ci.yml`; the release job fails if one is
missing, so a release never goes out half-built.

## Once per machine

1. Install git and [uv](https://docs.astral.sh/uv/getting-started/installation/):
   - Ubuntu / macOS: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
2. Clone: `git clone git@gitlab.comfycoders.nl:tranquil-tools/browsertest-suite.git`
3. Create a GitLab personal access token with the `api` scope (Passbolt is the place to keep it) and make
   it available as `GITLAB_TOKEN` when uploading:
   - Ubuntu / macOS: `export GITLAB_TOKEN=...`
   - Windows (PowerShell): `$env:GITLAB_TOKEN = "..."`

Ubuntu additionally needs the Qt runtime libraries, which a desktop install already has:
`sudo apt install libgl1 libegl1 libxkbcommon0 libfontconfig1 libdbus-1-3`.

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
   and uploads both to the package registry of this project.

   Without `--upload` it is a local test build; that is also the way to check a change to packaging.

Once all three are uploaded:

4. In GitLab, open the tag's pipeline (Build → Pipelines) and retry the `release` job. It checks that
   every archive is in the registry and creates the release with links to them.

A failed build on one OS can be rebuilt and re-uploaded with the same command; uploading the same file
name again adds a newer file to the package, and downloads always serve the newest.

## Installing a build

The builds are not signed yet, so each OS warns the first time.

- **Linux**: `tar xzf BrowsertestSuite-*.tar.gz` and run `BrowsertestSuite/BrowsertestSuite`.
- **macOS**: unzip, move `BrowsertestSuite.app` to Applications, then once:
  `xattr -dr com.apple.quarantine /Applications/BrowsertestSuite.app` (or right-click → Open).
- **Windows**: unzip anywhere and run `BrowsertestSuite\BrowsertestSuite.exe`; on the SmartScreen warning
  choose More info → Run anyway.

On the first recording the app offers to download Chromium (about 150 MB) into the user data directory;
no admin rights are needed.

## Upgrading Playwright

A Playwright bump changes the browser build and the recorder's environment. Treat it as its own task:
bump the pin in `pyproject.toml` and the image tag in `.gitlab-ci.yml` together, run the full test suite,
and do a local test build before releasing.
