from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QComboBox, QWidget

from comfycapture.ui import theme, translations
from comfycapture.ui.dialogs import FormDialog
from comfycapture.ui.widgets import hint


class SettingsDialog(FormDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.set_heading(self.tr("Settings"))
        self.language = QComboBox()
        for value, label in (("", self.tr("System default")), ("en", "English"), ("nl", "Nederlands")):
            self.language.addItem(label, value)
        self.language.setCurrentIndex(
            max(0, self.language.findData(QSettings().value(translations.LANGUAGE_KEY, "", str)))
        )
        self.appearance = QComboBox()
        for value, label in (
            ("system", self.tr("System default")),
            ("light", self.tr("Light")),
            ("dark", self.tr("Dark")),
        ):
            self.appearance.addItem(label, value)
        self.appearance.setCurrentIndex(max(0, self.appearance.findData(theme.preferred_theme())))
        self.appearance.currentIndexChanged.connect(self._preview_theme)
        self.add_field(self.tr("Language"), self.language, required=True)
        self.add_widget(hint(self.tr("A language change takes effect after restarting the app.")))
        self.layout_.addSpacing(8)
        self.add_field(self.tr("Appearance"), self.appearance, required=True)
        self.finish_layout(self.tr("Save settings"))
        self._original_theme = theme.preferred_theme()

    def _preview_theme(self) -> None:
        application = QApplication.instance()
        if isinstance(application, QApplication):
            theme.apply_theme(application, self.appearance.currentData())

    def accept(self) -> None:
        settings = QSettings()
        settings.setValue(translations.LANGUAGE_KEY, self.language.currentData())
        settings.setValue(theme.THEME_KEY, self.appearance.currentData())
        super().accept()

    def reject(self) -> None:
        application = QApplication.instance()
        if isinstance(application, QApplication):
            theme.apply_theme(application, self._original_theme)
        super().reject()
