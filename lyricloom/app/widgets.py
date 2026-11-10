"""Small custom widgets shared by the player and the karaoke window."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QSlider, QStyle


class SeekSlider(QSlider):
    """A horizontal slider that jumps to the click position.

    QSlider's Fusion style moves by one page step when the groove is clicked. A seek bar is
    expected to jump where the user clicked, so the press, drag and release are handled here.
    """

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)

    def _value_at(self, x: float) -> int:
        span = max(1, self.width())
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), int(max(0, min(span, x))), span, self.invertedAppearance())

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self.maximum() > self.minimum():
            self.setSliderDown(True)
            self.setValue(self._value_at(event.position().x()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.isSliderDown():
            self.setValue(self._value_at(event.position().x()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self.isSliderDown():
            self.setSliderDown(False)
            self.sliderReleased.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)
