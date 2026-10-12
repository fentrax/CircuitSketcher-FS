"""Mac-Feedback (René, 22.09.2026): Geister-Labels bei Drehung,
Orientierungs-Ableitung im Symbol-Editor, PNG-Auflösungsfaktor,
SVG-Export mit Inhaltsrechteck."""
import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fresh(mw):
    mw.canvas.scene.clear()
    mw._ensure_decorations()
    mw.on_component_selected("select")
    return mw


# ----------------------------------------------------------------------
# Bugfix 1: Drehen darf keine Geister-Kopien der Beschriftung hinterlassen
# ----------------------------------------------------------------------
def test_rotation_leaves_no_ghost_labels(main_window):
    mw = _fresh(main_window)
    comp = mw.create_component("resistor", 200, 200)
    mw.canvas.scene.addItem(comp)
    comp.set_placeholder_value("name", "R1")

    expected = len(comp.placeholder_items)
    assert expected > 0
    for _ in range(4):
        comp.rotate_component()

    texts = [i for i in mw.canvas.scene.items()
             if getattr(i, "is_placeholder_text", False)]
    assert len(texts) == expected, "Geister-Labels nach Drehen"
    assert all(t.parentItem() is comp for t in texts), "Label ohne Bauteil-Parent"

    grips = [i for i in comp.childItems()
             if type(i).__name__ == "_TextGripHandle"]
    assert len(grips) == expected, "verwaiste Text-Griffpunkte"


def test_preview_rotation_cleanup(main_window):
    from PyQt5.QtCore import QPointF
    mw = _fresh(main_window)
    mw.on_component_selected("resistor")
    preview = mw.create_component("resistor", 100, 100)
    mw.canvas.scene.addItem(preview)
    mw.preview_component = preview
    mw.rotate_preview()
    mw._clear_preview()

    orphans = [i for i in mw.canvas.scene.items()
               if getattr(i, "is_placeholder_text", False)
               and i.parentItem() is None]
    assert not orphans, "Vorschau-Rotation hat Label-Geister hinterlassen"


# ----------------------------------------------------------------------
# Bugfix 2: andere Orientierung aus der aktuellen ableiten (90°)
# ----------------------------------------------------------------------
def test_derive_rotated_orientation_maps_poles():
    from src.ui.symbol_editor import derive_rotated_orientation
    data = {
        "items": [
            {"type": "line", "start": [-40.0, 0.0], "end": [40.0, 0.0]},
            {"type": "circle", "center": [0.0, 5.0], "radius": 3.0},
        ],
        "placeholders": [
            {"type": "placeholder", "key": "name",
             "position": [0.0, 34.0], "alignment": "center"},
        ],
        "connection_points": [[-40.0, 0.0], [40.0, 0.0]],
        "origin": [-40.0, 0.0],
    }
    vertical = derive_rotated_orientation(data)
    # linker Pol (-40, 0) bildet auf oberen Pol (0, -40) ab (Batterie-Konvention)
    assert vertical["origin"] == [0.0, -40.0]
    assert vertical["connection_points"][0] == [0.0, -40.0]
    assert vertical["connection_points"][1] == [0.0, 40.0]
    assert vertical["items"][0]["start"] == [0.0, -40.0]
    assert vertical["items"][0]["end"] == [0.0, 40.0]
    assert vertical["items"][1]["center"] == [-5.0, 0.0]

    # Rückweg (im Uhrzeigersinn) führt exakt zum Ausgangszustand zurück
    back = derive_rotated_orientation(vertical, clockwise=True)
    assert back["origin"] == [-40.0, 0.0]
    assert back["connection_points"] == [[-40.0, 0.0], [40.0, 0.0]]
    assert back["placeholders"][0]["position"] == [0.0, 34.0]


def test_derive_orientation_from_real_battery_symbol():
    from src.ui.symbol_editor import derive_rotated_orientation
    battery = Path(__file__).resolve().parent.parent / "symbols" / "battery.symbol.json"
    data = json.loads(battery.read_text(encoding="utf-8"))
    h = data["orientations"]["horizontal"]
    v = derive_rotated_orientation(h)
    assert v["origin"] == [0.0, -40.0]
    assert [0.0, -40.0] in v["connection_points"]
    assert [0.0, 40.0] in v["connection_points"]


# ----------------------------------------------------------------------
# Wunsch 3: PNG-Auflösungsfaktor
# ----------------------------------------------------------------------
def test_png_export_with_scale_factor(main_window, tmp_path):
    from PyQt5.QtGui import QImage
    mw = _fresh(main_window)
    comp = mw.create_component("resistor", 300, 300)
    mw.canvas.scene.addItem(comp)
    comp.set_placeholder_value("name", "R1")

    target = tmp_path / "export.png"
    mw._batch_export = True  # Erfolgs-Dialoge unterdrücken
    mw.export_png(filename=str(target), scale=2)

    visible = mw.canvas.get_visible_scene_rect()
    expected_w = max(1, int(visible.width() * 2))
    expected_h = max(1, int(visible.height() * 2))
    img = QImage(str(target))
    assert not img.isNull(), "PNG wurde nicht geschrieben"
    assert img.width() == expected_w and img.height() == expected_h


# ----------------------------------------------------------------------
# Bugfix 4: SVG-Export umfasst die gezeichneten Elemente, nicht das Raster
# ----------------------------------------------------------------------
def test_svg_export_uses_content_rect(main_window, tmp_path):
    mw = _fresh(main_window)
    comp = mw.create_component("resistor", 300, 300)
    mw.canvas.scene.addItem(comp)
    comp.set_placeholder_value("name", "R1")

    target = tmp_path / "export.svg"
    mw._batch_export = True
    mw.export_svg(filename=str(target))

    text = target.read_text(encoding="utf-8")
    assert "<svg" in text, "SVG-Datei leer oder ungültig"
    match = re.search(r'viewBox="([^"]+)"', text)
    assert match, "keine viewBox im SVG"
    values = [float(v) for v in re.split(r"[ ,]+", match.group(1).strip())]
    width, height = values[2], values[3]
    assert width < 2000 and height < 2000, \
        f"viewBox umfasst das leere Raster statt den Inhalt: {values}"
    # Inhalt (Bauteil um 300/300 mit ~84px Ausdehnung) muss drin liegen
    assert 0 <= values[0] <= 300 and 0 <= values[1] <= 300
