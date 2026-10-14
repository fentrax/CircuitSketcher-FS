"""Automatische Betriebsmittel-Kennzeichnung und Punktraster."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtWidgets import QApplication


class _Click:
    """Minimales Szenen-Mausereignis für canvas_mouse_press."""
    def __init__(self, x, y, button=Qt.LeftButton):
        self._pos = QPointF(x, y)
        self._button = button
        self._accepted = False

    def button(self):
        return self._button

    def buttons(self):
        return self._button

    def scenePos(self):
        return self._pos

    def modifiers(self):
        return Qt.NoModifier

    def accept(self):
        self._accepted = True

    def ignore(self):
        self._accepted = False

    def isAccepted(self):
        return self._accepted


def _fresh(mw):
    mw.canvas.scene.clear()
    mw._ensure_decorations()
    mw.undo_stack.clear()
    mw.redo_stack.clear()
    mw.auto_numbering = True
    mw.activate_select_mode()
    return mw


def _place(mw, symbol_id, x, y):
    mw.on_component_selected(symbol_id)
    mw.canvas_mouse_press(_Click(x, y))
    QApplication.processEvents()


def _names(mw, symbol_id=None):
    from src.components.symbol_component import SymbolComponent
    return sorted(c.placeholder_values.get("name", "") for c in mw.canvas.scene.items()
                  if isinstance(c, SymbolComponent) and c is not mw.preview_component
                  and (symbol_id is None or c.symbol_id == symbol_id))


def test_placing_numbers_per_prefix(main_window):
    mw = _fresh(main_window)
    _place(mw, "resistor", 100, 100)
    _place(mw, "resistor", 300, 100)
    _place(mw, "capacitor", 500, 100)
    _place(mw, "resistor", 700, 100)
    assert _names(mw, "resistor") == ["R1", "R2", "R3"]
    assert _names(mw, "capacitor") == ["C1"]


def test_gap_is_reused_after_delete(main_window):
    from src.components.symbol_component import SymbolComponent
    mw = _fresh(main_window)
    for x in (100, 300, 500):
        _place(mw, "resistor", x, 100)
    mw.activate_select_mode()
    r2 = next(c for c in mw.canvas.scene.items()
              if isinstance(c, SymbolComponent) and c.placeholder_values["name"] == "R2")
    r2.setSelected(True)
    mw.delete_selected()
    _place(mw, "resistor", 700, 100)
    assert _names(mw, "resistor") == ["R1", "R2", "R3"]


def test_ground_keeps_fixed_name(main_window):
    mw = _fresh(main_window)
    _place(mw, "ground", 100, 100)
    _place(mw, "ground", 300, 100)
    assert _names(mw, "ground") == ["PE", "PE"]


def test_custom_name_not_counted_and_kept(main_window):
    mw = _fresh(main_window)
    _place(mw, "resistor", 100, 100)
    mw.activate_select_mode()
    only = next(c for c in mw.canvas.scene.items() if getattr(c, "symbol_id", "") == "resistor")
    only.set_placeholder_value("name", "Rv")
    _place(mw, "resistor", 300, 100)
    assert _names(mw, "resistor") == ["R1", "Rv"]


def test_paste_and_duplicate_get_unique_names(main_window):
    mw = _fresh(main_window)
    _place(mw, "resistor", 100, 100)
    mw.activate_select_mode()
    original = next(c for c in mw.canvas.scene.items() if getattr(c, "symbol_id", "") == "resistor")
    original.setSelected(True)
    mw.duplicate_selection()
    mw.duplicate_selection()
    assert _names(mw, "resistor") == ["R1", "R2", "R3"]


def test_auto_numbering_can_be_switched_off(main_window):
    mw = _fresh(main_window)
    mw.auto_numbering = False
    _place(mw, "resistor", 100, 100)
    assert _names(mw, "resistor") == ["R"]


def test_preview_shows_next_designator(main_window):
    mw = _fresh(main_window)
    _place(mw, "resistor", 100, 100)
    mw.on_component_selected("resistor")

    class _Move(_Click):
        pass
    mw.canvas_mouse_move(_Move(400, 400))
    assert mw.preview_component.placeholder_values["name"] == "R2"
    mw._clear_preview()


def test_renumber_all_in_reading_order(main_window):
    mw = _fresh(main_window)
    mw.auto_numbering = False
    for x, y in ((500, 100), (100, 400), (100, 100), (300, 100)):
        _place(mw, "resistor", x, y)
    mw.activate_select_mode()
    mw.renumber_all()
    from src.components.symbol_component import SymbolComponent
    by_pos = {(round(c.x()), round(c.y())): c.placeholder_values["name"]
              for c in mw.canvas.scene.items() if isinstance(c, SymbolComponent)}
    assert by_pos[(100, 100)] == "R1"
    assert by_pos[(300, 100)] == "R2"
    assert by_pos[(500, 100)] == "R3"
    assert by_pos[(100, 400)] == "R4"
    mw.undo()
    assert sorted(_names(mw)) == ["R", "R", "R", "R"]


def test_main_canvas_uses_dot_grid(main_window):
    assert main_window.canvas.grid_style == "dots"


@pytest.mark.parametrize("zoom", [1.0, 0.3, 0.1])
def test_dot_grid_draws_dots_thinned_when_zoomed_out(main_window, zoom):
    from PyQt5.QtCore import QRectF
    from PyQt5.QtGui import QImage, QPainter, QColor
    canvas = main_window.canvas
    canvas.set_grid_style("dots")
    img = QImage(400, 300, QImage.Format_ARGB32)
    img.fill(QColor("white"))
    painter = QPainter(img)
    painter.scale(zoom, zoom)
    rect = QRectF(0, 0, 400 / zoom, 300 / zoom)
    calls = []
    original = painter.drawPoints

    class _Spy:
        def __getattr__(self, name):
            return getattr(painter, name)

        def drawPoints(self, points):
            calls.append(points.count())
            original(points)
    canvas._draw_dot_grid(_Spy(), rect)
    painter.end()
    total = sum(calls)
    assert total > 0
    # Nie mehr Punkte als bei 7 px Bildschirmabstand möglich
    assert total <= (400 / 7 + 2) * (300 / 7 + 2) + 1
    # Es sind wirklich Punkte gezeichnet (keine durchgehenden Linien)
    row = [QColor(img.pixel(x, 150)).lightness() for x in range(400)]
    assert sum(1 for v in row if v < 250) < 200


def test_lines_style_still_available(main_window):
    mw = main_window
    mw.dot_grid_action.setChecked(False)
    assert mw.canvas.grid_style == "lines"
    mw.dot_grid_action.setChecked(True)
    assert mw.canvas.grid_style == "dots"


# Kennbuchstaben nach DIN EN 81346-2 (Hauptklassen)
IEC_81346_LETTERS = {
    "battery": "G",        # Erzeugen eines Energieflusses
    "resistor": "R",       # Begrenzen
    "diode": "R",          # Begrenzen
    "inductor": "R",       # Begrenzen (Drosselspule)
    "capacitor": "C",      # Speichern
    "fuse": "F",           # Schützen
    "lamp": "E",           # Licht/Wärme bereitstellen
    "led": "P",            # Information darstellen (Signallampe/LED)
    "ammeter": "P",        # Information darstellen (Messgerät)
    "voltmeter": "P",
    "motor": "M",          # Mechanische Energie bereitstellen
    "switch": "S",         # Manuelle Betätigung in Signal umsetzen
    "switch_normally_open": "S",
    "switch_normally_closed": "S",
    "pushbutton_normally_open": "S",
    "pushbutton_normally_closed": "S",
}


@pytest.mark.parametrize("symbol_id,letter", sorted(IEC_81346_LETTERS.items()))
def test_default_letters_follow_iec_81346_2(main_window, symbol_id, letter):
    definition = main_window.symbol_definitions[symbol_id]
    assert definition.default_values.get("name") == letter


def test_same_class_shares_one_counter(main_window):
    """R-Klasse: Widerstand, Diode und Spule zählen gemeinsam (R1, R2, R3)."""
    mw = _fresh(main_window)
    _place(mw, "resistor", 100, 100)
    _place(mw, "diode", 300, 100)
    _place(mw, "inductor", 500, 100)
    _place(mw, "voltmeter", 100, 300)
    _place(mw, "ammeter", 300, 300)
    assert _names(mw, "resistor") == ["R1"]
    assert _names(mw, "diode") == ["R2"]
    assert _names(mw, "inductor") == ["R3"]
    assert sorted(_names(mw, "voltmeter") + _names(mw, "ammeter")) == ["P1", "P2"]


def test_old_drawings_keep_their_names(main_window, tmp_path):
    """Bestehende Dateien mit alten Kennzeichen (A1, H1) bleiben unverändert."""
    import json
    mw = _fresh(main_window)
    comp = mw.create_component("ammeter", 100, 100)
    mw.canvas.scene.addItem(comp)
    comp.set_placeholder_value("name", "A1")
    target = tmp_path / "alt.sz.json"
    mw._save_to(target)
    mw.canvas.scene.clear()
    mw._ensure_decorations()
    mw.load_circuit(str(target))
    assert _names(mw, "ammeter") == ["A1"]
    assert json.loads(target.read_text(encoding="utf-8"))["components"][0]["placeholder_values"]["name"] == "A1"
