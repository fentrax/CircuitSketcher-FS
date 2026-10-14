"""Runde 2 (René, 12.10.2026): Export-Robustheit (Endung/Format),
Spannungsbogen drehbar + Auto-Ausrichtung, Werttext verschiebbar."""
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtCore import QPointF


def _fresh(mw):
    mw.canvas.scene.clear()
    mw._ensure_decorations()
    mw.on_component_selected("select")
    return mw


def _place(mw, symbol_id, x, y, step=0):
    comp = mw.create_component(symbol_id, x, y,
                               orientation="horizontal", rotation_step=step)
    mw.canvas.scene.addItem(comp)
    return comp


# ----------------------------------------------------------------------
# Exporte: endungslose Dateinamen (macOS-Dialog) müssen funktionieren
# ----------------------------------------------------------------------
def test_export_menu_bool_call_is_safe(main_window, monkeypatch):
    """Menü-Aktionen übergeben checked=False als erstes Argument — das muss
    als GUI-Aufruf gewertet werden, nicht als Dateiname (Crash-Regression)."""
    from PyQt5.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: ("", "")))
    mw = _fresh(main_window)
    mw._batch_export = True
    mw.export_png(False)   # früher: TypeError -> nativer Absturz (exit 127)
    mw.export_svg(False)


def test_png_export_without_extension(main_window, tmp_path):
    from PyQt5.QtGui import QImage
    mw = _fresh(main_window)
    _place(mw, "resistor", 300, 300)
    target = tmp_path / "ohne_endung"          # KEIN .png — wie unter macOS
    mw._batch_export = True
    mw.export_png(filename=str(target), scale=1)
    written = tmp_path / "ohne_endung.png"
    assert written.exists(), "Endung wurde nicht ergänzt"
    img = QImage(str(written))
    assert not img.isNull() and img.width() > 0


def test_svg_export_without_extension(main_window, tmp_path):
    mw = _fresh(main_window)
    _place(mw, "resistor", 300, 300)
    target = tmp_path / "ohne_endung"          # KEIN .svg
    mw._batch_export = True
    mw.export_svg(filename=str(target))
    written = tmp_path / "ohne_endung.svg"
    assert written.exists() and written.stat().st_size > 0
    assert "<svg" in written.read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# Spannungsbogen: Drehung + Auto-Ausrichtung + Serialisierung
# ----------------------------------------------------------------------
def test_voltage_arc_rotates_and_roundtrips(main_window):
    mw = _fresh(main_window)
    comp = _place(mw, "resistor", 200, 200)
    from src.components.annotations import VoltageAnnotation
    annotation = VoltageAnnotation(comp, "20 V")
    comp.annotations.append(annotation)

    assert annotation.angle_deg == 0.0
    annotation._rotate_step()   # gegen den Uhrzeigersinn: oben -> links
    assert annotation.angle_deg == 270.0
    annotation._rotate_step()
    assert annotation.angle_deg == 180.0

    data = annotation.to_dict()
    assert data.get("angle") == 180.0

    restored = VoltageAnnotation(comp, data["value"], flipped=data.get("flip", False),
                                 angle=data.get("angle", 0.0))
    assert restored.angle_deg == 180.0


def test_voltage_arc_auto_orients_vertical(main_window, monkeypatch):
    from PyQt5.QtWidgets import QInputDialog
    monkeypatch.setattr(
        QInputDialog, "getText",
        staticmethod(lambda *a, **k: ("20 V", False)))
    mw = _fresh(main_window)
    _place(mw, "resistor", 200, 200, step=1)   # vertikal gedreht
    mw.on_component_selected("voltage")
    pos = QPointF(200, 200)
    mw._place_measurement_annotation(pos)
    from src.components.annotations import VoltageAnnotation
    arcs = [a for c in mw.canvas.scene.items()
            if isinstance(c, type(mw.create_component("resistor", 0, 0)))
            for a in getattr(c, "annotations", [])
            if isinstance(a, VoltageAnnotation)]
    assert arcs, "Spannungsbogen wurde nicht platziert"
    assert arcs[0].angle_deg == 270.0, "vertikales Bauteil sollte Bogen links bekommen"


