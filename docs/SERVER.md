# Running on a server

The runner is the same `browsertests` CLI as on the desktop, without the Qt parts. Record on a desktop,
export the tests, import them on the server, run them on a schedule.

## Image

```bash
docker build -t browsertests .
docker volume create browsertests-data
```

The image is based on `mcr.microsoft.com/playwright/python:v1.63.0-noble`, which carries the browsers
and system libraries for the pinned Playwright version. Bump the tag together with the Playwright pin in
`pyproject.toml`. Data (database, traces) lives in the `/data` volume.

## Getting tests onto the server

```bash
browsertests export --project shop --out exports/          # on the desktop
docker run --rm -v browsertests-data:/data -v "$PWD/exports:/exports:ro" \
    browsertests import /exports/*.json                     # on the server
```

The import reports the variables and secrets the server still needs. Variables live in the database
(set them on a desktop before exporting, or edit the SQLite `variables` table). Secrets never travel in
an export.

## Secrets

Environment variables `BROWSERTESTS_SECRET_<NAME>` (upper-case, other characters as `_`), or one file
outside any repository, named by `BROWSERTESTS_SECRETS_FILE`:

```bash
# /etc/browsertests/shop.env, chmod 600
BROWSERTESTS_SECRET_ADMIN_PASSWORD=...
BROWSERTESTS_SECRET_STAGING_BASIC_AUTH=user:password
```

```bash
docker run --rm -v browsertests-data:/data -v /etc/browsertests/shop.env:/run/secrets/shop.env:ro \
    -e BROWSERTESTS_SECRETS_FILE=/run/secrets/shop.env \
    browsertests run --project shop --env staging --tag smoke
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | all tests passed (flaky tests are reported, not failed) |
| 1 | at least one test failed |
| 2 | configuration problem: unknown project/environment, missing variable or secret, failing login test, or a destructive test refused on a protected environment |

`--workers N` (default 2) runs tests in parallel; each Chromium costs about 300 MB. `--retries N`
(default 1) retries a failing test; a pass on retry is reported as flaky. Traces of failures are kept
14 days under `/data/BrowsertestSuite/artifacts/` and pruned after every run.

## Notifications

On failure (exit code 1 or 2) the runner can alert by itself:

```bash
browsertests run --project shop --env staging \
    --notify-webhook https://hooks.slack.com/services/…      # or $BROWSERTESTS_NOTIFY_WEBHOOK
browsertests run --project shop --env staging \
    --notify-command '/usr/local/bin/mail-team'               # or $BROWSERTESTS_NOTIFY_COMMAND
```

- The webhook gets a JSON POST whose `text` field is a readable summary, which Slack and Mattermost
  incoming webhooks show as is; `results` carries every test's status, failed step and message.
- The command runs through the shell with `BROWSERTESTS_EXIT_CODE`, `BROWSERTESTS_PROJECT`,
  `BROWSERTESTS_ENVIRONMENT` and `BROWSERTESTS_SUMMARY` set and the same JSON on stdin, so mail or a
  ticket system is one small script.
- `--notify-always` also reports green runs. A failing notification is a warning and does not change the
  exit code.

## Scheduling

No scheduler is built in. Use the one the machine already has.

### systemd (recommended on Linux)

`/etc/systemd/system/browsertests-shop.service`

```ini
[Unit]
Description=Browser tests for shop (staging)
OnFailure=browsertests-notify@%n.service

[Service]
Type=oneshot
ExecStart=/usr/bin/docker run --rm -v browsertests-data:/data \
    -v /etc/browsertests/shop.env:/run/secrets/shop.env:ro -e BROWSERTESTS_SECRETS_FILE=/run/secrets/shop.env \
    browsertests run --project shop --env staging
```

`/etc/systemd/system/browsertests-shop.timer`

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
systemctl daemon-reload && systemctl enable --now browsertests-shop.timer
journalctl -u browsertests-shop.service    # results
```

A non-zero exit marks the unit failed, which triggers `OnFailure=` for anything systemd-level.

### cron

```cron
0 * * * * docker run --rm -v browsertests-data:/data -e BROWSERTESTS_SECRETS_FILE=/run/secrets/shop.env -v /etc/browsertests/shop.env:/run/secrets/shop.env:ro browsertests run --project shop --env staging >> /var/log/browsertests-shop.log 2>&1 || /usr/local/bin/notify-failure shop
```

### Windows Task Scheduler

```powershell
schtasks /Create /TN "BrowserTests shop" /SC HOURLY /TR "C:\Tools\BrowsertestSuite\BrowsertestSuite.exe --core browsertests.cli run --project shop --env staging"
```

The packaged desktop build contains the CLI: `BrowsertestSuite.exe --core browsertests.cli <arguments>`.
