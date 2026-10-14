"""Runde 2 (René): Dreh- und Text-Lagen für alle vier Bauteilschritte.

Erwartung Spannungsbogen (Bauteil dreht im Uhrzeigersinn, Bogen wandert
gegen den Uhrzeigersinn): Schritt 0 oben, 1 links, 2 unten, 3 rechts.
Alle Werttexte und Platzhalter stehen stets aufrecht (nie kopfüber oder
gespiegelt) und bleiben an ihrem Anker.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PyQt5.QtCore import QPointF
from PyQt5.QtWidgets import QApplication

EXPECTED_SIDE = {0: "oben", 1: "links", 2: "unten", 3: "rechts"}
# Lokaler Bogenwinkel (Qt dreht bei Schritt 2/3 das ganze Bauteil um 180°).
EXPECTED_LOCAL_ANGLE = {0: 0.0, 1: 270.0, 2: 0.0, 3: 270.0}


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


def _side(annotation):
    """Visuelle Seite des Bogenscheitels relativ zum Bogen-Anker (Szene)."""
    from src.components.annotations import ARC_BASE_OFFSET, ARC_HEIGHT
    apex = annotation.mapToScene(
        annotation._rotated(QPointF(0, -(ARC_BASE_OFFSET + ARC_HEIGHT))))
    origin = annotation.scenePos()
    dx, dy = apex.x() - origin.x(), apex.y() - origin.y()
    if abs(dx) > abs(dy):
        return "rechts" if dx > 0 else "links"
    return "unten" if dy > 0 else "oben"


def _assert_upright(text_item, what):
    t = text_item.sceneTransform()
    assert t.m11() == pytest.approx(1.0, abs=1e-6), f"{what}: gedreht/gespiegelt"
    assert t.m22() == pytest.approx(1.0, abs=1e-6), f"{what}: gedreht/gespiegelt"
    assert t.m12() == pytest.approx(0.0, abs=1e-6), f"{what}: schräg"
    assert t.m21() == pytest.approx(0.0, abs=1e-6), f"{what}: schräg"


def _assert_text_at_anchor(annotation):
    """Textmitte (Szene) == Anker + Versatz (Szene) — kein Wegspringen."""
    text = annotation.text_item
    center = text.mapToScene(text.boundingRect().center())
    anchor = annotation.mapToScene(annotation.text_anchor() + annotation._text_offset)
    assert center.x() == pytest.approx(anchor.x(), abs=0.5)
    assert center.y() == pytest.approx(anchor.y(), abs=0.5)


def _assert_placeholders(comp, step):
    assert comp.placeholder_items, "Testsymbol braucht Platzhalter"
    for key, item in comp.placeholder_items.items():
        _assert_upright(item, f"Platzhalter {key} @ Schritt {step}")
        # Gegenrotation darf das Label nicht vom Standardplatz verschieben.
        rect = item.boundingRect()
        center = item.mapToParent(rect.center())
        expected = item.pos() + rect.center()
        assert center.x() == pytest.approx(expected.x(), abs=0.5), key
        assert center.y() == pytest.approx(expected.y(), abs=0.5), key


def _assert_arc_state(arc, step):
    assert _side(arc) == EXPECTED_SIDE[step], f"Bogen-Seite @ Schritt {step}"
    assert arc.angle_deg == EXPECTED_LOCAL_ANGLE[step], f"Winkel @ Schritt {step}"
    _assert_upright(arc.text_item, f"Bogentext @ Schritt {step}")
    _assert_text_at_anchor(arc)


def test_arc_side_angle_and_text_for_all_steps(main_window):
    from src.components.annotations import VoltageAnnotation
    mw = _fresh(main_window)
    comp = _place(mw, "resistor", 200, 200)
    arc = VoltageAnnotation(comp, "20 V")
    comp.annotations.append(arc)
    _assert_arc_state(arc, 0)
    _assert_placeholders(comp, 0)
    for step in (1, 2, 3, 0):
        comp.rotate_component()
        QApplication.processEvents()
        assert comp.rotation_step == step
        _assert_arc_state(arc, step)
        _assert_placeholders(comp, step)


@pytest.mark.parametrize("step", [0, 1, 2, 3])
def test_placement_matches_rotation_cycle(main_window, monkeypatch, step):
    """Neu gesetzter Bogen liegt auf derselben Seite wie nach Drehen."""
    from PyQt5.QtWidgets import QInputDialog
    from src.components.annotations import VoltageAnnotation
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("20 V", True)))
    mw = _fresh(main_window)
    comp = _place(mw, "resistor", 200, 200, step=step)
    mw.on_component_selected("voltage")
    mw._place_measurement_annotation(QPointF(200, 200))
    arcs = [a for a in comp.annotations if isinstance(a, VoltageAnnotation)]
    assert arcs, "Spannungsbogen wurde nicht platziert"
    _assert_arc_state(arcs[0], step)


def test_manual_rotate_matches_sync_direction(main_window):
    """«Bogen drehen (90°)» dreht wie die Synchronisation gegen den Uhrzeigersinn."""
    from src.components.annotations import VoltageAnnotation
    mw = _fresh(main_window)
    comp = _place(mw, "resistor", 200, 200)
    arc = VoltageAnnotation(comp, "20 V")
    comp.annotations.append(arc)
    sides = []
    for _ in range(4):
        arc._rotate_step()
        sides.append(_side(arc))
        _assert_upright(arc.text_item, "Bogentext manuell")
        _assert_text_at_anchor(arc)
    assert sides == ["links", "unten", "rechts", "oben"]


def test_manual_rotate_then_component_rotate_keeps_relation(main_window):
    """Manuell gedrehter Bogen dreht danach relativ zur neuen Lage weiter."""
    from src.components.annotations import VoltageAnnotation
    mw = _fresh(main_window)
    comp = _place(mw, "resistor", 200, 200)
    arc = VoltageAnnotation(comp, "20 V")
    comp.annotations.append(arc)
    comp.rotate_component()           # Schritt 1: links
    QApplication.processEvents()
    arc._rotate_step()                # manuell: unten
    assert _side(arc) == "unten"
    comp.rotate_component()           # Schritt 2: eine Vierteldrehung weiter
    QApplication.processEvents()
    assert _side(arc) == "rechts"


def test_current_arrow_text_upright_all_directions(main_window):
    from src.components.annotations import CurrentAnnotation
    from src.components.wire import Wire
    mw = _fresh(main_window)
    wire = Wire(QPointF(100, 100), QPointF(300, 100))
    mw.canvas.scene.addItem(wire)
    arrow = CurrentAnnotation(wire, "2 A", 0.0)
    arrow.setPos(wire.mapFromScene(QPointF(200, 100)))
    wire.annotations.append(arrow)
    for angle in (0.0, 90.0, 180.0, 270.0):
        arrow.set_angle(angle)
        _assert_upright(arrow.text_item, f"Stromtext @ {angle}")
        _assert_text_at_anchor(arrow)
        arrow._flip_direction()
        _assert_upright(arrow.text_item, f"Stromtext gedreht @ {angle}")


@pytest.mark.parametrize("step", [0, 1, 2, 3])
def test_save_load_roundtrip_preserves_lagen(main_window, tmp_path, step):
    from src.components.annotations import VoltageAnnotation, CurrentAnnotation
    from src.components.symbol_component import SymbolComponent
    from src.components.wire import Wire
    mw = _fresh(main_window)
    comp = _place(mw, "resistor", 200, 200)
    arc = VoltageAnnotation(comp, "20 V")
    comp.annotations.append(arc)
    for _ in range(step):
        comp.rotate_component()
        QApplication.processEvents()
    arc.set_text_offset(6, -4)
    wire = Wire(QPointF(100, 400), QPointF(300, 400))
    mw.canvas.scene.addItem(wire)
    arrow = CurrentAnnotation(wire, "2 A", 180.0)
    arrow.setPos(wire.mapFromScene(QPointF(200, 400)))
    arrow.set_text_offset(-5, 3)
    wire.annotations.append(arrow)

    def _state():
        c = next(i for i in mw.canvas.scene.items() if isinstance(i, SymbolComponent))
        a = next(x for x in c.annotations if isinstance(x, VoltageAnnotation))
        w = next(i for i in mw.canvas.scene.items() if isinstance(i, Wire))
        p = next(x for x in w.annotations if isinstance(x, CurrentAnnotation))
        _assert_upright(a.text_item, "Bogentext nach Laden")
        _assert_upright(p.text_item, "Stromtext nach Laden")
        _assert_placeholders(c, c.rotation_step)

        def center(t):
            pt = t.mapToScene(t.boundingRect().center())
            return (round(pt.x(), 1), round(pt.y(), 1))
        return (c.rotation_step, a.angle_deg, _side(a), center(a.text_item),
                p.angle_deg, center(p.text_item),
                {k: center(t) for k, t in c.placeholder_items.items()})

    before = _state()
    assert before[2] == EXPECTED_SIDE[step]
    target = tmp_path / "lagen.sz.json"
    mw._save_to(target)
    mw.canvas.scene.clear()
    mw._ensure_decorations()
    mw.load_circuit(str(target))
    QApplication.processEvents()
    assert _state() == before


@pytest.mark.parametrize("turns", [2, 3, 4])
def test_rapid_rotation_without_event_loop(main_window, turns):
    """Mehrfaches Drehen, bevor der verzögerte Sync läuft (Tasten-Autorepeat):
    der Bogen muss trotzdem auf der Seite des Endschritts landen."""
    from src.components.annotations import VoltageAnnotation
    mw = _fresh(main_window)
    comp = _place(mw, "resistor", 200, 200)
    arc = VoltageAnnotation(comp, "20 V")
    comp.annotations.append(arc)
    for _ in range(turns):
        comp.rotate_component()
    QApplication.processEvents()
    _assert_arc_state(arc, turns % 4)


@pytest.mark.parametrize("step", [0, 1, 2, 3])
def test_label_grip_sits_at_visible_top_left(main_window, step):
    mw = _fresh(main_window)
    comp = _place(mw, "resistor", 200, 200, step=step)
    for key, item in comp.placeholder_items.items():
        visible = item.mapToScene(item.boundingRect()).boundingRect()
        grip = item.grip.scenePos()
        assert grip.x() == pytest.approx(visible.left(), abs=0.5), key
        assert grip.y() == pytest.approx(visible.top(), abs=0.5), key