def test_voltage_arc_follows_component_rotation(main_window):
    from PyQt5.QtWidgets import QApplication
    from src.components.annotations import VoltageAnnotation
    mw = _fresh(main_window)
    comp = _place(mw, "resistor", 200, 200)
    annotation = VoltageAnnotation(comp, "20 V")
    comp.annotations.append(annotation)
    # Absichtlich OHNE voreingestellten _base_angle: der normale Platzierungs-
    # pfad setzt ihn auch nicht — die Herleitung beim ersten Drehen muss
    # stimmen (Regression: Bogen blieb oben hängen).

    comp.rotate_component()   # -> 90° (vertikal, Bogen links)
    QApplication.processEvents()
    assert annotation.angle_deg == 270.0, "Bogen folgt der Drehung nicht"
    comp.rotate_component()   # -> 180° (Qt dreht mit, lokal zurück auf 0)
    QApplication.processEvents()
    assert annotation.angle_deg == 0.0
    comp.rotate_component()   # -> 270° (Qt +180°, lokal 270 = rechts)
    QApplication.processEvents()
    assert annotation.angle_deg == 270.0
    comp.rotate_component()   # -> zurück zu 0°
    QApplication.processEvents()
    assert annotation.angle_deg == 0.0


def test_annotation_hit_routing(main_window):
    """Rechtsklick-Routing: Bogen und Strompfeil müssen an ihrem Ort das
    oberste Item sein, sonst geht der Kontextmenü-Klick daneben."""
    from src.components.annotations import VoltageAnnotation
    mw = _fresh(main_window)
    comp = _place(mw, "resistor", 300, 300)
    annotation = VoltageAnnotation(comp, "20 V")
    comp.annotations.append(annotation)
    poles = comp.get_pole_points()
    mid = QPointF((poles[0].x() + poles[1].x()) / 2.0,
                  (poles[0].y() + poles[1].y()) / 2.0)
    annotation.setPos(comp.mapFromScene(mid))

    # Klickpunkte in der Bogenfläche: zwischen Bauteilachse und Bogenlinie
    for probe in (mid + QPointF(0, -18), mid + QPointF(0, -32),
                  mid + QPointF(0, -44)):
        hit_items = mw.canvas.scene.items(probe)
        assert any(i is annotation for i in hit_items), \
            f"Spannungsbogen bei y-Offset {probe.y() - mid.y()} nicht treffbar"


def test_current_text_offset_roundtrip(main_window):
    mw = _fresh(main_window)
    from src.components.wire import Wire
    from src.components.annotations import CurrentAnnotation
    wire = Wire(QPointF(100, 100), QPointF(300, 100), grid_size=20)
    mw.canvas.scene.addItem(wire)
    annotation = CurrentAnnotation(wire, "15 mA", 0.0)
    wire.annotations.append(annotation)
    annotation.set_text_offset(25.0, -40.0)

    data = annotation.to_dict()
    assert data.get("text_offset") == [25.0, -40.0]

    restored = CurrentAnnotation(wire, data["value"], data["angle"])
    restored.set_text_offset(*data["text_offset"])
    assert restored._text_offset.x() == 25.0 and restored._text_offset.y() == -40.0


def test_text_drag_enabled_only_when_selected(main_window):
    mw = _fresh(main_window)
    from src.components.wire import Wire
    from src.components.annotations import CurrentAnnotation
    wire = Wire(QPointF(100, 100), QPointF(300, 100), grid_size=20)
    mw.canvas.scene.addItem(wire)
    annotation = CurrentAnnotation(wire, "1 A", 0.0)
    wire.annotations.append(annotation)

    from PyQt5.QtWidgets import QGraphicsItem
    assert not annotation.text_item.flags() & QGraphicsItem.ItemIsMovable
    annotation.setSelected(True)
    assert annotation.text_item.flags() & QGraphicsItem.ItemIsMovable


# ----------------------------------------------------------------------
# Rechtsklick-Zustellung: Leitung/Bauteil über dem Bogen müssen an diesen
# durchreichen statt ihr eigenes Menü zeigen (Regression: 1 von 30 Treffern)
# ----------------------------------------------------------------------
class _FakeContextEvent:
    """QGraphicsSceneContextMenuEvent-Ersatz (in PyQt5 nicht konstruierbar)."""

    def __init__(self, scene_pos, screen_pos):
        self._scene_pos = scene_pos
        self._screen_pos = screen_pos
        self._accepted = False

    def scenePos(self):
        return self._scene_pos

    def screenPos(self):
        return self._screen_pos

    def accept(self):
        self._accepted = True

    def ignore(self):
        self._accepted = False

    def isAccepted(self):
        return self._accepted


