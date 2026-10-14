"""Spannungsbogen und Strompfeil einzeln umkehren/drehen: Kontextmenü,
Tastenkürzel (U, R), Werkzeugleiste, Undo."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtCore import QPointF
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QApplication, QMenu


def _setup(mw):
    from src.components.annotations import VoltageAnnotation, CurrentAnnotation
    from src.components.wire import Wire
    mw.canvas.scene.clear()
    mw._ensure_decorations()
    mw.undo_stack.clear()
    mw.redo_stack.clear()
    mw.activate_select_mode()
    comp = mw.create_component("resistor", 200, 200)
    mw.canvas.scene.addItem(comp)
    arc = VoltageAnnotation(comp, "5 V")
    arc.setPos(comp.mapFromScene(QPointF(200, 200)))
    comp.annotations.append(arc)
    wire = Wire(QPointF(100, 400), QPointF(300, 400))
    mw.canvas.scene.addItem(wire)
    arrow = CurrentAnnotation(wire, "1 A", 0.0)
    arrow.setPos(wire.mapFromScene(QPointF(200, 400)))
    wire.annotations.append(arrow)
    mw._push_undo_snapshot()
    return comp, arc, wire, arrow


class _Ev:
    def __init__(self, pos):
        self._pos = pos
        self._acc = False

    def scenePos(self):
        return self._pos

    def screenPos(self):
        return None

    def accept(self):
        self._acc = True

    def ignore(self):
        self._acc = False

    def isAccepted(self):
        return self._acc


def _menu_entries(monkeypatch, item, pos, click=None):
    """Texte des Kontextmenüs, so wie sie beim Öffnen tatsächlich da sind;
    `click` löst den Eintrag aus, solange das Menü offen ist (echter Klick)."""
    captured = []

    def fake_exec(menu, *a, **k):
        entries = {x.text().split("	")[0]: x for x in menu.actions() if x.text()}
        captured.append(list(entries))
        if click:
            entries[click].trigger()
    monkeypatch.setattr(QMenu, "exec_", fake_exec)
    item.contextMenuEvent(_Ev(pos))
    assert captured, "kein Menü geöffnet"
    return captured[-1]


def test_arc_menu_offers_reverse_and_rotate(main_window, monkeypatch):
    comp, arc, _, _ = _setup(main_window)
    apex = arc.mapToScene(QPointF(0, -40))
    entries = _menu_entries(monkeypatch, comp, apex,   # Rechtsklick übers Bauteil
                            click="Richtung umkehren")
    assert "Bogen drehen (90°)" in entries, entries
    assert arc.flipped is True
    _menu_entries(monkeypatch, comp, apex, click="Bogen drehen (90°)")
    assert arc.angle_deg == 270.0


def test_arrow_menu_offers_reverse(main_window, monkeypatch):
    _, _, wire, arrow = _setup(main_window)
    _menu_entries(monkeypatch, wire, QPointF(200, 400),   # über die Leitung
                  click="Richtung umkehren")
    assert arrow.angle_deg == 180.0


def test_component_menu_entries_survive(main_window, monkeypatch):
    comp, _, _, _ = _setup(main_window)
    entries = _menu_entries(monkeypatch, comp, QPointF(140, 260))  # neben dem Bogen
    for label in ("Drehen (90°)", "Vergrößern", "Verkleinern", "Löschen"):
        assert label in entries, entries


def test_u_reverses_selected_and_is_one_undo_step(main_window):
    mw = main_window
    _, arc, _, arrow = _setup(mw)
    assert mw.reverse_action.shortcut() == QKeySequence("U")
    arc.setSelected(True)
    arrow.setSelected(True)
    mw.reverse_action.trigger()
    assert arc.flipped is True and arrow.angle_deg == 180.0
    mw.undo()
    from src.components.annotations import VoltageAnnotation, CurrentAnnotation
    items = mw.canvas.scene.items()
    assert not next(i for i in items if isinstance(i, VoltageAnnotation)).flipped
    assert next(i for i in items if isinstance(i, CurrentAnnotation)).angle_deg == 0.0


def test_r_on_selected_arc_rotates_only_the_arc(main_window):
    mw = main_window
    comp, arc, _, arrow = _setup(mw)
    arc.setSelected(True)
    mw.rotate_action.trigger()
    QApplication.processEvents()
    assert comp.rotation_step == 0
    assert arc.angle_deg == 270.0
    arc.setSelected(False)
    arrow.setSelected(True)
    mw.rotate_action.trigger()
    assert arrow.angle_deg == 180.0


def test_r_with_component_and_its_arc_selected_rotates_once(main_window):
    mw = main_window
    comp, arc, _, _ = _setup(mw)
    comp.setSelected(True)
    arc.setSelected(True)
    mw.rotate_action.trigger()
    QApplication.processEvents()
    assert comp.rotation_step == 1
    assert arc.angle_deg == 270.0     # Schritt 1 -> Bogen links, nicht doppelt


def test_toolbar_has_reverse_button(main_window):
    from PyQt5.QtWidgets import QToolBar
    bar = main_window.findChild(QToolBar, "main_toolbar")
    assert main_window.reverse_action in bar.actions()
    assert not main_window.reverse_action.icon().isNull()
