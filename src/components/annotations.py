"""
Messwert-Annotationen: Spannungsbogen (blau) und Strompfeil (rot).

Beide sind Kind-Items ihres Zielelements (Bauteil bzw. Leitung) und folgen
damit automatisch beim Verschieben und werden mitgelöscht. Der Wert ist per
Doppelklick frei editierbar (z. B. "20 V", "15 mV", "10 kA").
"""
import math

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (QColor, QPen, QBrush, QPainterPath, QPolygonF,
                         QPainterPathStroker, QTransform)
from PyQt5.QtWidgets import QGraphicsItem, QGraphicsTextItem, QInputDialog, QMenu, QAction, QStyle

VOLTAGE_COLOR = QColor(0, 102, 204)
CURRENT_COLOR = QColor(220, 53, 69)

# Lokale Geometrie (Pixel, unskaliert)
ARC_HALF_WIDTH = 44    # Bogen spannt ±44 px (Passt zum 80-px-Polabstand + Luft)
ARC_HEIGHT = 14        # "Leicht gebogen": Scheitelhöhe des Bogens
ARC_BASE_OFFSET = 34   # Abstand Bogenenden über Bauteilmitte (y negativ = oben)
TRIANGLE_SIZE = 12     # Dreieckshalbe Breite/Höhe des Strompfeils
ARROW_LENGTH = 9       # Kleiner Pfeil am rechten Bogenende
ARROW_WIDTH = 3.5
TEXT_GAP = 3.0         # Abstand Werttext <-> Bogenscheitel/Pfeil
TEXT_MARGIN = 1.0      # Dokumentrand der Textitems (Qt-Standard 4 px wirkt luftig)


def deliver_context_menu_to_annotation(receiver, event):
    """Kontextmenü-Ereignis an eine Annotation unter dem Cursor zustellen.

    Annotationen sind Kind-Items ihres Zielelements und stapeln deshalb
    unter eigenständigen Elementen, die später in die Szene gekommen sind
    (gleiche z-Ebene entscheidet die Einfügereihenfolge — eine Leitung
    über dem Bauteil überdeckt den ganzen Bauteil-Stack inkl. Bogen). Der
    Rechtsklick auf einen Bogen traf so fast immer das fremde Menü. Elemente
    mit eigenem Kontextmenü reichen das Ereignis hier zuerst an eine
    Annotation an der Klickposition weiter. Rueckgabe: zugestellt?
    """
    scene = receiver.scene()
    if scene is None:
        return False
    pos = event.scenePos()
    for item in scene.items(pos):
        if getattr(item, "is_annotation", False) and item is not receiver:
            item.contextMenuEvent(event)
            if event.isAccepted():
                return True
    return False


class _AnnotationText(QGraphicsTextItem):
    """Wert-Text einer Annotation (Doppelklick = bearbeiten).

    Ist die Annotation AUSGEWÄHLT, lässt sich der Text eigenständig ziehen —
    die örtliche Anordnung des Messwerts ist damit frei (Versatz wird
    serialisiert). Nicht ausgewählt: Klicks fallen durch auf die Annotation.
    """

    def __init__(self, annotation, color):
        super().__init__(annotation)
        self.annotation = annotation
        self.setDefaultTextColor(color)
        self.document().setDocumentMargin(TEXT_MARGIN)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.setTextInteractionFlags(Qt.NoTextInteraction)

    def mouseDoubleClickEvent(self, event):
        self.annotation.edit_value()
        event.accept()

    def mousePressEvent(self, event):
        if not self.annotation.isSelected():
            event.ignore()
            return
        super().mousePressEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            # Der Text gehört zur Bounding-Rect der Annotation — Verschieben
            # muss die Geometrie-Ankündigung auslösen (nur Struktur, keine
            # Szenen-Abfragen: absturzsicher im Maus-Dispatch).
            self.annotation.prepareGeometryChange()
            self.annotation.update()
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.annotation._commit_text_offset()


