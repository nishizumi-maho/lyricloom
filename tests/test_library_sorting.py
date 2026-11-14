"""Sorting lives in the table model, so a search never re-sorts the library through Qt."""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QTableView  # noqa: E402

from lyricloom.app.library import SORT_ROLE, TrackFilterProxyModel, TrackTableModel  # noqa: E402
from lyricloom.app.model import TrackRow  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def _row(name: str, artist: str, title: str, status: str = "done", conf: float = 0.5,
         source: str = "lrclib") -> TrackRow:
    return TrackRow(Path(f"C:/music/{name}.flac"), artist, title, status, source, conf)


def _pair(rows):
    _app()
    model = TrackTableModel(rows)
    model._current_models = {}
    proxy = TrackFilterProxyModel()
    proxy.setSourceModel(model)
    return model, proxy


def _titles(proxy) -> list[str]:
    return [proxy.index(i, 1).data() for i in range(proxy.rowCount())]


def test_sorting_through_the_proxy_orders_the_rows():
    _model, proxy = _pair([_row("a", "Zed", "banana", conf=0.2), _row("b", "amy", "Cherry", conf=0.9),
                           _row("c", "Bob", "apple", conf=0.5)])
    proxy.sort(1, Qt.AscendingOrder)
    assert _titles(proxy) == ["apple", "banana", "Cherry"]       # case-insensitive
    proxy.sort(1, Qt.DescendingOrder)
    assert _titles(proxy) == ["Cherry", "banana", "apple"]
    proxy.sort(4, Qt.DescendingOrder)                            # confidence sorts as a number
    assert _titles(proxy) == ["Cherry", "apple", "banana"]


def test_a_search_does_not_ask_the_model_for_sort_keys():
    _app()
    asked = []

    class Counting(TrackTableModel):
        def data(self, index, role=Qt.DisplayRole):
            if role == SORT_ROLE:
                asked.append(index.row())
            return super().data(index, role)

    model = Counting([_row(str(i), f"artist {i % 7}", f"title {i}") for i in range(400)])
    model._current_models = {}
    proxy = TrackFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.sort(1, Qt.AscendingOrder)
    asked.clear()
    proxy.set_search_text("title 1")
    proxy.set_search_text("")
    assert proxy.rowCount() == 400
    assert asked == []


def test_search_keeps_the_sort_order():
    _model, proxy = _pair([_row("a", "x", "night b"), _row("b", "x", "day"), _row("c", "x", "night a")])
    proxy.sort(1, Qt.AscendingOrder)
    proxy.set_search_text("night")
    assert _titles(proxy) == ["night a", "night b"]


def test_an_updated_row_moves_to_its_sorted_place():
    model, proxy = _pair([_row("a", "x", "alpha"), _row("b", "x", "beta"), _row("c", "x", "gamma")])
    proxy.sort(1, Qt.AscendingOrder)
    model.update_row(_row("a", "x", "zeta"))
    assert _titles(proxy) == ["beta", "gamma", "zeta"]
    model.update_row(_row("d", "x", "delta"))                     # a new song is placed, not appended
    assert _titles(proxy) == ["beta", "delta", "gamma", "zeta"]


def test_sorting_keeps_the_selected_song_selected():
    _model, proxy = _pair([_row("a", "x", "banana"), _row("b", "x", "cherry"), _row("c", "x", "apple")])
    view = QTableView()
    view.setModel(proxy)
    view.setSortingEnabled(True)
    view.sortByColumn(1, Qt.AscendingOrder)
    row = _titles(proxy).index("cherry")
    view.selectionModel().select(proxy.index(row, 0),
                                 QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
    view.sortByColumn(1, Qt.DescendingOrder)
    selected = view.selectionModel().selectedRows(1)
    assert [index.data() for index in selected] == ["cherry"]
    assert _titles(proxy) == ["cherry", "banana", "apple"]
