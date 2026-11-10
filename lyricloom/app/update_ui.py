"""The non-modal update notice bar and the scrollable release notes popup."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton,
                               QTextBrowser, QVBoxLayout, QWidget)

from .. import updater


class ReleaseNotesDialog(QDialog):
    """The release body in a scrollable, read-only popup. Links are never followed automatically."""

    def __init__(self, info: updater.UpdateInfo, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"What's new in LyricLoom {info.version}")
        self.resize(680, 520)
        self.setAttribute(Qt.WA_DeleteOnClose)

        layout = QVBoxLayout(self)
        heading = QLabel(f"LyricLoom {info.version}")
        heading.setStyleSheet("font-weight: 600; font-size: 15px;")
        layout.addWidget(heading)

        notes = QTextBrowser()
        notes.setOpenExternalLinks(False)
        notes.setOpenLinks(False)
        notes.setPlainText(info.notes.strip() or "This release did not publish release notes.")
        notes.setAccessibleName("Release notes")
        layout.addWidget(notes, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        open_button = buttons.addButton("Open release page", QDialogButtonBox.ActionRole)
        open_button.clicked.connect(lambda: updater.open_release_page(info))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class UpdateBar(QWidget):
    """A banner above the main window: what is new, the mode's action, Later and Skip.

    The bar owns the two browser actions it offers. "What's new" opens the validated release page
    in the browser and shows the release body in the popup; the Linux tarball link opens only the
    release asset the updater accepted. Clicking anything else never opens a browser.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("updateBar")
        self.setAccessibleName("Update available")
        self.info: updater.UpdateInfo | None = None
        self._notes: ReleaseNotesDialog | None = None
        self._on_action = None
        self._on_later = None
        self._on_skip = None

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 7, 10, 7)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setStyleSheet("font-weight: 600;")
        self.btn_whats_new = QPushButton("What's new")
        self.btn_whats_new.setToolTip("Open the GitHub release page and show the release notes")
        self.btn_tarball = QPushButton("Download for Linux")
        self.btn_tarball.setToolTip("Open the release tarball download in your browser")
        self.btn_action = QPushButton()
        self.btn_later = QPushButton("Later")
        self.btn_skip = QPushButton("Skip this version")
        for widget in (self.btn_whats_new, self.btn_tarball, self.btn_action, self.btn_later,
                       self.btn_skip):
            row.addWidget(widget)
        row.insertWidget(0, self.label, 1)

        self.btn_whats_new.clicked.connect(self._whats_new)
        self.btn_tarball.clicked.connect(self._open_tarball)
        self.btn_action.clicked.connect(self._action)
        self.btn_later.clicked.connect(self._later)
        self.btn_skip.clicked.connect(self._skip)
        self.hide()

    def show_update(self, info: updater.UpdateInfo, *, action_text: str | None = None,
                    show_tarball: bool = False, on_action=None, on_later=None, on_skip=None) -> None:
        """Shows the banner for ``info``; ``action_text`` is None when this mode has no action."""
        self.info = info
        self._on_action, self._on_later, self._on_skip = on_action, on_later, on_skip
        self.label.setText(f"LyricLoom {info.version} is available")
        self.btn_action.setText(action_text or "")
        self.btn_action.setVisible(bool(action_text))
        self.btn_tarball.setVisible(bool(show_tarball and info.tarball_url))
        self.show()

    def _whats_new(self) -> None:
        if self.info is None:
            return
        updater.open_release_page(self.info)
        self._notes = ReleaseNotesDialog(self.info, self.window())
        self._notes.show()

    def _open_tarball(self) -> None:
        if self.info is not None:
            updater.open_tarball_page(self.info)

    def _action(self) -> None:
        if self._on_action is not None:
            self._on_action()

    def _later(self) -> None:
        self.hide()
        if self._on_later is not None:
            self._on_later()

    def _skip(self) -> None:
        self.hide()
        if self._on_skip is not None:
            self._on_skip()
