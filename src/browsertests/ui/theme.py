from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

THEME_KEY = "ui/theme"
THEMES = ("system", "light", "dark")


@dataclass(frozen=True, slots=True)
class Tokens:
    background: str
    surface: str
    surface_raised: str
    sidebar: str
    border: str
    text: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_text: str
    accent_soft: str
    danger: str
    warning: str
    success: str
    selection: str
    input: str


LIGHT = Tokens(
    background="#f6f6f9",
    surface="#ffffff",
    surface_raised="#fbfbfd",
    sidebar="#eeeef4",
    border="#e2e2ea",
    text="#1b1b25",
    text_muted="#6b6b7b",
    accent="#7c3aed",
    accent_hover="#6d28d9",
    accent_text="#ffffff",
    accent_soft="#ede7fd",
    danger="#dc2626",
    warning="#b45309",
    success="#15803d",
    selection="#e4dafc",
    input="#ffffff",
)

DARK = Tokens(
    background="#15151c",
    surface="#1d1d26",
    surface_raised="#23232e",
    sidebar="#111118",
    border="#2e2e3b",
    text="#ececf3",
    text_muted="#9a9aab",
    accent="#8b5cf6",
    accent_hover="#a78bfa",
    accent_text="#ffffff",
    accent_soft="#2d2445",
    danger="#f87171",
    warning="#fbbf24",
    success="#4ade80",
    selection="#3a2f5c",
    input="#17171f",
)


def preferred_theme() -> str:
    value = QSettings().value(THEME_KEY, "system", str)
    return value if value in THEMES else "system"


def system_is_dark() -> bool:
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def resolve_tokens(theme: str) -> Tokens:
    if theme == "dark":
        return DARK
    if theme == "light":
        return LIGHT
    return DARK if system_is_dark() else LIGHT


def palette(tokens: Tokens) -> QPalette:
    result = QPalette()
    roles = {
        QPalette.ColorRole.Window: tokens.background,
        QPalette.ColorRole.WindowText: tokens.text,
        QPalette.ColorRole.Base: tokens.input,
        QPalette.ColorRole.AlternateBase: tokens.surface_raised,
        QPalette.ColorRole.Text: tokens.text,
        QPalette.ColorRole.Button: tokens.surface,
        QPalette.ColorRole.ButtonText: tokens.text,
        QPalette.ColorRole.Highlight: tokens.accent,
        QPalette.ColorRole.HighlightedText: tokens.accent_text,
        QPalette.ColorRole.ToolTipBase: tokens.surface_raised,
        QPalette.ColorRole.ToolTipText: tokens.text,
        QPalette.ColorRole.PlaceholderText: tokens.text_muted,
        QPalette.ColorRole.Link: tokens.accent,
    }
    for role, color in roles.items():
        result.setColor(role, QColor(color))
    result.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(tokens.text_muted))
    result.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(tokens.text_muted))
    return result


