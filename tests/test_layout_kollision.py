"""Profi-Layout: Beschriftungen, Spannungsbogen und Werttexte überschneiden
sich in keiner Drehlage mit dem Symbolkörper oder untereinander — für jedes
Symbol der Bibliothek."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtWidgets import QApplication

from src.components.annotations import ARC_HALF_WIDTH, ARC_HEIGHT


def _symbol_ids():
    root = Path(__file__).resolve().parent.parent / "symbols"
    return sorted(p.name.split(".")[0] for p in root.glob("*.symbol.json"))


def _scene_rect(item, rect):
    return item.mapToScene(rect).boundingRect()


def _text_rect(text_item):
    # Sichtbare Glyphen: Dokumentrand abziehen, 0.5 px Toleranz
    r = text_item.boundingRect().adjusted(1.5, 1.5, -1.5, -1.5)
    return _scene_rect(text_item, r)


def _arc_rect(arc):
    b = arc.base_offset
    local = QRectF(-ARC_HALF_WIDTH, -b - ARC_HEIGHT, 2 * ARC_HALF_WIDTH, ARC_HEIGHT)
    pts = [arc._rotated(p) for p in (local.topLeft(), local.topRight(),
                                     local.bottomLeft(), local.bottomRight())]
    xs = [p.x() for p in pts]
    ys = [p.y() for p in pts]
    return _scene_rect(arc, QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))


def _body_scene(comp):
    # Körper ohne die Pol-Anschlussleitungen entlang der Achse ist schwer
    # generisch zu trennen — die Hülle aller Symbolteile ist die strengere Prüfung.
    return _scene_rect(comp, comp._body_rect().adjusted(0.5, 0.5, -0.5, -0.5))


def _overlap(a, b):
    return a.intersects(b) and a.intersected(b).width() > 0.5 and a.intersected(b).height() > 0.5


@pytest.mark.parametrize("with_arc", [False, True])
def test_no_overlaps_all_symbols_all_steps(main_window, with_arc):
    from src.components.annotations import VoltageAnnotation
    mw = main_window
    problems = []
    for symbol_id in _symbol_ids():
        if symbol_id not in mw.symbol_definitions:
            continue
        mw.canvas.scene.clear()
        mw._ensure_decorations()
        comp = mw.create_component(symbol_id, 400, 400)
        mw.canvas.scene.addItem(comp)
        if with_arc and len(comp.get_pole_points()) == 2:
            poles = comp.get_pole_points()
            arc = VoltageAnnotation(comp, "230 V")
            arc.setPos(comp.mapFromScene((poles[0] + poles[1]) / 2.0))
            comp.annotations.append(arc)
            comp._layout_labels()
        for step in range(4):
            if step:
                comp.rotate_component()
                QApplication.processEvents()
            body = _body_scene(comp)
            texts = {f"Label {k}": _text_rect(t) for k, t in comp.placeholder_items.items()}
            for arc in comp._voltage_arcs():
                texts["Bogenwert"] = _text_rect(arc.text_item)
                arc_r = _arc_rect(arc)
                if _overlap(arc_r, body):
                    problems.append(f"{symbol_id}@{step}: Bogen schneidet Körper")
            names = list(texts)
            for name in names:
                if _overlap(texts[name], body):
                    problems.append(f"{symbol_id}@{step}: {name} schneidet Körper")
                for arc in comp._voltage_arcs():
                    if name != "Bogenwert" and _overlap(texts[name], _arc_rect(arc)):
                        problems.append(f"{symbol_id}@{step}: {name} schneidet Bogen")
            for i, a in enumerate(names):
                for b in names[i + 1:]:
                    if _overlap(texts[a], texts[b]):
                        problems.append(f"{symbol_id}@{step}: {a} schneidet {b}")
            for key, t in comp.placeholder_items.items():
                m = t.sceneTransform()
                if abs(m.m11() - 1) > 1e-6 or abs(m.m22() - 1) > 1e-6:
                    problems.append(f"{symbol_id}@{step}: Label {key} nicht aufrecht")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("symbol_id", ["ammeter", "voltmeter"])
def test_glyphs_inside_circle_stay_upright(main_window, symbol_id):
    """«A», «V» im Kreis: bei jeder Lage identisch zur Grundlage
    (horizontal bzw. vertikal) — nie kopfüber.

    Der Motor ist im FS-Programm ein eigenes Symbol (Richtungslinie mit
    «direction»-Platzhalter für die Simulation) — sein M ist ein Text-
    Platzhalter und wird wie jedes Label gegenrotiert, kein Glyph.
    """
    mw = main_window
    comp = mw.create_component(symbol_id, 0, 0)
    mw.canvas.scene.addItem(comp)
    glyphs = [i for i in comp.render_items if "glyph_center" in i]
    assert glyphs, "Buchstabe im Kreis nicht erkannt"

    class _RecPainter:
        """Zeichnet nichts, protokolliert nur drawLine-Aufrufe aus paint()."""
        def __init__(self):
            self.lines = []
        def drawLine(self, a, b):
            self.lines.append((QPointF(a), QPointF(b)))
        def __getattr__(self, name):
            return lambda *a, **k: None

    def drawn(c):
        """Tatsächlich gezeichnete Linien im Symbolkreis, in Szenenkoordinaten
        relativ zur Kreismitte."""
        rec = _RecPainter()
        c.paint(rec, None, None)
        circle = next(i for i in c.render_items
                      if i["type"] == "circle" and i["radius"] > 6)
        ctr, r = circle["center"], circle["radius"]
        sc = c.mapToScene(ctr)
        out = []
        for a, b in rec.lines:
            if all((p.x() - ctr.x()) ** 2 + (p.y() - ctr.y()) ** 2 < r * r for p in (a, b)):
                out.append(tuple(sorted(
                    (round(c.mapToScene(p).x() - sc.x(), 1),
                     round(c.mapToScene(p).y() - sc.y(), 1)) for p in (a, b))))
        return sorted(set(out))

    reference = {0: drawn(comp)}
    for step in (1, 2, 3):
        comp.rotate_component()
        QApplication.processEvents()
        if step == 1:
            reference[1] = drawn(comp)
        else:
            assert drawn(comp) == reference[step % 2], f"Schritt {step} kopfüber"