class BaseAnnotation(QGraphicsItem):
    """Gemeinsame Basis: Wert, Textposition, Bearbeiten, Kontextmenü."""

    is_annotation = True

    def __init__(self, parent_item):
        super().__init__(parent_item)
        self.value = ""
        self._text_offset = QPointF(0.0, 0.0)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setZValue(8)
        self._press_pos = None
        self.text_item = _AnnotationText(self, self.text_color())
        self._update_text()
        # Auf einem bereits um 180° gedrehten Bauteil (Platzieren, Laden,
        # Einfügen) sofort gegenrotieren — reine Item-Eigenschaft, keine
        # Szenen-Abfrage.
        if parent_item is not None:
            self.keep_text_upright(-parent_item.rotation())

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            # Wert-Text erst bei ausgewählter Annotation greifbar machen
            # (gleiches Muster wie Bauteil-Beschriftungen).
            self.text_item.setFlag(QGraphicsItem.ItemIsMovable, bool(value))
        return super().itemChange(change, value)

    # -- von Unterklassen ------------------------------------------------
    def text_color(self):
        raise NotImplementedError

    def text_anchor(self):
        """Szene-lokaler Ankerpunkt (relativ zum Annotation-Item) für den Text."""
        return QPointF(0, 0)

    # -- API ---------------------------------------------------------------
    def set_value(self, value):
        self.value = value or ""
        self._update_text()

    def edit_value(self):
        title, prompt = self.edit_prompt()
        self._request_undo()
        value, ok = QInputDialog.getText(None, title, prompt, text=self.value)
        if ok:
            self.set_value(value)

    def _request_undo(self):
        """Undo-Snapshot über das Hauptfenster des Zielelements anstossen."""
        target = self.parentItem()
        getter = getattr(target, "_push_undo_from_component", None)
        if callable(getter):
            getter()
        elif isinstance(target, QGraphicsItem) and target.scene() and target.scene().views():
            top = target.scene().views()[0].window()
            push = getattr(top, "_push_undo_snapshot", None)
            if callable(push):
                push()

    def _update_text(self):
        self.text_item.setPlainText(self.value)
        anchor = self.text_anchor() + self._text_offset
        rect = self.text_item.boundingRect()
        self.text_item.setPos(anchor.x() - rect.width() / 2.0,
                              anchor.y() - rect.height() / 2.0)
        # Gegenrotation um die Textmitte: sonst schwenkt der Text um seine
        # linke obere Ecke und springt bei 180° vom Anker weg.
        self.text_item.setTransformOriginPoint(rect.center())
        self.prepareGeometryChange()

    def _commit_text_offset(self):
        """Versatz des Wert-Texts nach dem Ziehen übernehmen."""
        rect = self.text_item.boundingRect()
        centered = self.text_anchor() + QPointF(-rect.width() / 2.0,
                                                -rect.height() / 2.0)
        self._text_offset = self.text_item.pos() - centered
        self._request_undo()

    def set_text_offset(self, dx, dy):
        self._text_offset = QPointF(float(dx), float(dy))
        self._update_text()

    def _reset_text_offset(self):
        self._request_undo()
        self._text_offset = QPointF(0.0, 0.0)
        self._update_text()

    def keep_text_upright(self, angle):
        """Wert-Text gegen die Drehung des Zielelements rotieren."""
        self.text_item.setRotation(angle)

    # -- Auswahl & Ziehen --------------------------------------------------
    def mousePressEvent(self, event):
        self._press_pos = QPointF(self.pos())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        # Verschieben der Annotation ist undo-fähig: Snapshot erst am Ende
        # des Zugs (wie bei den Leitungsenden-Griffpunkten — niemals während
        # des Dispatchs serialisieren).
        if self._press_pos is not None and self.pos() != self._press_pos:
            self._request_undo()
        self._press_pos = None

    def _paint_selection_hint(self, painter, option):
        """Gestrichelter Rahmen, wenn die Annotation ausgewählt ist."""
        if option.state & QStyle.State_Selected:
            hint = QPen(QColor(120, 170, 255, 180), 1, Qt.DashLine)
            painter.setPen(hint)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.boundingRect().adjusted(1, 1, -1, -1))

    def _text_hit_path(self):
        path = QPainterPath()
        path.addRect(QRectF(self.text_item.pos(), self.text_item.boundingRect().size()))
        return path

    def contextMenuEvent(self, event):
        menu = QMenu()
        edit_action = QAction("Wert bearbeiten", menu)
        edit_action.triggered.connect(self.edit_value)
        menu.addAction(edit_action)
        self._extend_context_menu(menu)
        if self._text_offset.manhattanLength() > 0.5:
            reset = QAction("Textposition zurücksetzen", menu)
            reset.triggered.connect(self._reset_text_offset)
            menu.addAction(reset)
        menu.addSeparator()
        delete_action = QAction("Löschen", menu)
        delete_action.triggered.connect(self.delete_later)
        menu.addAction(delete_action)
        menu.exec_(event.screenPos())
        event.accept()

    def _text_offset_dict(self):
        if self._text_offset.manhattanLength() > 0.5:
            return [round(self._text_offset.x(), 1), round(self._text_offset.y(), 1)]
        return None

    def _extend_context_menu(self, menu):
        pass

    def delete_later(self, checked=False):
        # Aus dem eigenen Kontextmenü: Szene erst nach dem Ereignis ändern.
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, self._delete_now)

    def _delete_now(self):
        try:
            if self.scene() is None:
                return
        except RuntimeError:
            return
        self._request_undo()
        if self.scene():
            # Sicherheitshalber erst aus Registry des Bauteils entfernen.
            parent = self.parentItem()
            registry = getattr(parent, "annotations", None)
            if registry is not None and self in registry:
                registry.remove(self)
            self.scene().removeItem(self)
            relayout = getattr(parent, "_layout_labels", None)
            if callable(relayout):
                relayout()