def stylesheet(tokens: Tokens) -> str:
    return f"""
    * {{ font-size: 13px; }}
    QMainWindow, QDialog {{ background: {tokens.background}; color: {tokens.text}; }}
    QWidget {{ color: {tokens.text}; }}
    QToolTip {{ background: {tokens.surface_raised}; color: {tokens.text}; border: 1px solid {tokens.border};
        padding: 6px 8px; border-radius: 6px; }}

    #Sidebar {{ background: {tokens.sidebar}; border-right: 1px solid {tokens.border}; }}
    #Brand {{ font-size: 15px; font-weight: 700; }}
    #BrandSub {{ color: {tokens.text_muted}; font-size: 11px; }}
    #SidebarHeading {{ color: {tokens.text_muted}; font-size: 11px; font-weight: 600; }}
    #ProjectList {{ background: transparent; border: none; outline: 0; }}
    #ProjectList::item {{ padding: 8px 10px; border-radius: 8px; margin: 1px 0; }}
    #ProjectList::item:hover {{ background: {tokens.surface}; }}
    #ProjectList::item:selected {{ background: {tokens.accent_soft}; color: {tokens.text}; font-weight: 600; }}

    #PageTitle {{ font-size: 22px; font-weight: 700; }}
    #PageSubtitle, #Muted {{ color: {tokens.text_muted}; }}
    #Card {{ background: {tokens.surface}; border: 1px solid {tokens.border}; border-radius: 12px; }}
    #CardTitle {{ font-size: 15px; font-weight: 600; }}
    #EmptyState {{ color: {tokens.text_muted}; font-size: 14px; }}
    #Status {{ color: {tokens.text_muted}; }}
    #Required {{ color: {tokens.danger}; font-weight: 700; }}
    #Optional {{ color: {tokens.text_muted}; font-size: 11px; }}
    #FieldHint {{ color: {tokens.text_muted}; font-size: 11px; }}
    #Badge {{ background: {tokens.accent_soft}; color: {tokens.accent}; border-radius: 9px; padding: 2px 8px;
        font-size: 11px; font-weight: 600; }}

    QPushButton {{ background: {tokens.surface}; color: {tokens.text}; border: 1px solid {tokens.border};
        border-radius: 8px; padding: 7px 14px; }}
    QPushButton:hover {{ border-color: {tokens.accent}; }}
    QPushButton:pressed {{ background: {tokens.surface_raised}; }}
    QPushButton:disabled {{ color: {tokens.text_muted}; border-color: {tokens.border}; }}
    QPushButton[variant="primary"] {{ background: {tokens.accent}; color: {tokens.accent_text}; border: 1px solid {tokens.accent};
        font-weight: 600; }}
    QPushButton[variant="primary"]:hover {{ background: {tokens.accent_hover}; border-color: {tokens.accent_hover}; }}
    QPushButton[variant="primary"]:disabled {{ background: {tokens.border}; border-color: {tokens.border}; }}
    QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; }}
    QPushButton[variant="ghost"]:hover {{ background: {tokens.surface}; border-color: {tokens.border}; }}
    QPushButton:checked, QPushButton[variant="ghost"]:checked {{ background: {tokens.accent_soft};
        border: 1px solid {tokens.accent}; color: {tokens.text}; }}
    QPushButton[variant="danger"] {{ color: {tokens.danger}; background: transparent; border: 1px solid transparent; }}
    QPushButton[variant="danger"]:hover {{ border-color: {tokens.danger}; }}
    QPushButton[variant="danger"]:disabled, QPushButton[variant="ghost"]:disabled {{ color: {tokens.text_muted};
        border-color: transparent; }}

    QLineEdit, QComboBox, QPlainTextEdit {{ background: {tokens.input}; border: 1px solid {tokens.border};
        border-radius: 8px; padding: 7px 10px; selection-background-color: {tokens.selection};
        selection-color: {tokens.text}; }}
    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {tokens.accent}; }}
    QLineEdit[invalid="true"] {{ border: 1px solid {tokens.danger}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox QAbstractItemView {{ background: {tokens.surface}; border: 1px solid {tokens.border};
        selection-background-color: {tokens.accent_soft}; selection-color: {tokens.text}; outline: 0; padding: 4px; }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {tokens.border};
        background: {tokens.input}; }}
    QCheckBox::indicator:checked {{ background: {tokens.accent}; border-color: {tokens.accent}; }}

    QListWidget {{ background: {tokens.input}; border: 1px solid {tokens.border}; border-radius: 8px;
        padding: 4px; outline: 0; }}
    QListWidget::item {{ padding: 7px 8px; border-radius: 6px; }}
    QListWidget::item:selected {{ background: {tokens.accent_soft}; color: {tokens.text}; }}
    QTableWidget {{ background: transparent; border: none; gridline-color: transparent; outline: 0;
        alternate-background-color: {tokens.surface_raised}; }}
    QTableWidget::item {{ padding: 6px 8px; border-bottom: 1px solid {tokens.border}; }}
    QTableWidget::item:selected {{ background: {tokens.accent_soft}; color: {tokens.text}; }}
    QHeaderView {{ background: transparent; border: none; }}
    QHeaderView::section {{ background: transparent; color: {tokens.text_muted}; border: none;
        border-bottom: 1px solid {tokens.border}; padding: 6px 8px; font-size: 11px; font-weight: 600; }}
    QTableCornerButton::section {{ background: transparent; border: none; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {tokens.border}; border-radius: 4px; min-height: 30px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {tokens.border}; border-radius: 4px; min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QSplitter::handle {{ background: {tokens.border}; width: 1px; }}
    QMessageBox {{ background: {tokens.surface}; }}
    """


def apply_theme(application: QApplication, theme: str | None = None) -> Tokens:
    tokens = resolve_tokens(theme or preferred_theme())
    application.setStyle("Fusion")
    application.setPalette(palette(tokens))
    application.setStyleSheet(stylesheet(tokens))
    return tokens


def follow_system(application: QApplication) -> None:
    def changed(_scheme: Qt.ColorScheme) -> None:
        if preferred_theme() == "system":
            apply_theme(application)

    QGuiApplication.styleHints().colorSchemeChanged.connect(changed)
