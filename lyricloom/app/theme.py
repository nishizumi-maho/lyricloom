"""Fusion style and a palette that follows the system light/dark colour scheme."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def _scheme(app: QApplication) -> str:
    hints = app.styleHints()
    scheme = hints.colorScheme() if hasattr(hints, "colorScheme") else Qt.ColorScheme.Unknown
    if scheme == Qt.ColorScheme.Dark:
        return "dark"
    if scheme == Qt.ColorScheme.Light:
        return "light"
    # Qt cannot see the Windows theme (offscreen, some Linux desktops): use the current palette.
    return "dark" if app.palette().color(QPalette.Window).lightness() < 128 else "light"


def _dark_palette(app: QApplication) -> QPalette:
    p = app.style().standardPalette()
    window = QColor("#23262e")
    base = QColor("#1b1d23")
    text = QColor("#e8ecf3")
    disabled = QColor("#8b919d")
    p.setColor(QPalette.Window, window)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, QColor("#272a33"))
    p.setColor(QPalette.ToolTipBase, QColor("#2d313b"))
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, QColor("#2b2f38"))
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.BrightText, QColor("#ff7b7b"))
    p.setColor(QPalette.Link, QColor("#79b8ff"))
    p.setColor(QPalette.Highlight, QColor("#2f6feb"))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.PlaceholderText, QColor("#9aa1ad"))
    p.setColor(QPalette.Light, QColor("#3a3f4a"))
    p.setColor(QPalette.Midlight, QColor("#31353f"))
    p.setColor(QPalette.Mid, QColor("#2a2e37"))
    p.setColor(QPalette.Dark, QColor("#171920"))
    p.setColor(QPalette.Shadow, QColor("#0f1116"))
    p.setColor(QPalette.Disabled, QPalette.Text, disabled)
    p.setColor(QPalette.Disabled, QPalette.WindowText, disabled)
    p.setColor(QPalette.Disabled, QPalette.ButtonText, disabled)
    p.setColor(QPalette.Disabled, QPalette.Highlight, QColor("#3a3f4a"))
    p.setColor(QPalette.Disabled, QPalette.HighlightedText, disabled)
    return p


def _light_palette(app: QApplication) -> QPalette:
    p = app.style().standardPalette()
    p.setColor(QPalette.Window, QColor("#f4f5f7"))
    p.setColor(QPalette.Base, QColor("#ffffff"))
    p.setColor(QPalette.AlternateBase, QColor("#f7f8fa"))
    p.setColor(QPalette.Text, QColor("#1d2128"))
    p.setColor(QPalette.WindowText, QColor("#1d2128"))
    p.setColor(QPalette.ButtonText, QColor("#1d2128"))
    p.setColor(QPalette.Link, QColor("#1e63c8"))
    p.setColor(QPalette.Highlight, QColor("#2f6feb"))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.PlaceholderText, QColor("#707784"))
    p.setColor(QPalette.Light, QColor("#ffffff"))
    p.setColor(QPalette.Midlight, QColor("#e9ebef"))
    p.setColor(QPalette.Mid, QColor("#c9cdd4"))
    p.setColor(QPalette.Dark, QColor("#9aa0a8"))
    p.setColor(QPalette.Shadow, QColor("#6f757d"))
    return p


def apply_theme(app: QApplication | None = None, scheme: str | None = None) -> str:
    """Sets the Fusion style and the palette for `scheme` ("light"/"dark").

    `None` follows the system setting. Returns the scheme that was applied. The window follows a
    live Windows theme change because `colorSchemeChanged` re-applies the palette.
    """
    app = app if app is not None else QApplication.instance()
    if app is None:
        return "light"
    app.setStyle("Fusion")
    chosen = scheme or _scheme(app)
    app.setPalette(_dark_palette(app) if chosen == "dark" else _light_palette(app))
    app.setProperty("lyricloom_theme", chosen)
    if not getattr(app, "_lyricloom_theme_watch", False):
        app._lyricloom_theme_watch = True
        hints = app.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda _scheme: apply_theme(app))
    return chosen
