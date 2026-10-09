from __future__ import annotations

import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QProcess, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QProgressDialog, QWidget

from comfycapture import __version__
from comfycapture.core import updates
from comfycapture.ui import messages
from comfycapture.ui.widgets import IconButton


class Background(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    progressed = Signal(int, int)

    def start(self, work: Callable[[], Any]) -> None:
        def run() -> None:
            try:
                result = work()
            except Exception as error:
                self.failed.emit(str(error) or error.__class__.__name__)
                return
            self.succeeded.emit(result)

        threading.Thread(target=run, daemon=True).start()


class UpdateBar(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("UpdateBar")
        self._release: updates.Release | None = None
        self._installation = updates.detect_installation()
        self._progress: QProgressDialog | None = None
        self._jobs: list[Background] = []

        self.message = QLabel()
        self.message.setObjectName("UpdateText")
        self.update_button = IconButton(self.tr("Update now"), "download", "primary", self._update)
        later = IconButton(self.tr("Later"), variant="ghost", on_click=self.hide)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(12)
        layout.addWidget(self.message, 1)
        layout.addWidget(later)
        layout.addWidget(self.update_button)
        self.hide()

    def check(self) -> None:
        def work(_job: Background) -> updates.Release | None:
            updates.remove_previous(self._installation)
            return updates.available_update()

        self._run(work, self._on_checked)

    def _run(
        self,
        work: Callable[[Background], Any],
        on_success: Callable[[Any], None],
        on_failure: Callable[[str], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> Background:
        job = Background(self)
        job.succeeded.connect(on_success)
        job.succeeded.connect(lambda _result: self._jobs.remove(job))
        job.failed.connect(lambda _message: self._jobs.remove(job))
        if on_failure is not None:
            job.failed.connect(on_failure)
        if on_progress is not None:
            job.progressed.connect(on_progress)
        self._jobs.append(job)
        job.start(lambda: work(job))
        return job

    def _on_checked(self, release: updates.Release | None) -> None:
        if release is None:
            return
        self._release = release
        self.message.setText(
            self.tr("ComfyCapture {version} is available (you have {current}).").format(
                version=release.version, current=__version__
            )
        )
        if not self._installation.can_update_in_place:
            self.update_button.setText(self.tr("Download"))
        self.show()

    def _update(self) -> None:
        release = self._release
        if release is None:
            return
        if not self._installation.can_update_in_place:
            QDesktopServices.openUrl(QUrl(release.page_url))
            return
        self.update_button.setEnabled(False)
        self._progress = QProgressDialog(
            self.tr("Downloading ComfyCapture {version}…").format(version=release.version),
            "",
            0,
            0,
            self.window(),
        )
        self._progress.setWindowTitle(self.tr("Updating"))
        self._progress.setCancelButton(None)
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.show()
        installation = self._installation

        def work(job: Background) -> list[str]:
            directory = Path(tempfile.mkdtemp(prefix="comfycapture-download-"))
            archive = updates.fetch_verified(release, installation, directory, job.progressed.emit)
            return updates.install(archive, installation)

        self._run(work, self._on_installed, self._on_failed, self._on_progress)

    def _on_progress(self, received: int, total: int) -> None:
        if self._progress is None or total <= 0:
            return
        self._progress.setMaximum(total)
        self._progress.setValue(received)
        if received >= total:
            self._progress.setLabelText(self.tr("Installing…"))

    def _on_installed(self, command: list[str]) -> None:
        if self._progress is not None:
            self._progress.close()
        QProcess.startDetached(command[0], command[1:])
        QApplication.quit()

    def _on_failed(self, message: str) -> None:
        if self._progress is not None:
            self._progress.close()
        self.update_button.setEnabled(True)
        messages.fail(
            self.window(),
            self.tr("Updating"),
            self.tr("The update failed: {error}\n\nYou can download it from {url}").format(
                error=message, url=self._release.page_url if self._release else updates.RELEASES_PAGE_URL
            ),
        )