class VoltageAnnotation(BaseAnnotation):
    """Blauer, leicht gebogener Spannungsbogen über einem Bauteil.

    `flipped` spiegelt den Bogen: der Messpfeil sitzt dann am linken statt
    am rechten Ende (Messrichtung umkehren). `angle` dreht den Bogen in
    90°-Schritten (0 = über dem Bauteil, 90 = rechts, 270 = links daneben —
    links ist die Standardlage für vertikal stehende Bauteile). Der Wert-Text bleibt stets aufrecht.
    """

    ANNOTATION_TYPE = "voltage"

    def __init__(self, parent_item, value="U", flipped=False, angle=0.0):
        self.flipped = bool(flipped)
        # Früh setzen: BaseAnnotation.__init__ ruft bereits text_anchor() auf.
        self.angle_deg = float(angle) % 360.0
        # Abstand Bogenenden <-> Bauteilachse; das Bauteil vergrössert ihn,
        # wenn der Symbolkörper (z. B. Messgerät, Taster) höher ist.
        self.base_offset = float(ARC_BASE_OFFSET)
        super().__init__(parent_item)
        self.set_value(value)
        self._notify_parent_layout()

    def _notify_parent_layout(self):
        """Bauteil-Beschriftungen auf die Gegenseite des Bogens legen."""
        relayout = getattr(self.parentItem(), "_layout_labels", None)
        if callable(relayout):
            relayout()

    def set_base_offset(self, offset):
        offset = float(offset)
        if abs(offset - self.base_offset) < 0.01:
            return
        self.prepareGeometryChange()
        self.base_offset = offset
        self._update_text()
        self.update()

    def text_color(self):
        return VOLTAGE_COLOR

    def edit_prompt(self):
        return ("Spannung", "Spannungswert eingeben (z. B. 20 V, 15 mV, 10 kV):")

    def set_flipped(self, flipped):
        self.flipped = bool(flipped)
        self.prepareGeometryChange()
        self.update()

    def set_angle(self, angle):
        self.angle_deg = float(angle) % 360.0
        self.prepareGeometryChange()
        self._update_text()
        self.update()
        self._notify_parent_layout()

    def _rotate_step(self, checked=False):
        # Gleiche Richtung wie die Bauteil-Synchronisation: visuell gegen den
        # Uhrzeigersinn (oben -> links -> unten -> rechts). Die gemerkte Basis
        # verwerfen, damit das nächste Bauteil-Drehen von dieser Lage ausgeht.
        self._request_undo()
        self.rotate_quarter()

    def rotate_quarter(self):
        """Bogen eine Vierteldrehung weiter (ohne Undo-Schritt)."""
        self._base_angle = None
        self.set_angle(self.angle_deg - 90.0)

    def _mirror(self):
        return -1.0 if self.flipped else 1.0

    def _rotated(self, point):
        rad = math.radians(self.angle_deg)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        return QPointF(point.x() * cos_a - point.y() * sin_a,
                       point.x() * sin_a + point.y() * cos_a)

    def boundingRect(self):
        rect = QRectF(-ARC_HALF_WIDTH - 5, -self.base_offset - ARC_HEIGHT - 5,
                      ARC_HALF_WIDTH * 2 + 10, ARC_HEIGHT + self.base_offset + 10)
        corners = [self._rotated(c) for c in (
            rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight())]
        xs = [p.x() for p in corners]
        ys = [p.y() for p in corners]
        rot_rect = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        text_rect = QRectF(self.text_item.pos(), self.text_item.boundingRect().size())
        return rot_rect.united(text_rect)

    def shape(self):
        """Trefferfläche = gesamte Bogenfläche (bis zur Bauteilachse) + Text.

        Nur die Bogenlinie selbst wäre kaum treffbar — der Bereich zwischen
        Bauteil und Bogen gehört sichtbar zur Annotation und muss klickbar
        sein (Rechtsklick/Auswahl).
        """
        m = self._mirror()
        base = -self.base_offset
        path = QPainterPath()
        path.moveTo(m * -ARC_HALF_WIDTH, 0.0)
        path.lineTo(m * -ARC_HALF_WIDTH, base)
        path.quadTo(0.0, base - ARC_HEIGHT * 2, m * ARC_HALF_WIDTH, base)
        path.lineTo(m * ARC_HALF_WIDTH, 0.0)
        path.closeSubpath()
        rotated = QTransform().rotate(self.angle_deg).map(path)
        return rotated.united(self._text_hit_path())

    def text_anchor(self):
        # Werttext aussen am Bogenscheitel (Scheitel = base + ARC_HEIGHT),
        # mit festem Abstand von der Textkante statt von der Textmitte —
        # breite Werte («230 V») ragen sonst seitlich in den Bogen.
        rect = self.text_item.boundingRect()
        direction = self._rotated(QPointF(0.0, -1.0))
        horizontal = abs(direction.x()) > abs(direction.y())
        half = rect.width() / 2.0 if horizontal else rect.height() / 2.0
        distance = self.base_offset + ARC_HEIGHT + TEXT_GAP + half
        return QPointF(round(direction.x()) * distance, round(direction.y()) * distance)

    def paint(self, painter, option, widget):
        self._paint_selection_hint(painter, option)
        pen = QPen(VOLTAGE_COLOR, 2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.save()
        painter.rotate(self.angle_deg)
        path = QPainterPath()
        base = -self.base_offset
        m = self._mirror()
        path.moveTo(m * -ARC_HALF_WIDTH, base)
        path.quadTo(0.0, base - ARC_HEIGHT * 2, m * ARC_HALF_WIDTH, base)
        painter.drawPath(path)
        # Kleiner Pfeil am Bogenende (standardmäßig rechts), in Kurvenrichtung
        # nach unten aufs Bauteil weisend — Messpfeil-Konvention.
        end = QPointF(m * ARC_HALF_WIDTH, base)
        ctrl = QPointF(0.0, base - ARC_HEIGHT * 2)
        tangent = end - ctrl
        norm = math.hypot(tangent.x(), tangent.y())
        if norm > 0:
            tangent = QPointF(tangent.x() / norm, tangent.y() / norm)
            perp = QPointF(-tangent.y(), tangent.x())
            wing1 = QPointF(end.x() - tangent.x() * ARROW_LENGTH + perp.x() * ARROW_WIDTH,
                            end.y() - tangent.y() * ARROW_LENGTH + perp.y() * ARROW_WIDTH)
            wing2 = QPointF(end.x() - tangent.x() * ARROW_LENGTH - perp.x() * ARROW_WIDTH,
                            end.y() - tangent.y() * ARROW_LENGTH - perp.y() * ARROW_WIDTH)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(VOLTAGE_COLOR))
            painter.drawPolygon(QPolygonF([end, wing1, wing2]))
        painter.restore()

    def _extend_context_menu(self, menu):
        # Aktionen gehören dem Menü: ohne Eltern-Objekt räumt Python sie beim
        # Verlassen dieser Methode ab und sie fehlen im Menü (war der Fall).
        flip = QAction("Richtung umkehren\tU", menu)
        flip.triggered.connect(self._flip_direction)
        menu.addAction(flip)
        rotate = QAction("Bogen drehen (90°)\tR", menu)
        rotate.triggered.connect(self._rotate_step)
        menu.addAction(rotate)

    def _flip_direction(self, checked=False):
        self._request_undo()
        self.reverse()

    def reverse(self):
        """Messrichtung umkehren: Pfeilspitze ans andere Bogenende
        (ohne Undo-Schritt)."""
        self.set_flipped(not self.flipped)

    def to_dict(self):
        data = {"type": self.ANNOTATION_TYPE,
                "x": float(self.x()), "y": float(self.y()),
                "value": self.value}
        if self.flipped:
            data["flip"] = True
        if self.angle_deg:
            data["angle"] = round(self.angle_deg, 1)
        offset = self._text_offset_dict()
        if offset:
            data["text_offset"] = offset
        return data


