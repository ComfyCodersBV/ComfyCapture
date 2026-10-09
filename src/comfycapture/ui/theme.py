from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

THEME_KEY = "ui/theme"
THEMES = ("system", "light", "dark")
FONTS = Path(__file__).resolve().parent / "fonts"
HEADING_FONT = "Montserrat"
BODY_FONT = "DM Sans"


@dataclass(frozen=True, slots=True)
class Pill:
    background: str
    text: str
    dot: str | None


@dataclass(frozen=True, slots=True)
class Tokens:
    dark: bool
    background: str
    surface: str
    surface_raised: str
    sidebar: str
    sidebar_border: str
    border: str
    text: str
    text_secondary: str
    text_muted: str
    text_subtle: str
    accent: str
    accent_hover: str
    accent_text: str
    accent_soft: str
    highlight: str
    outline: str
    hover: str
    row_hover: str
    danger: str
    danger_soft: str
    warning: str
    success: str
    selection: str
    input: str
    search: str


LIGHT = Tokens(
    dark=False,
    background="#F6F4FA",
    surface="#FFFFFF",
    surface_raised="#FBFAFD",
    sidebar="#FFFFFF",
    sidebar_border="#E4DFEE",
    border="#E4DFEE",
    text="#221B35",
    text_secondary="#3F2B6C",
    text_muted="#65539E",
    text_subtle="#7A6FA0",
    accent="#E6287D",
    accent_hover="#C91E6A",
    accent_text="#FFFFFF",
    accent_soft="#EDE8F7",
    highlight="#60C2DE",
    outline="#65539E",
    hover="#E4DFEE",
    row_hover="#F3F0F8",
    danger="#E6287D",
    danger_soft="#FCE4EF",
    warning="#9A6500",
    success="#15803D",
    selection="#EDE8F7",
    input="#FFFFFF",
    search="#F6F4FA",
)

DARK = Tokens(
    dark=True,
    background="#221B35",
    surface="#2A2142",
    surface_raised="#2F2549",
    sidebar="#1B152B",
    sidebar_border="#2E2548",
    border="#362B55",
    text="#FFFFFF",
    text_secondary="#D8D2E8",
    text_muted="#B8B0CF",
    text_subtle="#8C82AB",
    accent="#E6287D",
    accent_hover="#C91E6A",
    accent_text="#FFFFFF",
    accent_soft="#3F2B6C",
    highlight="#60C2DE",
    outline="#65539E",
    hover="#362B55",
    row_hover="#322850",
    danger="#E6287D",
    danger_soft="#3A1C3E",
    warning="#F7A810",
    success="#4ADE80",
    selection="#3F2B6C",
    input="#221B35",
    search="#221B35",
)

PILLS = {
    False: {
        "neutral": Pill("#E4DFEE", "#3F2B6C", None),
        "warning": Pill("#FDF0D2", "#9A6500", "#F7A810"),
        "success": Pill("#DCF5E6", "#15803D", "#22C55E"),
        "danger": Pill("#FCE4EF", "#C91E6A", "#E6287D"),
        "info": Pill("#E0F3F9", "#1F7FA0", "#60C2DE"),
    },
    True: {
        "neutral": Pill("#362B55", "#D8D2E8", None),
        "warning": Pill("#3B2E1E", "#F7A810", "#F7A810"),
        "success": Pill("#1E3B2E", "#4ADE80", "#4ADE80"),
        "danger": Pill("#3A1C3E", "#FF5FA2", "#E6287D"),
        "info": Pill("#1C3341", "#60C2DE", "#60C2DE"),
    },
}

_active = {"tokens": LIGHT}


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


def active_tokens() -> Tokens:
    return _active["tokens"]


def pill(tone: str) -> Pill:
    pills = PILLS[active_tokens().dark]
    return pills.get(tone, pills["neutral"])


def load_fonts() -> None:
    if HEADING_FONT in QFontDatabase.families() and BODY_FONT in QFontDatabase.families():
        return
    for path in sorted(FONTS.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))


def heading_font(pixel_size: int, weight: QFont.Weight, spacing: float = 0) -> QFont:
    font = QFont(HEADING_FONT)
    font.setPixelSize(pixel_size)
    font.setWeight(weight)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100 + spacing)
    return font


