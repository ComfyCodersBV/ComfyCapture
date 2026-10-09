from __future__ import annotations

from html import escape

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QDesktopServices

from comfycapture.core import ir

TICKET_URL_KEY = "tickets/url"
TICKET_PLACEHOLDER = "{ticket}"


def build_ticket_url(pattern: str, tag: str) -> str | None:
    pattern = pattern.strip()
    if not pattern or not ir.is_ticket_tag(tag):
        return None
    if TICKET_PLACEHOLDER in pattern:
        return pattern.replace(TICKET_PLACEHOLDER, tag)
    return pattern + tag


def ticket_url(tag: str) -> str | None:
    return build_ticket_url(QSettings().value(TICKET_URL_KEY, "", str), tag)


def ticket_links(tags: tuple[str, ...] | list[str]) -> dict[str, str]:
    links = {tag: ticket_url(tag) for tag in tags}
    return {tag: url for tag, url in links.items() if url}


def links_html(tags: tuple[str, ...] | list[str]) -> str:
    return "  ".join(
        f'<a href="{escape(url, quote=True)}">🎫 {escape(tag)}</a>' for tag, url in ticket_links(tags).items()
    )


def open_ticket(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))
