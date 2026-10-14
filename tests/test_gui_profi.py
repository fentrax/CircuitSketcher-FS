"""GUI: Werkzeugleiste, Kürzel, Statusleiste, Palette."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtCore import QPointF
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QApplication


def _fresh(mw):
    mw.canvas.scene.clear()
    mw._ensure_decorations()
    mw.undo_stack.clear()
    mw.redo_stack.clear()
    mw.activate_select_mode()
    return mw


def test_redo_menu_action_works(main_window):
    mw = _fresh(main_window)
    comp = mw.create_component("resistor", 200, 200)
    mw.canvas.scene.addItem(comp)
    mw._push_undo_snapshot()
    mw.undo()
    assert not [i for i in mw.canvas.scene.items() if hasattr(i, "symbol_id")]
    mw.redo_action.trigger()          # war früher mit nichts verbunden
    assert [i for i in mw.canvas.scene.items() if hasattr(i, "symbol_id")]


def test_rotate_shortcut_is_r_and_rotates_selection(main_window):
    mw = _fresh(main_window)
    assert mw.rotate_action.shortcut() == QKeySequence("R")
    comp = mw.create_component("resistor", 200, 200)
    mw.canvas.scene.addItem(comp)
    comp.setSelected(True)
    mw.rotate_action.trigger()
    QApplication.processEvents()
    assert comp.rotation_step == 1


def test_rotate_shortcut_rotates_preview_while_placing(main_window):
    mw = _fresh(main_window)
    mw.on_component_selected("resistor")
    mw.preview_component = mw.create_component("resistor", 0, 0)
    mw.canvas.scene.addItem(mw.preview_component)
    mw.rotate_selection_or_preview()
    assert mw.preview_rotation_step == 1
    assert mw.preview_component.rotation_step == 1
    mw._clear_preview()


def test_zoom_label_and_fit(main_window):
    mw = _fresh(main_window)
    mw.canvas.zoom_reset()
    mw.canvas.zoom_in()
    assert mw.zoom_label.text() == "115 %"
    comp = mw.create_component("resistor", 2000, 2000)
    mw.canvas.scene.addItem(comp)
    mw.zoom_to_content()
    visible = mw.canvas.get_visible_scene_rect()
    assert visible.contains(comp.sceneBoundingRect().center())


def test_toolbar_has_icons_and_no_clear_button(main_window):
    from PyQt5.QtWidgets import QPushButton, QToolBar
    mw = main_window
    bar = mw.findChild(QToolBar, "main_toolbar")
    actions = [a for a in bar.actions() if not a.isSeparator() and a.icon() and not a.icon().isNull()]
    assert len(actions) >= 10
    assert all(a.toolTip() for a in actions)
    assert not [b for b in bar.findChildren(QPushButton) if b.text() == "Alles löschen"]


def test_palette_highlights_active_tool_and_has_symbol_icons(main_window):
    mw = _fresh(main_window)
    tb = mw.component_toolbar
    assert tb.button_for("select").isChecked()
    mw.on_component_selected("resistor")
    assert tb.button_for("resistor").isChecked()
    assert not tb.button_for("select").isChecked()
    mw.activate_select_mode()
    assert tb.button_for("select").isChecked()
    assert not tb.button_for("resistor").icon().isNull()


def test_cursor_label_shows_grid_position(main_window):
    mw = _fresh(main_window)
    mw._update_cursor_label(QPointF(40, 60))
    assert "X 2.0" in mw.coord_label.text() and "Y 3.0" in mw.coord_label.text()


def test_fit_ignores_preview_and_hidden_sheet(main_window):
    mw = _fresh(main_window)
    mw._set_sheet_visible(False)
    comp = mw.create_component("resistor", 2000, 2000)
    mw.canvas.scene.addItem(comp)
    mw.on_component_selected("resistor")
    mw.preview_component = mw.create_component("resistor", 0, 0)
    mw.canvas.scene.addItem(mw.preview_component)
    bounds = mw._content_bounds()
    assert bounds.left() > 1500, "Vorschau bei (0,0) darf nicht zum Inhalt zählen"
    mw._clear_preview()