def palette(tokens: Tokens) -> QPalette:
    result = QPalette()
    roles = {
        QPalette.ColorRole.Window: tokens.background,
        QPalette.ColorRole.WindowText: tokens.text,
        QPalette.ColorRole.Base: tokens.input,
        QPalette.ColorRole.AlternateBase: tokens.surface_raised,
        QPalette.ColorRole.Text: tokens.text,
        QPalette.ColorRole.Button: tokens.surface,
        QPalette.ColorRole.ButtonText: tokens.text_secondary,
        QPalette.ColorRole.Highlight: tokens.accent,
        QPalette.ColorRole.HighlightedText: tokens.accent_text,
        QPalette.ColorRole.ToolTipBase: tokens.surface_raised,
        QPalette.ColorRole.ToolTipText: tokens.text,
        QPalette.ColorRole.PlaceholderText: tokens.text_subtle,
        QPalette.ColorRole.Link: tokens.highlight,
    }
    for role, color in roles.items():
        result.setColor(role, QColor(color))
    result.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(tokens.text_subtle))
    result.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(tokens.text_subtle))
    return result


CHECK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#ffffff" '
    'stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>'
)


def check_image() -> str:
    path = Path(tempfile.gettempdir()) / "comfycapture-check.svg"
    if not path.is_file() or path.read_text(encoding="utf-8") != CHECK_SVG:
        path.write_text(CHECK_SVG, encoding="utf-8")
    return path.as_posix()


