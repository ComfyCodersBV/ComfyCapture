"""Health check for packaged builds: proves the core subprocess can talk to the desktop over stdout."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from importlib import resources

from browsertests import __version__


def main(argv: Sequence[str] | None = None) -> int:
    from playwright._repo_version import version as playwright_version

    recorder = resources.files("browsertests.core").joinpath("recorder.js").is_file()
    report = {
        "type": "health",
        "version": __version__,
        "playwright": playwright_version,
        "recorder_script": recorder,
        "stdout": True,
    }
    sys.stdout.write(json.dumps(report) + "\n")
    sys.stdout.flush()
    return 0 if recorder else 1


if __name__ == "__main__":
    sys.exit(main())
