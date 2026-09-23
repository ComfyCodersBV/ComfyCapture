$ErrorActionPreference = "Stop"

if (-not $env:GITLAB_TOKEN) {
    throw "Set GITLAB_TOKEN to a GitLab token with the api scope"
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

uv sync --all-extras --group package
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run --group package python packaging/build.py --upload
exit $LASTEXITCODE