def stylesheet(tokens: Tokens) -> str:
    check = check_image()
    heading = f'font-family: "{HEADING_FONT}";'
    return f"""
    * {{ font-family: "{BODY_FONT}"; font-size: 14px; }}
    QMainWindow, QDialog {{ background: {tokens.background}; color: {tokens.text}; }}
    QWidget {{ color: {tokens.text}; }}
    QToolTip {{ background: {tokens.surface_raised}; color: {tokens.text}; border: 1px solid {tokens.border};
        padding: 6px 8px; border-radius: 8px; }}

    #Sidebar {{ background: {tokens.sidebar}; border-right: 1px solid {tokens.sidebar_border}; }}
    #Brand {{ {heading} font-size: 15px; }}
    #BrandSub {{ {heading} color: {tokens.text_subtle}; font-size: 10px; font-weight: 500; }}
    #SidebarHeading {{ {heading} color: {tokens.text_subtle}; font-size: 11px; font-weight: 700; }}
    #ProjectList {{ background: transparent; border: none; outline: 0; padding: 0; }}
    #ProjectList::item {{ padding: 10px 12px; border-radius: 14px; margin: 2px 0; color: {tokens.text_secondary}; }}
    #ProjectList::item:hover {{ background: {tokens.hover}; }}
    #ProjectList::item:selected {{ background: {tokens.accent_soft}; color: {tokens.text}; font-weight: 500; }}
    QPushButton#SidebarLink {{ text-align: left; padding: 0 14px; border-radius: 14px; height: 38px; }}

    #PageTitle {{ {heading} font-size: 28px; font-weight: 800; }}
    #PageSubtitle, #Muted {{ color: {tokens.text_muted}; }}
    #Card {{ background: {tokens.surface}; border: 1px solid {tokens.border}; border-radius: 20px; }}
    #CardTitle {{ {heading} font-size: 17px; font-weight: 700; }}
    #EmptyState {{ color: {tokens.text_muted}; font-size: 15px; }}
    #Status {{ color: {tokens.text_muted}; }}
    #Required {{ color: {tokens.danger}; font-weight: 700; }}
    #Optional {{ color: {tokens.text_subtle}; font-size: 12px; }}
    #FieldHint {{ color: {tokens.text_subtle}; font-size: 12px; }}
    #MessageText {{ color: {tokens.text_secondary}; font-size: 14px; }}
    #UpdateBar {{ background: {tokens.accent_soft}; border-bottom: 1px solid {tokens.border}; }}
    #UpdateText {{ color: {tokens.text}; font-size: 14px; font-weight: 600; }}
    #Badge {{ background: {tokens.accent_soft}; color: {tokens.text}; border-radius: 11px; padding: 3px 10px;
        font-size: 12px; font-weight: 500; }}

    QPushButton {{ {heading} background: transparent; color: {tokens.text}; border: 1px solid {tokens.outline};
        border-radius: 19px; padding: 0 16px; min-height: 36px; font-size: 13px; font-weight: 600; }}
    QPushButton:hover {{ background: {tokens.accent_soft}; }}
    QPushButton:pressed {{ background: {tokens.hover}; }}
    QPushButton:disabled {{ color: {tokens.text_subtle}; border-color: {tokens.border}; }}
    QPushButton[variant="primary"] {{ background: {tokens.accent}; color: {tokens.accent_text};
        border: 1px solid {tokens.accent}; font-weight: 700; padding: 0 18px; }}
    QPushButton[variant="primary"]:hover {{ background: {tokens.accent_hover}; border-color: {tokens.accent_hover}; }}
    QPushButton[variant="primary"]:disabled {{ background: {tokens.border}; border-color: {tokens.border};
        color: {tokens.text_subtle}; }}
    QPushButton[variant="ghost"], QPushButton[variant="danger"] {{ font-family: "{BODY_FONT}"; font-size: 14px;
        font-weight: 400; background: transparent; border: 1px solid transparent; border-radius: 12px;
        padding: 0 12px; color: {tokens.text_secondary}; }}
    QPushButton[variant="ghost"]:hover {{ background: {tokens.hover}; }}
    QPushButton[variant="danger"] {{ color: {tokens.danger}; }}
    QPushButton[variant="danger"]:hover {{ background: {tokens.danger_soft}; }}
    QPushButton[variant="destructive"] {{ background: {tokens.danger}; color: {tokens.accent_text};
        border: 1px solid {tokens.danger}; font-weight: 700; padding: 0 18px; }}
    QPushButton[variant="destructive"]:hover {{ background: {tokens.accent_hover}; border-color: {tokens.accent_hover}; }}
    QPushButton:checked, QPushButton[variant="ghost"]:checked {{ background: {tokens.accent_soft};
        border: 1px solid {tokens.outline}; color: {tokens.text}; }}
    QPushButton[variant="danger"]:disabled, QPushButton[variant="ghost"]:disabled {{ color: {tokens.text_subtle};
        background: transparent; border-color: transparent; }}

    QLineEdit, QComboBox, QPlainTextEdit {{ background: {tokens.input}; border: 1px solid {tokens.border};
        border-radius: 12px; padding: 8px 12px; selection-background-color: {tokens.selection};
        selection-color: {tokens.text}; }}
    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {tokens.outline}; }}
    QLineEdit[invalid="true"] {{ border: 1px solid {tokens.danger}; }}
    QLineEdit#SearchField {{ background: {tokens.search}; border-radius: 14px; padding: 0 12px; min-height: 42px; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox QAbstractItemView {{ background: {tokens.surface}; border: 1px solid {tokens.border};
        selection-background-color: {tokens.accent_soft}; selection-color: {tokens.text}; outline: 0; padding: 4px; }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {tokens.outline};
        background: {tokens.input}; }}
    QCheckBox::indicator:checked {{ background: {tokens.accent}; border-color: {tokens.accent};
        image: url("{check}"); }}

    QListWidget {{ background: {tokens.input}; border: 1px solid {tokens.border}; border-radius: 12px;
        padding: 4px; outline: 0; }}
    QListWidget::item {{ padding: 8px 10px; border-radius: 10px; }}
    QListWidget::item:hover {{ background: {tokens.row_hover}; }}
    QListWidget::item:selected {{ background: {tokens.accent_soft}; color: {tokens.text}; }}
    QTableWidget {{ background: transparent; border: none; gridline-color: transparent; outline: 0;
        alternate-background-color: {tokens.surface_raised}; }}
    QTableWidget::item {{ padding: 6px 12px; color: {tokens.text_secondary}; }}
    QTableWidget::item:hover {{ background: {tokens.row_hover}; }}
    QTableWidget::item:selected {{ background: {tokens.selection}; color: {tokens.text}; }}
    QHeaderView {{ background: transparent; border: none; }}
    QHeaderView::section {{ {heading} background: transparent; color: {tokens.text_subtle}; border: none;
        border-bottom: 1px solid {tokens.border}; padding: 6px 12px 10px 12px; font-size: 11px; font-weight: 600; }}
    QTableCornerButton::section {{ background: transparent; border: none; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {tokens.border}; border-radius: 4px; min-height: 30px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {tokens.border}; border-radius: 4px; min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QSplitter::handle {{ background: {tokens.border}; width: 1px; }}
    QMenu {{ background: {tokens.surface}; border: 1px solid {tokens.border}; padding: 6px; }}
    QMenu::item {{ padding: 8px 16px 8px 12px; border-radius: 8px; color: {tokens.text_secondary}; }}
    QMenu::item:selected {{ background: {tokens.hover}; color: {tokens.text}; }}
    QMenu::icon {{ padding-left: 10px; }}
    QMenu::separator {{ height: 1px; background: {tokens.border}; margin: 6px 4px; }}
    """


def apply_theme(application: QApplication, theme: str | None = None) -> Tokens:
    load_fonts()
    tokens = resolve_tokens(theme or preferred_theme())
    _active["tokens"] = tokens
    application.setStyle("Fusion")
    application.setFont(QFont(BODY_FONT))
    application.setPalette(palette(tokens))
    application.setStyleSheet(stylesheet(tokens))
    return tokens


def follow_system(application: QApplication) -> None:
    def changed(_scheme: Qt.ColorScheme) -> None:
        if preferred_theme() == "system":
            apply_theme(application)

    QGuiApplication.styleHints().colorSchemeChanged.connect(changed)