def test_wire_menu_defers_to_overlapped_arc(main_window, monkeypatch):
    """Eine NACH dem Bauteil eingefügte Leitung stapelt über dem Bogen —
    ihr Rechtsklick-Menü muss den Bogen durchreichen."""
    from PyQt5.QtWidgets import QMenu
    from src.components.wire import Wire
    from src.components.annotations import VoltageAnnotation

    opened = []
    monkeypatch.setattr(
        QMenu, "exec_",
        lambda self, pos=None: opened.append(
            [a.text() for a in self.actions()]) and None)

    mw = _fresh(main_window)
    comp = _place(mw, "resistor", 200, 200)
    annotation = VoltageAnnotation(comp, "20 V")
    comp.annotations.append(annotation)
    poles = comp.get_pole_points()
    mid = QPointF((poles[0].x() + poles[1].x()) / 2.0,
                  (poles[0].y() + poles[1].y()) / 2.0)
    annotation.setPos(comp.mapFromScene(mid))

    # Leitung danach einfügen: gleiche z-Ebene, spätere Einfügung stapelt oben.
    # Sie läuft exakt durch die Bogenfläche (Sondpunkt y=-32 liegt auf ihr).
    wire = Wire(QPointF(80, 168), QPointF(320, 168), grid_size=20)
    mw.canvas.scene.addItem(wire)

    # Sanity: die Leitung liegt im Stacking tatsächlich vor der Annotation
    stack = mw.canvas.scene.items(mid + QPointF(0, -32))
    assert stack.index(wire) < stack.index(annotation), \
        "Testaufbau greift nicht: Leitung stapelt nicht über dem Bogen"

    wire.contextMenuEvent(_FakeContextEvent(mid + QPointF(0, -32), QPointF(0, 0)))
    assert opened and "Wert bearbeiten" in opened[-1], \
        "Rechtsklick auf Leitung über dem Bogen zeigte das Leitungsmenü"


def test_component_menu_defers_to_own_arc(main_window, monkeypatch):
    """Auch das Bauteil-Menü selbst reicht an den eigenen Bogen durch."""
    from PyQt5.QtWidgets import QMenu
    from src.components.annotations import VoltageAnnotation

    opened = []
    monkeypatch.setattr(
        QMenu, "exec_",
        lambda self, pos=None: opened.append(
            [a.text() for a in self.actions()]) and None)

    mw = _fresh(main_window)
    comp = _place(mw, "resistor", 200, 200)
    annotation = VoltageAnnotation(comp, "20 V")
    comp.annotations.append(annotation)
    poles = comp.get_pole_points()
    mid = QPointF((poles[0].x() + poles[1].x()) / 2.0,
                  (poles[0].y() + poles[1].y()) / 2.0)
    annotation.setPos(comp.mapFromScene(mid))

    comp.contextMenuEvent(_FakeContextEvent(mid + QPointF(0, -18), QPointF(0, 0)))
    assert opened and "Wert bearbeiten" in opened[-1], \
        "Rechtsklick auf Bauteil über dem Bogen zeigte das Bauteilmenü"


def test_wire_menu_opens_without_annotation_nearby(main_window, monkeypatch):
    """Ohne Annotation an der Klickposition bleibt es beim Leitungsmenü."""
    from PyQt5.QtWidgets import QMenu
    from src.components.wire import Wire

    opened = []
    monkeypatch.setattr(
        QMenu, "exec_",
        lambda self, pos=None: opened.append(
            [a.text() for a in self.actions()]) and None)

    mw = _fresh(main_window)
    wire = Wire(QPointF(100, 400), QPointF(400, 400), grid_size=20)
    mw.canvas.scene.addItem(wire)

    wire.contextMenuEvent(_FakeContextEvent(QPointF(250, 400), QPointF(0, 0)))
    assert opened and any("Farbe" in t for t in opened[-1]), \
        "Leitungsmenü ohne Annotation im Umfeld fehlt"
