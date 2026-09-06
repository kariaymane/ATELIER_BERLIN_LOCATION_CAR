"""
Dashboard responsiveness — the layout half of the rebuild.

The reported screenshot showed the sidebar clipped and header/cards cut off.
Root cause was a 1200x750 window floor combined with rows laid out at each
card's own ``sizeHint()`` width. These tests pin the fix at the four target
resolutions and would fail again if either regression returned.

Everything runs offscreen; the assertions are about geometry, not pixels.
"""
import os
import sys

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("CAR_RENTAL_DB_RESET", "1")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from app.ui.dashboard import DashboardWidget  # noqa: E402
from app.ui.widgets.responsive_grid import ResponsiveGrid  # noqa: E402

# The resolutions the dashboard must be usable at. Heights are the raw screen
# heights; the real window is shorter still once the OS panel is subtracted,
# which is exactly what the old 750px floor could not satisfy.
RESOLUTIONS = [(1280, 720), (1366, 768), (1600, 900), (1920, 1080)]

# A narrow window is not a target resolution, but nothing may break there.
EXTREME = [(1024, 600), (900, 560)]


def _dto():
    try:
        from tests.test_dashboard_rebuild import make_dto
    except ImportError:
        from desktop.tests.test_dashboard_rebuild import make_dto
    return make_dto()


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _cards(w):
    return [w._card_day, w._card_maintenance, w._card_available,
            w._card_rented, w._card_fleet_maintenance]


def _laid_out(qapp, width, height):
    w = DashboardWidget()
    w.apply_snapshot(_dto())
    w.resize(width, height)
    w.show()
    qapp.processEvents()
    w._scroll.widget().adjustSize()
    qapp.processEvents()
    return w


# ── the grid maths, in isolation ─────────────────────────────────────────


@pytest.mark.parametrize("width,expected", [
    (200, 1), (399, 1), (414, 2), (628, 3), (842, 4), (2000, 4),
])
def test_grid_column_count_follows_available_width(qapp, width, expected):
    """4 items, min 200px, 14px gutters -> the count is derived, never fixed."""
    host = QWidget()
    grid = ResponsiveGrid(min_item_width=200, h_spacing=14, v_spacing=14)
    host.setLayout(grid)
    for _ in range(4):
        grid.addWidget(QWidget())
    assert grid.columns_for_width(width) == expected


def test_grid_never_demands_more_than_one_column_of_width(qapp):
    """The minimum width is what decides whether the parent is forced wider
    than the screen; it must stay at one column."""
    host = QWidget()
    grid = ResponsiveGrid(min_item_width=190)
    host.setLayout(grid)
    for _ in range(6):
        grid.addWidget(QWidget())
    assert grid.minimumSize().width() == 190


def test_grid_stretches_cards_to_fill_the_row(qapp):
    host = QWidget()
    grid = ResponsiveGrid(min_item_width=100, h_spacing=10, v_spacing=10)
    host.setLayout(grid)
    kids = [QWidget() for _ in range(3)]
    for k in kids:
        grid.addWidget(k)
    host.resize(640, 200)
    host.show()
    qapp.processEvents()
    widths = {k.width() for k in kids}
    assert len(widths) == 1, "cards in a row must share the width equally"
    used = sum(k.width() for k in kids) + 2 * 10
    assert 640 - used <= 3, "cards must fill the row, not leave a ragged edge"


# ── the dashboard at each target resolution ──────────────────────────────


@pytest.mark.parametrize("width,height", RESOLUTIONS + EXTREME)
def test_no_horizontal_overflow(qapp, width, height):
    w = _laid_out(qapp, width, height)
    bar = w._scroll.horizontalScrollBar()
    assert bar.maximum() == 0, (
        f"{width}x{height}: content is wider than the viewport "
        f"(overflow {bar.maximum()}px)"
    )
    assert w._scroll.widget().width() <= w._scroll.viewport().width() + 1
    w.close()


@pytest.mark.parametrize("width,height", RESOLUTIONS + EXTREME)
def test_every_card_is_fully_inside_the_viewport(qapp, width, height):
    w = _laid_out(qapp, width, height)
    content = w._scroll.widget()
    for card in _cards(w) + [w._revenue_panel, w._top_box]:
        origin = card.mapTo(content, QPoint(0, 0))
        assert origin.x() >= 0, f"{width}x{height}: {card} starts off the left edge"
        assert origin.x() + card.width() <= content.width() + 1, (
            f"{width}x{height}: {card} is clipped on the right "
            f"({origin.x() + card.width()} > {content.width()})"
        )
        assert card.width() > 0 and card.height() > 0
    w.close()


@pytest.mark.parametrize("width,height", RESOLUTIONS)
def test_all_six_cards_and_the_top5_stay_present(qapp, width, height):
    """Responsiveness must never be achieved by hiding a card."""
    w = _laid_out(qapp, width, height)
    for card in _cards(w):
        assert card.isHidden() is False
    assert w._top_box.isHidden() is False
    assert w._revenue_panel.isHidden() is False
    w.close()


