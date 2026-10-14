"""
Dynamic symbol component rendered from external definition.
"""
from __future__ import annotations

from typing import Dict, List

from PyQt5.QtCore import QPointF, Qt, QRectF
from PyQt5.QtGui import QColor, QPen
from PyQt5.QtWidgets import QInputDialog, QGraphicsItem

from .base_component import BaseComponent
from ..symbols.library import OrientationData, SymbolDefinition


PLACEHOLDER_PROMPTS = {
    "name": ("Name", "Beschriftung eingeben:"),
    "voltage": ("Spannung", "Spannung eingeben:"),
    "current": ("Strom", "Stromstärke eingeben:"),
    "resistance": ("Widerstand", "Widerstandswert eingeben:"),
}


from PyQt5.QtWidgets import QGraphicsEllipseItem  # noqa: E402 (RailEndHandle)


RAIL_SYMBOLS = ("rail_plus", "rail_minus")
RAIL_MIN_LENGTH = 120.0
RELAY_CONTACT_SYMBOLS = ("relay_contact_no", "relay_contact_nc",
                         "timer_contact_pickup", "timer_contact_dropout")
COIL_SYMBOL_IDS = ("relay_coil", "timer_coil")


class RailEndHandle(QGraphicsEllipseItem):
    """Griffpunkt am Schienenende: Ziehen verlängert/verkürzt die Schiene.

    Kind des Bauteils; die Drag-Koordinate liegt damit automatisch im
    (evtl. gedrehten) Bauteil-Koordinatensystem — die Schiene behält ihre
    Ausrichtung, nur die Länge ändert sich (Raster-Snap im Owner).
    """

    is_handle = True

    def __init__(self, owner, radius=5):
        super().__init__(-radius, -radius, radius * 2, radius * 2, owner)
        self.owner = owner
        self.setBrush(QColor(255, 255, 255))
        self.setPen(QPen(QColor(60, 120, 200), 1))
        self.setCursor(Qt.SizeAllCursor)
        self.setZValue(20)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)

    def mousePressEvent(self, event):
        event.accept()

    def mouseMoveEvent(self, event):
        length = max(RAIL_MIN_LENGTH, event.pos().x())
        self.owner.apply_rail_length(length)
        event.accept()

    def mouseReleaseEvent(self, event):
        # Undo erst am Ende des Zugs (wie bei den anderen Griffpunkten)
        self.owner._push_undo_from_component()
        event.accept()


