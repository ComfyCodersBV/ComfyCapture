# Running on a server

The runner is the same `comfycapture` CLI as on the desktop, without the Qt parts. Record on a desktop,
export the tests, import them on the server, run them on a schedule.

## Image

```bash
docker build -t comfycapture .
docker volume create comfycapture-data
```

The image is based on `mcr.microsoft.com/playwright/python:v1.63.0-noble`, which carries the browsers
and system libraries for the pinned Playwright version. Bump the tag together with the Playwright pin in
`pyproject.toml`. Data (database, traces) lives in the `/data` volume.

On Docker Desktop, only paths under your home directory can be mounted, and `127.0.0.1` inside the
container is the Docker VM: point an environment at `http://host.docker.internal:<port>` to test a site
running on the host.

## Getting tests onto the server

```bash
comfycapture export --project shop --out exports/          # on the desktop
docker run --rm -v comfycapture-data:/data -v "$PWD/exports:/exports:ro" \
    comfycapture import /exports/*.json                     # on the server
```

The import reports the variables and secrets the server still needs. Variables live in the database
(set them on a desktop before exporting, or edit the SQLite `variables` table). Secrets never travel in
an export.

## Secrets

Environment variables `COMFYCAPTURE_SECRET_<NAME>` (upper-case, other characters as `_`), or one file
outside any repository, named by `COMFYCAPTURE_SECRETS_FILE`:

```bash
# /etc/comfycapture/shop.env, chmod 600
COMFYCAPTURE_SECRET_ADMIN_PASSWORD=...
COMFYCAPTURE_SECRET_STAGING_BASIC_AUTH=user:password
```

```bash
docker run --rm -v comfycapture-data:/data -v /etc/comfycapture/shop.env:/run/secrets/shop.env:ro \
    -e COMFYCAPTURE_SECRETS_FILE=/run/secrets/shop.env \
    comfycapture run --project shop --env staging --tag smoke
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | all tests passed (flaky tests are reported, not failed) |
| 1 | at least one test failed |
| 2 | configuration problem: unknown project/environment, missing variable or secret, failing login test, or a destructive test refused on a protected environment |

`--workers N` (default 2) runs tests in parallel; each Chromium costs about 300 MB. `--retries N`
(default 1) retries a failing test; a pass on retry is reported as flaky. Traces of failures are kept
14 days under `/data/ComfyCapture/artifacts/` and pruned after every run.

## Notifications

On failure (exit code 1 or 2) the runner can alert by itself:

```bash
comfycapture run --project shop --env staging \
    --notify-webhook https://hooks.slack.com/services/…      # or $COMFYCAPTURE_NOTIFY_WEBHOOK
comfycapture run --project shop --env staging \
    --notify-command '/usr/local/bin/mail-team'               # or $COMFYCAPTURE_NOTIFY_COMMAND
```

- The webhook gets a JSON POST whose `text` field is a readable summary, which Slack and Mattermost
  incoming webhooks show as is; `results` carries every test's status, failed step and message.
- The command runs through the shell with `COMFYCAPTURE_EXIT_CODE`, `COMFYCAPTURE_PROJECT`,
  `COMFYCAPTURE_ENVIRONMENT` and `COMFYCAPTURE_SUMMARY` set and the same JSON on stdin, so mail or a
  ticket system is one small script.
- `--notify-always` also reports green runs. A failing notification is a warning and does not change the
  exit code.

## Scheduling

No scheduler is built in. Use the one the machine already has.

### systemd (recommended on Linux)

`/etc/systemd/system/comfycapture-shop.service`

```ini
[Unit]
Description=Browser tests for shop (staging)
OnFailure=comfycapture-notify@%n.service

[Service]
Type=oneshot
ExecStart=/usr/bin/docker run --rm -v comfycapture-data:/data \
    -v /etc/comfycapture/shop.env:/run/secrets/shop.env:ro -e COMFYCAPTURE_SECRETS_FILE=/run/secrets/shop.env \
    comfycapture run --project shop --env staging
```

`/etc/systemd/system/comfycapture-shop.timer`

```ini
[Unit]
Description=Run the shop browser tests every hour

[Timer]
OnCalendar=hourly
RandomizedDelaySec=5m
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl daemon-reload && systemctl enable --now comfycapture-shop.timer
journalctl -u comfycapture-shop.service    # results
```

A non-zero exit marks the unit failed, which triggers `OnFailure=` for anything systemd-level.

### cron

```cron
0 * * * * docker run --rm -v comfycapture-data:/data -e COMFYCAPTURE_SECRETS_FILE=/run/secrets/shop.env -v /etc/comfycapture/shop.env:/run/secrets/shop.env:ro comfycapture run --project shop --env staging >> /var/log/comfycapture-shop.log 2>&1 || /usr/local/bin/notify-failure shop
```

### Windows Task Scheduler

```powershell
schtasks /Create /TN "ComfyCapture shop" /SC HOURLY /TR "C:\Tools\ComfyCapture\ComfyCapture.exe --core comfycapture.cli run --project shop --env staging"
```

The packaged desktop build contains the CLI: `ComfyCapture.exe --core comfycapture.cli <arguments>`.