class CurrentAnnotation(BaseAnnotation):
    """Roter Pfeil (gefülltes Dreieck) auf einer Leitung."""

    ANNOTATION_TYPE = "current"

    def __init__(self, parent_wire, value="I", angle=0.0):
        # Früh setzen: BaseAnnotation.__init__ ruft bereits text_anchor() auf.
        self.angle_deg = float(angle) % 360.0
        super().__init__(parent_wire)
        self.set_value(value)

    def text_color(self):
        return CURRENT_COLOR

    def edit_prompt(self):
        return ("Strom", "Stromwert eingeben (z. B. 20 A, 15 mA, 10 kA):")

    def set_angle(self, angle):
        self.angle_deg = float(angle) % 360.0
        self.prepareGeometryChange()
        self._update_text()   # Textanker hängt von der Pfeilrichtung ab
        self.update()

    def _triangle_points(self):
        """Dreieck symmetrisch um den Ursprung, Spitze in +x-Richtung.

        Spitze und Basis liegen gleich weit vom Anker entfernt — der Anker
        (die projizierte Klickstelle auf der Leitung) ist damit die optische
        Mitte des Pfeils und die Spitze sitzt exakt auf der Leitungsachse.
        """
        return [
            QPointF(TRIANGLE_SIZE, 0.0),
            QPointF(-TRIANGLE_SIZE, -TRIANGLE_SIZE * 0.7),
            QPointF(-TRIANGLE_SIZE, TRIANGLE_SIZE * 0.7),
        ]

    def _rotated(self, point):
        rad = math.radians(self.angle_deg)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        return QPointF(point.x() * cos_a - point.y() * sin_a,
                       point.x() * sin_a + point.y() * cos_a)

    def boundingRect(self):
        pts = [self._rotated(p) for p in self._triangle_points()]
        xs = [p.x() for p in pts] + [0]
        ys = [p.y() for p in pts] + [0]
        rect = QRectF(min(xs) - 2, min(ys) - 2,
                      max(xs) - min(xs) + 4, max(ys) - min(ys) + 4)
        text_rect = QRectF(self.text_item.pos(), self.text_item.boundingRect().size())
        return rect.united(text_rect)

    def shape(self):
        """Trefferfläche = Pfeildreieck (mit Griff-Toleranz) + Textbereich."""
        path = QPainterPath()
        path.addPolygon(QPolygonF([self._rotated(p) for p in self._triangle_points()]))
        path.closeSubpath()
        stroker = QPainterPathStroker()
        stroker.setWidth(8)
        return stroker.createStroke(path).united(path).united(self._text_hit_path())

    def text_anchor(self):
        # Feste Seite unabhängig von der Pfeilrichtung (Richtung drehen lässt
        # den Wert stehen): über waagrechten, rechts neben senkrechten
        # Leitungen — mit Kantenabstand, damit breite Werte nie die Leitung
        # oder den Pfeil schneiden.
        rad = math.radians(self.angle_deg)
        rect = self.text_item.boundingRect()
        clearance = TRIANGLE_SIZE * 0.7 + TEXT_GAP
        if abs(math.cos(rad)) >= abs(math.sin(rad)):
            return QPointF(0.0, -(clearance + rect.height() / 2.0))
        return QPointF(clearance + rect.width() / 2.0, 0.0)

    def paint(self, painter, option, widget):
        self._paint_selection_hint(painter, option)
        painter.setPen(QPen(CURRENT_COLOR, 1))
        painter.setBrush(QBrush(CURRENT_COLOR))
        polygon = QPolygonF([self._rotated(p) for p in self._triangle_points()])
        painter.drawPolygon(polygon)

    def _extend_context_menu(self, menu):
        flip = QAction("Richtung umkehren\tU", menu)
        flip.triggered.connect(self._flip_direction)
        menu.addAction(flip)

    def _flip_direction(self, checked=False):
        self._request_undo()
        self.reverse()

    def reverse(self):
        """Pfeil umkehren (ohne Undo — der Aufrufer legt den Schritt ab)."""
        self.set_angle(self.angle_deg + 180.0)

    def to_dict(self):
        # Szenen-Koordinaten: die Leitung speichert nur absolute Endpunkte,
        # ihre Item-Position aber nicht — lokale Koordinaten wären verlustbehaftet.
        # Rechnerisch statt mapToScene: wird u. U. innerhalb des Maus-Press-
        # Dispatchs aufgerufen, wo Szenen-Abfragen zum Absturz führen können.
        # Leitungen sind nie rotiert/skaliert: Szene = Item-Position + lokale Position.
        parent = self.parentItem()
        if parent is not None:
            scene_pos = parent.pos() + QPointF(self.x(), self.y())
        else:
            scene_pos = QPointF(self.x(), self.y())
        data = {"type": self.ANNOTATION_TYPE,
                "x": float(scene_pos.x()), "y": float(scene_pos.y()),
                "angle": self.angle_deg, "value": self.value}
        offset = self._text_offset_dict()
        if offset:
            data["text_offset"] = offset
        return data