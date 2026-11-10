"""Per-track details: the last queue result plus the exact log file, in one copyable place."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

if TYPE_CHECKING:
    from .model import TrackRow


def details_text(row: "TrackRow", device_label: str = "") -> str:
    """Everything the last run recorded for one row; safe to paste into a bug report."""
    lines = [
        f"Track: {row.path}",
        f"Artist: {row.artist or '(unknown)'}",
        f"Title: {row.title or row.path.stem}",
        f"Status: {row.status}",
        f"Source: {row.source or '(none)'}",
        f"Confidence: {row.conf:.2f}" if row.source else "Confidence: (not available)",
        f"Device: {device_label or row.device or '(not recorded)'}",
        f"Fallback: {row.fallback or '(none)'}",
        f"Error: {row.error or '(none)'}",
        f"Log: {row.log_path or '(not recorded yet)'}",
    ]
    if row.review_lines:
        lines.append("Lines to review: " + ", ".join(str(i + 1) for i in row.review_lines))
    return "\n".join(lines)


class TrackDetailsDialog(QDialog):
    def __init__(self, text: str, log_path: Path | None, parent: QWidget | None = None):
        super().__init__(parent)
        self._log_path = log_path
        self.setWindowTitle("Track details")
        self.setMinimumSize(680, 420)
        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlainText(text)
        layout.addWidget(self.text, 1)
        note = QLabel("This is the last result for the track. Refresh keeps it until the track is processed again.")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QHBoxLayout()
        copy = QPushButton("Copy")
        copy.clicked.connect(self._copy)
        self.open_log = QPushButton("Open log")
        self.open_log.setEnabled(log_path is not None)
        self.open_log.clicked.connect(self._open_log)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(copy)
        buttons.addWidget(self.open_log)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.text.toPlainText())
        QMessageBox.information(self, "Track details", "Details copied to the clipboard.")

    def _open_log(self) -> None:
        if self._log_path is None or not self._log_path.is_file():
            QMessageBox.information(self, "Track details", "There is no log for this track yet.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._log_path)))