class SymbolComponent(BaseComponent):
    """Component instance rendered from a data-driven symbol definition."""

    def __init__(
        self,
        definition: SymbolDefinition,
        orientation: str = "horizontal",
        x: float = 0.0,
        y: float = 0.0,
        rotation_step: int = 0,
    ):
        # rotation_step früh setzen, da BaseComponent.__init__ bereits
        # _update_text_orientation() aufruft (welches hier überschrieben wird).
        self.rotation_step = int(rotation_step) % 4
        super().__init__(x, y)
        self.text_item.setVisible(False)

        self.definition = definition
        self.symbol_id = definition.symbol_id
        self.component_type = definition.name

        for key, value in definition.default_values.items():
            self.placeholder_values.setdefault(key, value)

        # rotation_step wurde bereits vor super().__init__ gesetzt.
        self.orientation = "horizontal" if self.rotation_step % 2 == 0 else "vertical"
        if self.orientation not in definition.orientations:
            self.orientation = "horizontal"
            self.rotation_step = 0

        self._origin_offset = QPointF(0.0, 0.0)
        self.render_items: List[Dict] = []
        self.local_bounding_rect = QRectF()

        self.apply_orientation()

    def apply_orientation(self):
        """Apply the current orientation to update geometry and visuals."""
        orientation_data = self.definition.get_orientation(self.orientation)

        self.prepareGeometryChange()

        origin = orientation_data.origin
        origin_point = QPointF(float(origin[0]), float(origin[1]))

        bounds = orientation_data.bounds
        min_local = QPointF(
            float(bounds["min"][0]) - origin_point.x(),
            float(bounds["min"][1]) - origin_point.y(),
        )
        max_local = QPointF(
            float(bounds["max"][0]) - origin_point.x(),
            float(bounds["max"][1]) - origin_point.y(),
        )
        local_rect = QRectF(min_local, max_local).normalized()
        self.local_bounding_rect = local_rect
        self.set_custom_bounding_rect(local_rect)

        self._origin_offset = origin_point

        self.width = max(local_rect.width(), 1.0)
        self.height = max(local_rect.height(), 1.0)

        self.connection_points = [
            self._shift_point(point) for point in orientation_data.connection_points
        ]

        self.render_items = self._prepare_render_items(orientation_data.items)

        adjusted_placeholders = []
        for placeholder in orientation_data.placeholders:
            position = placeholder.get("position", [0.0, 0.0])
            adjusted = dict(placeholder)
            adjusted["position"] = [
                position[0] - self._origin_offset.x(),
                position[1] - self._origin_offset.y(),
            ]
            adjusted_placeholders.append(adjusted)

        self.configure_placeholders(adjusted_placeholders, self.definition.default_values)

        # Funktionsschema: Schienenlänge/Endgriffpunkt bzw. Relais-Zuweisung
        self._init_fs_extras()

        self._apply_rotation_transform()
        self._layout_labels()
        self.update()

    def _apply_rotation_transform(self):
        """Qt-Rotation passend zum aktuellen rotation_step setzen.

        Die vertical-Orientierung der Symboldefinition ist bereits für 90°
        gezeichnet, daher wird bei ungeraden Schritten nur das zusätzliche
        180°-Kippen (Schritt 3) per Qt angewendet. So entstehen vier
        korrekte Lagen: 0°, 90°, 180°, 270°.
        """
        qt_angle = (self.rotation_step // 2) * 180
        self.rotation_angle = self.rotation_step * 90
        QGraphicsItem.setRotation(self, qt_angle)
        self._update_text_orientation()

    @property
    def rotation_angle_deg(self) -> int:
        """Tatsächlicher visueller Winkel in Grad (0/90/180/270)."""
        return self.rotation_step * 90

    #: Maximale Kreis-Radien, die als Anschluss-Pol gelten. Größere Kreise
    #: (z. B. r=20 bei Lampe/Voltmeter/Amperemeter) sind der Symbolkörper.
    POLE_MAX_CIRCLE_RADIUS = 6.0

    def get_pole_points(self):
        """Absolute Szenen-Koordinaten der beiden Pole der aktiven Orientierung.

        Pole-Erkennung (zwei Stufen):
        1. Explizite Anschlusspunkte (`connection_points`) aus der
           Symboldefinition — die im Symbol-Editor gesetzten Trenn-/Andock-
           Punkte. Bei mehr als 2 Anschlüssen zählt das äußere Paar.
        2. Fallback für Symbole ohne Anschlüsse (Heuristik): kleine
           Anschlusskreise (radius <= POLE_MAX_CIRCLE_RADIUS); falls keine
           vorhanden, das Paar von Linien-Endpunkten mit maximalem Abstand.

        Rückgabe: Liste mit 0 oder 2 QPointF in Szenen-Koordinaten, sortiert als
        [Eingang, Ausgang] (Eingang = kleineres x, bei Gleichstand kleineres y).
        Wird für das Wire-Splitting und das magnetische Einrasten von
        Leitungsenden genutzt.
        """
        # Stufe 1: explizite Anschlüsse (Trennpunkte) aus der Definition.
        # Ein EINZIGER expliziter Anschluss (z. B. Erde) wird respektiert —
        # kein Heuristik-Fallback, der ein Phantasie-Polpaar erfinden würde.
        explicit = self.get_connection_points()
        if len(explicit) == 1:
            return [explicit[0]]
        if len(explicit) >= 2:
            poles = self._outermost_pair(explicit) if len(explicit) > 2 else list(explicit)
        else:
            # Stufe 2: Heuristik-Fallback.
            poles = self._heuristic_poles()
            if not poles:
                return []

        # Reihenfolge [Eingang, Ausgang]: Eingang kommt in Leserichtung zuerst
        # (kleineres x, bei Gleichstand kleineres y).
        p1, p2 = poles
        if (p1.x(), p1.y()) > (p2.x(), p2.y()):
            poles = [p2, p1]
        return poles

    def _heuristic_poles(self):
        """Pole-Schätzung für Symbole ohne explizite Anschlüsse."""
        circle_poles = []
        for item in self.render_items:
            if item.get("type") != "circle":
                continue
            radius = float(item.get("radius", 0.0))
            if radius > self.POLE_MAX_CIRCLE_RADIUS:
                continue  # Symbolkörper (z. B. Lampe/Messgerät), kein Pol
            center_local = item.get("center")
            if center_local is not None:
                circle_poles.append(self.mapToScene(center_local))

        if len(circle_poles) >= 2:
            return self._outermost_pair(circle_poles)

        # Fallback: Linien-Endpunkte ohne Anschlusskreise (Schalter etc.)
        line_ends = []
        for item in self.render_items:
            if item.get("type") == "line":
                for key in ("start", "end"):
                    point = item.get(key)
                    if point is not None:
                        line_ends.append(self.mapToScene(point))
        if len(line_ends) < 2:
            return []
        return self._outermost_pair(line_ends)

    @staticmethod
    def _outermost_pair(points):
        """Das Paar mit maximalem Abstand aus einer Punktmenge bestimmen."""
        best_pair = None
        best_dist = -1.0
        for i in range(len(points)):
            for j in range(i + 1, len(points)):
                dx = points[i].x() - points[j].x()
                dy = points[i].y() - points[j].y()
                dist = dx * dx + dy * dy
                if dist > best_dist:
                    best_dist = dist
                    best_pair = [points[i], points[j]]
        return best_pair

    def _prepare_render_items(self, items: List[Dict]) -> List[Dict]:
        prepared: List[Dict] = []
        for item in items:
            item_type = item.get("type")
            if item_type == "line":
                start = self._shift_point(item.get("start", [0.0, 0.0]))
                end = self._shift_point(item.get("end", [0.0, 0.0]))
                color = self._coerce_color(item.get("color"))
                prepared.append({"type": "line", "start": start, "end": end, "color": color})
            elif item_type == "circle":
                center = self._shift_point(item.get("center", [0.0, 0.0]))
                color = self._coerce_color(item.get("color"))
                prepared.append(
                    {
                        "type": "circle",
                        "center": center,
                        "radius": float(item.get("radius", 0.0)),
                        "color": color,
                    }
                )
        self._mark_glyphs(prepared)
        return prepared

    def _mark_glyphs(self, prepared):
        """Linien vollständig innerhalb eines Symbolkreises (Messgeräte-,
        Motorbuchstaben «A», «V», «M») als Schriftzeichen markieren: sie
        müssen lesbar bleiben, wenn Qt das Bauteil um 180° dreht."""
        bodies = [i for i in prepared if i["type"] == "circle"
                  and i["radius"] > self.POLE_MAX_CIRCLE_RADIUS]
        for item in prepared:
            if item["type"] != "line":
                continue
            for body in bodies:
                c, r = body["center"], body["radius"]
                inside = all((pt.x() - c.x()) ** 2 + (pt.y() - c.y()) ** 2 < (r - 0.5) ** 2
                             for pt in (item["start"], item["end"]))
                if inside:
                    item["glyph_center"] = c
                    break

    def _shift_point(self, coords) -> QPointF:
        return QPointF(
            float(coords[0]) - self._origin_offset.x(),
            float(coords[1]) - self._origin_offset.y(),
        )

    def paint(self, painter, option, widget):
        painter.setBrush(Qt.NoBrush)

        upside_down = self.rotation_step >= 2
        for item in self.render_items:
            if item["type"] == "line" and upside_down and "glyph_center" in item:
                # Punktspiegelung an der Kreismitte hebt die Qt-180°-Drehung
                # für das Schriftzeichen auf — «A» bleibt «A», nicht «∀».
                c = item["glyph_center"]
                item = dict(item,
                            start=QPointF(2 * c.x() - item["start"].x(), 2 * c.y() - item["start"].y()),
                            end=QPointF(2 * c.x() - item["end"].x(), 2 * c.y() - item["end"].y()))
            if item["type"] == "line":
                base_pen = QPen(item["color"], 2)
                base_pen.setCapStyle(Qt.RoundCap)
                if self.isSelected():
                    highlight_pen = QPen(QColor(0, 120, 215), 4)
                    highlight_pen.setCapStyle(Qt.RoundCap)
                    painter.setPen(highlight_pen)
                    painter.drawLine(item["start"], item["end"])
                    base_pen.setWidth(3)
                painter.setPen(base_pen)
                painter.drawLine(item["start"], item["end"])
            elif item["type"] == "circle":
                center = item["center"]
                radius = item["radius"]
                base_pen = QPen(item["color"], 2)
                base_pen.setCapStyle(Qt.RoundCap)
                if self.isSelected():
                    highlight_pen = QPen(QColor(0, 120, 215), 4)
                    highlight_pen.setCapStyle(Qt.RoundCap)
                    painter.setPen(highlight_pen)
                    painter.drawEllipse(center, radius, radius)
                    base_pen.setWidth(3)
                painter.setPen(base_pen)
                painter.drawEllipse(center, radius, radius)

    def set_orientation(self, orientation: str):
        """Explizit auf horizontal oder vertical schalten (ohne Schritt zu ändern).

        Wird für Rückwärtskompatibilität mit alten Serialisierungen genutzt.
        Behält den aktuellen 180°-Knick (Schritt 0/2 bzw. 1/3) bei.
        """
        if orientation not in self.definition.orientations:
            return
        was_flipped = self.rotation_step >= 2
        new_step = 1 if orientation == "vertical" else 0
        if was_flipped:
            new_step += 2
        if new_step == self.rotation_step:
            return
        self.rotation_step = new_step
        self.orientation = orientation
        self.apply_orientation()

    def rotate_component(self, checked=False):
        """Um 90° weiterdrehen: 0° -> 90° -> 180° -> 270° -> 0°.

        Drehen ist ein Neu-Layout: manuell verschobene Beschriftungen und
        Bogenwerte springen auf ihre automatische Lage zurück — ein alter
        Versatz zeigt nach dem Drehen in eine sinnlose Richtung und würde
        Texte in den Symbolkörper schieben.
        """
        self._freeze_voltage_bases()
        self.placeholder_offsets.clear()
        for annotation in self._voltage_arcs():
            annotation._text_offset = QPointF(0.0, 0.0)
        self.rotation_step = (self.rotation_step + 1) % 4
        self.orientation = "horizontal" if self.rotation_step % 2 == 0 else "vertical"
        self.apply_orientation()
        self._sync_voltage_annotations()

    def _freeze_voltage_bases(self):
        """Bogen-Basis festhalten, solange angle_deg noch zum aktuellen Schritt
        passt (reine Rechnung, keine Szenen-Abfrage). Der verzögerte Sync
        allein würde bei mehrfachem Drehen vor dem nächsten Ereignisschleifen-
        Durchlauf (Tasten-Autorepeat) die Basis aus dem falschen Schritt
        herleiten."""
        step = self.rotation_step
        for annotation in getattr(self, "annotations", []):
            if (getattr(annotation, "ANNOTATION_TYPE", "") == "voltage"
                    and getattr(annotation, "_base_angle", None) is None):
                annotation._base_angle = (annotation.angle_deg + step * 90
                                          + (step // 2) * 180) % 360

    def _sync_voltage_annotations(self):
        """Spannungsbögen an die neue Bauteillage anpassen (verzögert).

        Die Szenen-Abfragen (Pol-Mittelpunkt) dürfen nicht im Maus-Dispatch
        laufen (Absturzregel) — daher singleShot. Der Bogen selbst ist kein
        reines Kind-Mitdrehen: gerade Schritte rotieren das Bauteil per Qt
        ((step//2)*180, Kinder drehen mit), ungerade Schritte tauschen die
        Geometrie (Kinder bleiben stehen). Der lokale Bogenwinkel gleicht das
        aus, sodass er visuell um -step*90 wandert (oben, links, unten, rechts).
        """
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, self._sync_voltage_annotations_now)

    def _sync_voltage_annotations_now(self):
        try:
            qt_angle = (self.rotation_step // 2) * 180
            visual = self.rotation_step * 90
            for annotation in list(getattr(self, "annotations", [])):
                if getattr(annotation, "ANNOTATION_TYPE", "") != "voltage":
                    continue
                base = getattr(annotation, "_base_angle", None)
                if base is None:
                    # Basis aus dem VORHERIGEN Schritt herleiten: der aktuelle
                    # Winkel galt noch für die alte Lage. (Mit dem neuen Schritt
                    # gerechnet heben sich die Winkel gegenseitig auf — der
                    # Bogen blieb oben hängen.)
                    prev = (self.rotation_step - 1) % 4
                    base = (annotation.angle_deg + prev * 90
                            + (prev // 2) * 180) % 360
                    annotation._base_angle = base
                # Bogen wandert gegen den Uhrzeigersinn: oben -> links ->
                # unten -> rechts (visuell = base - step*90).
                annotation.set_angle((base - visual - qt_angle) % 360)
                poles = self.get_pole_points()
                if len(poles) == 2:
                    mid = QPointF((poles[0].x() + poles[1].x()) / 2.0,
                                  (poles[0].y() + poles[1].y()) / 2.0)
                    annotation.setPos(self.mapFromScene(mid))
            self._layout_labels()
        except RuntimeError:
            pass  # Bauteil wurde zwischenzeitlich gelöscht

    # ------------------------------------------------------------------
    # Automatisches Beschriftungs-Layout
    # ------------------------------------------------------------------
    #: Abstand Beschriftungsblock <-> Symbolkörper (px)
    LABEL_GAP = 4.0
    #: Mindestabstand Bogenenden <-> Symbolkörper (px)
    ARC_BODY_CLEARANCE = 10.0
    # Seiten im Bildschirm-Sinn: 0 oben, 1 rechts, 2 unten, 3 links
    _SIDE_VECTORS = {0: (0, -1), 1: (1, 0), 2: (0, 1), 3: (-1, 0)}

    def _voltage_arcs(self):
        """Spannungsbögen dieses Bauteils (über die Kind-Items, damit auch ein
        frisch erzeugter, noch nicht registrierter Bogen zählt)."""
        return [child for child in self.childItems()
                if getattr(child, "ANNOTATION_TYPE", "") == "voltage"]

    def _body_rect(self):
        """Lokale Hülle der gezeichneten Symbolteile (ohne Texte)."""
        rect = None
        for item in self.render_items:
            if item["type"] == "line":
                part = QRectF(item["start"], item["end"]).normalized()
            elif item["type"] == "circle":
                r = item["radius"]
                c = item["center"]
                part = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
            else:
                continue
            rect = part if rect is None else rect.united(part)
        return rect if rect is not None else QRectF(self.local_bounding_rect)

    def _label_side(self):
        """Bildschirmseite für den Beschriftungsblock.

        Liegt ein Spannungsbogen am Bauteil, kommt die Beschriftung auf die
        Gegenseite (nie Überschneidung von Bogen, Wert und Name). Ohne Bogen
        gilt die Gegenseite der Standard-Bogenlage — das Setzen eines Bogens
        lässt die Beschriftung damit stehen.
        """
        qt_angle = (self.rotation_step // 2) * 180
        arcs = self._voltage_arcs()
        if arcs:
            arc_side = int(round(((arcs[0].angle_deg + qt_angle) % 360) / 90.0)) % 4
        else:
            arc_side = (-self.rotation_step) % 4
        return (arc_side + 2) % 4

    def _ordered_label_keys(self):
        keys = list(self.placeholder_items.keys())
        if "name" in keys:
            keys.remove("name")
            keys.insert(0, "name")
        return keys

    def _layout_labels(self):
        """Name/Wert als Block ausserhalb des Symbolkörpers anordnen und
        Bögen auf Abstand zum Körper halten. Reine Item-Geometrie (keine
        Szenen-Abfragen) — darf aus Ereignissen heraus laufen."""
        if not hasattr(self, "render_items"):
            return  # noch in BaseComponent.__init__
        body = self._body_rect()
        flip = self.rotation_step >= 2  # Qt dreht das ganze Bauteil um 180°
        visual = (QRectF(-body.right(), -body.bottom(), body.width(), body.height())
                  if flip else QRectF(body))

        keys = self._ordered_label_keys()
        if keys:
            side = self._label_side()
            rects = [self.placeholder_items[k].boundingRect() for k in keys]
            total_h = sum(r.height() for r in rects)
            gap = self.LABEL_GAP
            if side in (0, 2):
                y = (visual.top() - gap - total_h) if side == 0 else (visual.bottom() + gap)
                centers = []
                for r in rects:
                    centers.append(QPointF(visual.center().x(), y + r.height() / 2.0))
                    y += r.height()
            else:
                y = visual.center().y() - total_h / 2.0
                centers = []
                for r in rects:
                    if side == 1:
                        x = visual.right() + gap + r.width() / 2.0
                    else:
                        x = visual.left() - gap - r.width() / 2.0
                    centers.append(QPointF(x, y + r.height() / 2.0))
                    y += r.height()
            for key, rect, center in zip(keys, rects, centers):
                item = self.placeholder_items[key]
                local = QPointF(-center.x(), -center.y()) if flip else center
                standard = local - rect.center()
                item._standard_pos = standard
                item.setTransformOriginPoint(rect.center())
                dx, dy = self.placeholder_offsets.get(key, (0.0, 0.0))
                item._applying_offset = True
                try:
                    item.setPos(standard + QPointF(dx, dy))
                finally:
                    item._applying_offset = False
                grip = getattr(item, "grip", None)
                if grip is not None:
                    grip.setPos(item.mapToParent(QPointF(0.0, 0.0)))

        for arc in self._voltage_arcs():
            setter = getattr(arc, "set_base_offset", None)
            if not callable(setter):
                continue
            direction = arc._rotated(QPointF(0.0, -1.0))
            dx, dy = round(direction.x()), round(direction.y())
            p = arc.pos()
            if dy < 0:
                extent = p.y() - body.top()
            elif dy > 0:
                extent = body.bottom() - p.y()
            elif dx > 0:
                extent = body.right() - p.x()
            else:
                extent = p.x() - body.left()
            from .annotations import ARC_BASE_OFFSET
            setter(max(float(ARC_BASE_OFFSET), extent + self.ARC_BODY_CLEARANCE))

    def _update_placeholder_text(self, key):
        super()._update_placeholder_text(key)
        item = self.placeholder_items.get(key)
        if item is not None:
            item.document().setDocumentMargin(1.0)
        self._layout_labels()

    def setRotation(self, angle):
        """Externen Rotationswinkel auf den nächsten 90°-Schritt abbilden."""
        step = (int(round(angle)) // 90) % 4
        if step == self.rotation_step:
            return
        self.rotation_step = step
        self.orientation = "horizontal" if step % 2 == 0 else "vertical"
        self.apply_orientation()

    def _update_text_orientation(self):
        """Platzhalter und (versteckten) Text aufrecht halten.

        Da die Qt-Rotation nur das 180°-Kippen übernimmt, genügt hier eine
        Gegenrotation um denselben Qt-Winkel, damit die Texte immer waagerecht
        stehen.
        """
        qt_angle = (self.rotation_step // 2) * 180
        if self.text_item:
            self.text_item.setRotation(-qt_angle)
        for item in self.placeholder_items.values():
            item.setRotation(-qt_angle)
        for annotation in self.annotations:
            keep_upright = getattr(annotation, "keep_text_upright", None)
            if callable(keep_upright):
                keep_upright(-qt_angle)

    # ------------------------------------------------------------------
    # Funktionsschema: Schienen dynamischer Länge + Relais-Zuweisung
    # ------------------------------------------------------------------
    def rail_length(self):
        pts = getattr(self, "connection_points", [])
        if len(pts) >= 2:
            return abs(pts[1].x() - pts[0].x())
        return 400.0

    def apply_rail_length(self, length, snap=True):
        """Schiene auf neue Länge bringen (Geometrie ist instanzlokal)."""
        length = max(RAIL_MIN_LENGTH, float(length))
        if snap:
            length = round(length / 20.0) * 20.0
        self.prepareGeometryChange()
        black = QColor(0, 0, 0)
        self.render_items = [
            {"type": "line", "start": QPointF(0, 0), "end": QPointF(length, 0),
             "color": black},
            {"type": "circle", "center": QPointF(0, 0), "radius": 4.0, "color": black},
            {"type": "circle", "center": QPointF(length, 0), "radius": 4.0,
             "color": black},
        ]
        self.connection_points = [QPointF(0, 0), QPointF(length, 0)]
        self._custom_bounding_rect = QRectF(-6, -30, length + 12, 60)
        self.placeholder_values["length"] = str(int(length))
        handle = getattr(self, "rail_handle", None)
        if handle is not None:
            handle.setPos(QPointF(length, 0))
        self.update()

    def _init_fs_extras(self):
        """Nach dem Aufbau: Schienenlänge laden + Endgriffpunkt anlegen."""
        self.rail_handle = None
        if self.symbol_id in RAIL_SYMBOLS:
            length = self.placeholder_values.get("length")
            if length:
                try:
                    self.apply_rail_length(float(length), snap=False)
                except (TypeError, ValueError):
                    pass
            self.rail_handle = RailEndHandle(self)
            self.rail_handle.setPos(QPointF(self.rail_length(), 0))
            self.rail_handle.setVisible(False)

    def _extend_context_menu(self, menu):
        """Relaiskontakt: Zuweisung zur Spule per Rechtsklick (über Namen)."""
        if self.symbol_id not in RELAY_CONTACT_SYMBOLS or not self.scene():
            return
        coils = set()
        for item in self.scene().items():
            if getattr(item, "symbol_id", "") in COIL_SYMBOL_IDS:
                name = str(item.placeholder_values.get("name", "")).strip() or "?"
                coils.add((name, item.symbol_id))
        if not coils:
            return
        submenu = menu.addMenu("Relais zuweisen")
        for name, coil_sid in sorted(coils):
            label = name + (" (Zeitrelais)" if coil_sid == "timer_coil" else "")
            submenu.addAction(label).triggered.connect(
                lambda checked=False, n=name: self._assign_relay(n))

    def _assign_relay(self, name):
        self._push_undo_from_component()
        self.set_placeholder_value("name", name)
        self._refresh_mirrors()

    def _refresh_mirrors(self):
        """Kontakt-Spiegel über die View zum Neuzeichnen anstossen."""
        scene = self.scene()
        if scene is None or not scene.views():
            return
        window = scene.views()[0].window()
        refresh = getattr(window, "refresh_mirrors", None)
        if callable(refresh):
            refresh()

    def mouseDoubleClickEvent(self, event):
        """Allow editing of placeholder values via dialog inputs."""
        keys = list(self.placeholder_items.keys())
        if keys:
            self._push_undo_from_component()
        if keys:
            for key in keys:
                title, prompt = PLACEHOLDER_PROMPTS.get(
                    key, (key.capitalize(), f"{key.capitalize()} eingeben:")
                )
                current_value = self.get_placeholder_value(key)
                value, ok = QInputDialog.getText(None, title, prompt, text=current_value)
                if ok:
                    self.set_placeholder_value(key, value)
            self._refresh_mirrors()
            event.accept()
            return

        super().mouseDoubleClickEvent(event)

    @staticmethod
    def _coerce_color(value):
        if isinstance(value, QColor):
            return QColor(value)
        if isinstance(value, (tuple, list)) and len(value) >= 3:
            return QColor(int(value[0]), int(value[1]), int(value[2]))
        return QColor(0, 0, 0)
