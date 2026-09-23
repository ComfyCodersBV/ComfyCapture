from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QProcess, Signal

from browsertests.core.processes import core_command


class CoreProcess(QObject):
    message = Signal(dict)
    finished = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process = QProcess(self)
        self._process.readyReadStandardOutput.connect(self._read)
        self._process.finished.connect(self._on_finished)
        self._buffer = b""
        self._stderr = b""
        self._process.readyReadStandardError.connect(self._read_error)
        self._payload_path: Path | None = None

    @property
    def stderr(self) -> str:
        return self._stderr.decode("utf-8", "replace")

    def start(self, module: str, payload: dict[str, Any]) -> None:
        handle, name = tempfile.mkstemp(prefix="browsertests-", suffix=".json")
        os.close(handle)
        self._payload_path = Path(name)
        self._payload_path.write_text(json.dumps(payload), encoding="utf-8")
        command = core_command(module, name)
        self._process.start(command[0], command[1:])

    def start_command(self, command: list[str]) -> None:
        self._process.start(command[0], command[1:])

    def stop(self) -> None:
        if self._process.state() == QProcess.ProcessState.NotRunning:
            return
        self._process.write(b"stop\n")

    def kill(self) -> None:
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
            self._process.waitForFinished(3000)

    def _read(self) -> None:
        self._buffer += bytes(self._process.readAllStandardOutput().data())
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                decoded = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, dict):
                self.message.emit(decoded)

    def _read_error(self) -> None:
        self._stderr += bytes(self._process.readAllStandardError().data())

    def _on_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        self._read()
        if self._payload_path is not None:
            self._payload_path.unlink(missing_ok=True)
            self._payload_path = None
        self.finished.emit(exit_code)
