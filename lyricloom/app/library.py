"""Library table model and filter proxy.

The table is a model/view pair instead of a widget that is rebuilt on every keystroke: the model
owns the rows and their order, the proxy filters them, and a finished track updates one row in
place.

Sorting is done by the model, on the Python list, and never by ``QSortFilterProxyModel``.  The
proxy's own sort asks the model for two sort keys per comparison, each a call from Qt back into
Python; with tens of thousands of songs that is about a million calls for every change of the
search text, which froze the window for seconds per keystroke.
"""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor

from .model import (TrackRow, current_model_ids, other_model_stages, other_models_text)

FILTERS = ["All", "Review", "Pending", "Failed", "Other", "Done", "Made with other models"]
STATUS_LABELS = {"cancelled": "Stopped"}
REVIEW_TINT = QColor(255, 196, 0, 70)
SORT_ROLE = Qt.UserRole + 1
OTHER_MODELS_MARKER = "⇄ other"


class TrackTableModel(QAbstractTableModel):
    """The library rows. `Qt.DisplayRole` is what the view shows; `SORT_ROLE` gives a
    numeric/lexical key so Confidence sorts like a number."""

    COLUMNS = ("Artist", "Title", "Status", "Source", "Conf", "Notes")

    def __init__(self, rows: list[TrackRow] | None = None, parent=None, device_text=None):
        super().__init__(parent)
        self.rows = list(rows or [])
        self._device_text = device_text or (lambda device: device)
        self._current_models: dict[str, set[str]] | None = None
        self._sort_column = -1
        self._sort_order = Qt.AscendingOrder

    def current_models(self) -> dict[str, set[str]]:
        """What the current choices resolve, cached until the choices change."""
        if self._current_models is None:
            self._current_models = current_model_ids()
        return self._current_models

    def invalidate_models(self) -> None:
        """Forgets the cached choices so markers and the filter pick up a new choice."""
        self._current_models = None
        if self.rows:
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(len(self.rows) - 1, self.columnCount() - 1),
                                  [Qt.DisplayRole, Qt.ToolTipRole, SORT_ROLE])
            if self._sort_column == len(self.COLUMNS) - 1:   # the Notes column shows the marker
                self._resort()

    # ---------- cells ----------
    def _cells(self, row: TrackRow) -> tuple[tuple, tuple]:
        """What the six columns show for ``row`` and the keys they sort by."""
        status = STATUS_LABELS.get(row.status, row.status)
        other = other_model_stages(row, self.current_models())
        warning = ("⚠ warning" if row.notes else
                   "⚠ fallback" if row.fallback else ("⚠ error" if row.error else ""))
        notes = " · ".join(part for part in (warning, OTHER_MODELS_MARKER if other else "") if part)
        values = (row.artist, row.title, status, row.source,
                  f"{row.conf:.2f}" if row.source else "", notes)
        keys = (row.artist.lower(), row.title.lower(), status.lower(), row.source.lower(),
                row.conf if row.source else -1.0, notes.lower())
        return values, keys

    # ---------- sorting ----------
    def sort(self, column: int, order=Qt.AscendingOrder) -> None:
        """Orders the rows by a column; a negative column keeps them as they are."""
        self._sort_column = column if 0 <= column < len(self.COLUMNS) else -1
        self._sort_order = order
        self._resort()

    def _sorted(self, rows: list[TrackRow]) -> list[TrackRow]:
        column = self._sort_column
        if column < 0:
            return rows
        return sorted(rows, key=lambda row: self._cells(row)[1][column],
                      reverse=self._sort_order == Qt.DescendingOrder)

    def _resort(self) -> None:
        """Re-orders the rows in place, keeping every selection on its own song."""
        if self._sort_column < 0 or len(self.rows) < 2:
            return
        ordered = self._sorted(self.rows)
        if all(new is old for new, old in zip(ordered, self.rows)):
            return
        self.layoutAboutToBeChanged.emit()
        before = self.persistentIndexList()
        songs = [self.rows[index.row()] for index in before]
        self.rows = ordered
        place = {id(row): i for i, row in enumerate(ordered)}
        after = [self.index(place[id(song)], index.column()) for song, index in zip(songs, before)]
        self.changePersistentIndexList(before, after)
        self.layoutChanged.emit()

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
        if role == Qt.DisplayRole:
            values = self._cells(row)[0]
            return values[column] if 0 <= column < len(values) else None
        if role == SORT_ROLE:
            keys = self._cells(row)[1]
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
            if other_model_stages(row, self.current_models()):
                tips.append(other_models_text(row, self.current_models()))
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
        self.rows = self._sorted(list(rows))
        self.endResetModel()

    def update_row(self, row: TrackRow) -> bool:
        """Replaces one row and emits dataChanged for it only. Returns True when it existed.

        While a column is sorted the row moves to its place when its sort key changed."""
        column = self._sort_column
        for i, old in enumerate(self.rows):
            if old.path == row.path:
                moved = column >= 0 and self._cells(old)[1][column] != self._cells(row)[1][column]
                self.rows[i] = row
                self.dataChanged.emit(self.index(i, 0), self.index(i, self.columnCount() - 1),
                                      [Qt.DisplayRole, Qt.ToolTipRole, Qt.BackgroundRole,
                                       Qt.UserRole, SORT_ROLE])
                if moved:
                    self._resort()
                return True
        self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows))
        self.rows.append(row)
        self.endInsertRows()
        self._resort()
        return False


class TrackFilterProxyModel(QSortFilterProxyModel):
    """Search text and the status filter, applied without rebuilding the model.

    This proxy only filters.  It keeps the source model's order and hands every sort request to
    the source model (see the module text for why)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDynamicSortFilter(True)
        self.setSortRole(SORT_ROLE)
        self._status = "all"
        self._search = ""

    def sort(self, column: int, order=Qt.AscendingOrder) -> None:
        model = self.sourceModel()
        if model is not None:
            model.sort(column, order)

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
        other = False
        if self._status == "made with other models" or self._search:
            current = (model.current_models() if hasattr(model, "current_models")
                       else current_model_ids())
            other = bool(other_model_stages(row, current))
        if self._status == "made with other models":
            if not other:
                return False
        elif self._status != "all" and row.status != self._status:
            return False
        if not self._search:
            return True
        status = STATUS_LABELS.get(row.status, row.status).lower()
        marker = "made with other models" if other else ""
        haystack = f"{row.artist}\n{row.title}\n{status}\n{row.status}\n{marker}".lower()
        return self._search in haystack
