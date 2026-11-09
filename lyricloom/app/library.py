"""Library table model and filter proxy.

The table is a model/view pair instead of a widget that is rebuilt on every keystroke: the model
owns the rows, the proxy filters them, and a finished track updates one row in place.
"""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor

from .model import TrackRow

FILTERS = ["All", "Review", "Pending", "Failed", "Other", "Done"]
STATUS_LABELS = {"cancelled": "Stopped"}
REVIEW_TINT = QColor(255, 196, 0, 70)
SORT_ROLE = Qt.UserRole + 1


class TrackTableModel(QAbstractTableModel):
    """The library rows. `Qt.DisplayRole` is what the view shows; `SORT_ROLE` gives a
    numeric/lexical key so Confidence sorts like a number."""

    COLUMNS = ("Artist", "Title", "Status", "Source", "Conf", "Notes")

    def __init__(self, rows: list[TrackRow] | None = None, parent=None, device_text=None):
        super().__init__(parent)
        self.rows = list(rows or [])
        self._device_text = device_text or (lambda device: device)

    # ---------- QAbstractTableModel ----------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section: int, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole and 0 <= section < len(self.COLUMNS):
            return self.COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.rows)):
            return None
        row = self.rows[index.row()]
        column = index.column()
        status = STATUS_LABELS.get(row.status, row.status)
        notes = ("⚠ warning" if row.notes else
                 "⚠ fallback" if row.fallback else ("⚠ error" if row.error else ""))
        values = (row.artist, row.title, status, row.source,
                  f"{row.conf:.2f}" if row.source else "", notes)
        keys = (row.artist.lower(), row.title.lower(), status.lower(), row.source.lower(),
                row.conf if row.source else -1.0, notes.lower())
        if role == Qt.DisplayRole:
            return values[column] if 0 <= column < len(values) else None
        if role == SORT_ROLE:
            return keys[column] if 0 <= column < len(keys) else ""
        if role == Qt.UserRole:
            return str(row.path)
        if role == Qt.BackgroundRole and row.status == "review":
            return REVIEW_TINT
        if role == Qt.TextAlignmentRole and column == 4:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ToolTipRole:
            tips = []
            if row.error:
                tips.append("Error:\n" + row.error)
            if row.notes:
                tips.append("Warnings:\n" + "\n".join(row.notes))
            if row.fallback:
                tips.append("Fallback:\n" + row.fallback)
            if row.device:
                tips.append("Device: " + self._device_text(row.device))
            if row.log_path:
                tips.append("Log: " + row.log_path)
            return "\n\n".join(tips) if tips else None
        return None

    def flags(self, index: QModelIndex):
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled if index.isValid() else Qt.NoItemFlags

    # ---------- the app's row operations ----------
    def row_at(self, index: int) -> TrackRow:
        return self.rows[index]

    def row_for_path(self, path) -> int:
        wanted = str(path)
        for i, row in enumerate(self.rows):
            if str(row.path) == wanted:
                return i
        return -1

    def set_rows(self, rows: list[TrackRow]) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def update_row(self, row: TrackRow) -> bool:
        """Replaces one row and emits dataChanged for it only. Returns True when it existed."""
        for i, old in enumerate(self.rows):
            if old.path == row.path:
                self.rows[i] = row
                self.dataChanged.emit(self.index(i, 0), self.index(i, self.columnCount() - 1),
                                      [Qt.DisplayRole, Qt.ToolTipRole, Qt.BackgroundRole,
                                       Qt.UserRole, SORT_ROLE])
                return True
        self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows))
        self.rows.append(row)
        self.endInsertRows()
        return False


class TrackFilterProxyModel(QSortFilterProxyModel):
    """Search text and the status filter, applied without rebuilding the model."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDynamicSortFilter(True)
        self.setSortRole(SORT_ROLE)
        self._status = "all"
        self._search = ""

    def _invalidate(self) -> None:
        self.invalidate()

    def set_status_filter(self, status: str) -> None:
        status = status.lower()
        if status != self._status:
            self._status = status
            self._invalidate()

    def set_search_text(self, text: str) -> None:
        text = text.strip().lower()
        if text != self._search:
            self._search = text
            self._invalidate()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if model is None:
            return False
        row = model.row_at(source_row)
        if self._status != "all" and row.status != self._status:
            return False
        if not self._search:
            return True
        status = STATUS_LABELS.get(row.status, row.status).lower()
        haystack = f"{row.artist}\n{row.title}\n{status}\n{row.status}".lower()
        return self._search in haystack
