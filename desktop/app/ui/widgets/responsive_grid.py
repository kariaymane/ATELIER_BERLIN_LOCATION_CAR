"""
ResponsiveGrid — a card grid that adapts to the width it is actually given.

WHY NOT FlowLayout / QGridLayout
--------------------------------
``FlowLayout`` lays every item out at its own ``sizeHint()`` width and wraps
when the next one no longer fits. That leaves a ragged right edge, and — worse
— a card containing a word-wrapping QLabel reports a very wide sizeHint (the
unwrapped text width), so on a 1366x768 screen the row demanded more width
than the viewport had and the last card was clipped. ``QGridLayout`` fixes the
column count at build time, so the same layout that looks right at 1920 pushes
content off-screen at 1280.

This layout instead:

  * derives the COLUMN COUNT from the width available at paint time
    (``columns = (width + spacing) // (min_item_width + spacing)``, at least 1),
  * gives every column an EQUAL share of that width, so cards stretch to fill
    the row instead of leaving a ragged edge,
  * never reports a minimum width larger than ONE column, so the parent can
    always shrink without forcing a horizontal scrollbar,
  * implements ``heightForWidth`` so a vertical QScrollArea gets the true
    height for the current width and nothing is cut off at the bottom.

There are no absolute coordinates and no fixed pixel positions: the only tuning
knob is ``min_item_width``, the narrowest width at which a card is still
readable.
"""
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QSizePolicy


class ResponsiveGrid(QLayout):
    def __init__(self, parent=None, min_item_width: int = 200,
                 h_spacing: int = 14, v_spacing: int = 14,
                 max_columns: int = 0):
        super().__init__(parent)
        self._items = []
        self._min_item_width = max(1, int(min_item_width))
        self._h = int(h_spacing)
        self._v = int(v_spacing)
        self._max_columns = int(max_columns)   # 0 = unlimited
        self.setContentsMargins(0, 0, 0, 0)

    # ── QLayout plumbing ────────────────────────────────────────────────
    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation.Horizontal

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        """One column wide, so this layout can NEVER be the reason a window
        needs a horizontal scrollbar."""
        h = 0
        for item in self._items:
            h = max(h, item.minimumSize().height())
        left, top, right, bottom = self.getContentsMargins()
        return QSize(self._min_item_width + left + right, h + top + bottom)

    # ── the actual placement ────────────────────────────────────────────
    def columns_for_width(self, width: int) -> int:
        """How many cards fit side by side in ``width`` — at least one."""
        left, _t, right, _b = self.getContentsMargins()
        avail = max(0, width - left - right)
        cols = (avail + self._h) // (self._min_item_width + self._h)
        cols = max(1, int(cols))
        if self._max_columns:
            cols = min(cols, self._max_columns)
        return min(cols, max(1, len(self._items)))

    def _do_layout(self, rect, test_only: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        area = rect.adjusted(left, top, -right, -bottom)
        if not self._items:
            return top + bottom

        cols = self.columns_for_width(rect.width())
        total_spacing = self._h * (cols - 1)
        col_w = max(self._min_item_width, (area.width() - total_spacing) // cols)

        x, y = area.x(), area.y()
        row_height = 0
        col = 0
        for item in self._items:
            w = item.widget()
            if w is not None and w.isHidden():
                continue
            if col == cols:
                x = area.x()
                y += row_height + self._v
                row_height = 0
                col = 0
            h = (item.heightForWidth(col_w) if item.hasHeightForWidth()
                 else item.sizeHint().height())
            h = max(h, item.minimumSize().height())
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), QSize(col_w, h)))
            row_height = max(row_height, h)
            x += col_w + self._h
            col += 1

        return (y + row_height) - rect.y() + bottom


def make_card_size_policy(widget):
    """Cards stretch horizontally and keep their natural height.

    Applied to every card the grid manages so a single card in a wide row
    fills the row instead of hugging the left edge.
    """
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return widget
