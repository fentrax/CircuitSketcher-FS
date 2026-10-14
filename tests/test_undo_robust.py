"""Undo/Redo bleibt konsistent, egal ob eine Aktion ihren Snapshot vor oder
nach der Änderung ablegt; Kontextmenü-Aktionen sind undo-fähig."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtWidgets import QApplication


def _state(mw):
    from src.components.symbol_component import SymbolComponent
    return sorted((c.symbol_id, c.rotation_step) for c in mw.canvas.scene.items()
                  if isinstance(c, SymbolComponent))


def _only(mw):
    from src.components.symbol_component import SymbolComponent
    return next(c for c in mw.canvas.scene.items() if isinstance(c, SymbolComponent))


def _fresh(mw):
    mw.canvas.scene.clear()
    mw._ensure_decorations()
    mw.undo_stack.clear()
    mw.redo_stack.clear()
    return mw


def test_undo_walks_back_through_every_step(main_window):
    mw = _fresh(main_window)
    comp = mw.create_component("resistor", 200, 200)
    mw.canvas.scene.addItem(comp)
    mw._push_undo_snapshot()                       # Platzieren (nachher)
    _only(mw).setSelected(True)
    mw.rotate_selected()                           # Bearbeiten > Drehen (nachher)
    QApplication.processEvents()
    _only(mw)._rotate_from_menu()                  # Kontextmenü-Drehen
    QApplication.processEvents()
    _only(mw).setSelected(True)
    mw.delete_selected()                           # Löschen (vorher)
    assert _state(mw) == []
    history = []
    for _ in range(4):
        mw.undo()
        QApplication.processEvents()
        history.append(_state(mw))
    assert history == [[("resistor", 2)], [("resistor", 1)],
                       [("resistor", 0)], []]
    for expected in ([("resistor", 0)], [("resistor", 1)], [("resistor", 2)], []):
        mw.redo()
        QApplication.processEvents()
        assert _state(mw) == expected


def test_context_menu_delete_is_deferred_and_undoable(main_window):
    mw = _fresh(main_window)
    comp = mw.create_component("resistor", 200, 200)
    mw.canvas.scene.addItem(comp)
    mw._push_undo_snapshot()
    comp.delete_self(False)
    assert _state(mw) == [("resistor", 0)], "Löschen muss nach dem Ereignis laufen"
    QApplication.processEvents()
    assert _state(mw) == []
    mw.undo()
    assert _state(mw) == [("resistor", 0)]


def test_arc_delete_relayouts_labels(main_window):
    from src.components.annotations import VoltageAnnotation
    mw = _fresh(main_window)
    comp = mw.create_component("resistor", 200, 200)
    mw.canvas.scene.addItem(comp)
    arc = VoltageAnnotation(comp, "5 V")
    comp.annotations.append(arc)
    arc._rotate_step()        # Bogen nach links -> Beschriftung rechts
    assert comp._label_side() == 1
    arc.setSelected(True)
    mw.delete_selected()
    assert comp._label_side() == 2, "ohne Bogen zurück auf die Standardseite"