@pytest.mark.parametrize("width,height", RESOLUTIONS)
def test_card_text_is_not_truncated_at_target_resolutions(qapp, width, height):
    """Elision is the safety net for extreme widths, not the normal state:
    at every supported resolution the titles and values render in full."""
    w = _laid_out(qapp, width, height)
    for card in _cards(w):
        assert "…" not in card._title_lbl.text(), f"{width}x{height}: title elided"
        assert "…" not in card._count_lbl.text(), f"{width}x{height}: value elided"
    w.close()


def test_cards_wrap_instead_of_being_clipped_when_space_runs_out(qapp):
    """The layout genuinely reflows: one row while it fits, several rows when
    it does not — and never a card pushed off the edge."""
    wide = _laid_out(qapp, 1920, 1080)
    rows = {c.mapTo(wide._scroll.widget(), QPoint(0, 0)).y()
            for c in (wide._card_available, wide._card_rented,
                      wide._card_fleet_maintenance)}
    assert len(rows) == 1, "the three fleet cards must share one row on a wide screen"
    wide.close()

    narrow = _laid_out(qapp, 500, 600)
    content = narrow._scroll.widget()
    ys = {c.mapTo(content, QPoint(0, 0)).y()
          for c in (narrow._card_available, narrow._card_rented,
                    narrow._card_fleet_maintenance)}
    assert len(ys) > 1, "the cards must wrap onto more rows when width runs out"
    for c in (narrow._card_available, narrow._card_rented,
              narrow._card_fleet_maintenance):
        origin = c.mapTo(content, QPoint(0, 0))
        assert origin.x() + c.width() <= content.width() + 1
    assert narrow._scroll.horizontalScrollBar().maximum() == 0
    narrow.close()


def test_dashboard_minimum_width_fits_a_small_shell(qapp):
    """The page must never be the reason the window cannot shrink."""
    w = DashboardWidget()
    assert w.minimumSizeHint().width() <= 420
    assert w.minimumWidth() <= 420
    w.close()


def test_top5_bar_has_no_hard_coded_pixel_width(qapp):
    """The old bar was ``setFixedWidth(180 * pct)`` — an absolute size that
    overflowed narrow rows. It must now be layout-driven."""
    w = _laid_out(qapp, 1024, 600)
    row = w._top_layout.itemAt(0).widget()
    from app.ui.dashboard import RankBar
    bars = row.findChildren(RankBar)
    assert bars, "the Top-5 row must use the responsive RankBar"
    assert bars[0].maximumWidth() > 1000, "the bar must be free to stretch"
    w.close()


# ── the shell (sidebar + content + header) ───────────────────────────────


def test_sidebar_can_shrink_and_scrolls(qapp):
    from app.ui.widgets.sidebar import Sidebar
    s = Sidebar(user_role="ADMIN")
    assert s.minimumWidth() <= 200, "a fixed-width rail cannot yield to a small screen"
    assert s.maximumWidth() >= 200
    assert s._scroll.widgetResizable() is True
    s.resize(s.minimumWidth(), 420)
    s.show()
    qapp.processEvents()
    # Every navigation entry still exists (never hidden to "fit")
    assert len(s._buttons) == 6
    for btn in s._buttons.values():
        assert btn.isHidden() is False
    s.close()


@pytest.mark.parametrize("width,height", RESOLUTIONS + EXTREME)
def test_main_window_shell_fits_without_overlap(qapp, width, height):
    from app.ui.main_window import MainWindow
    win = MainWindow({
        "id": "u", "user_id": "u", "access_token": "", "refresh_token": "",
        "full_name": "Test Admin", "role": "ADMIN", "offline": True,
    })
    win._is_online = False
    win.resize(width, height)
    win.show()
    qapp.processEvents()

    # The window floor must not exceed any supported screen.
    assert win.minimumWidth() <= 1024
    assert win.minimumHeight() <= 600

    sidebar = win._sidebar
    stack = win._stack
    s_right = sidebar.mapTo(win, QPoint(0, 0)).x() + sidebar.width()
    c_left = stack.mapTo(win, QPoint(0, 0)).x()
    assert c_left >= s_right - 1, (
        f"{width}x{height}: sidebar (ends {s_right}) overlaps content (starts {c_left})"
    )
    assert c_left + stack.width() <= win.width() + 1, (
        f"{width}x{height}: content overflows the window horizontally"
    )
    assert sidebar.width() > 0 and stack.width() > 0

    # Header controls all present and inside the window.
    for ctl in (win._global_search, win._refresh_btn, win._user_btn):
        assert ctl.isHidden() is False
        x = ctl.mapTo(win, QPoint(0, 0)).x()
        assert x >= 0 and x + ctl.width() <= win.width() + 1, (
            f"{width}x{height}: header control cut off"
        )

    win.close()
    win.deleteLater()
    qapp.processEvents()
