"""
Leitungs-Bauteil zum Verbinden von Schaltungselementen.
"""
from PyQt5.QtWidgets import QGraphicsLineItem, QGraphicsItem, QGraphicsEllipseItem
from PyQt5.QtCore import Qt, QLineF, QPointF
from PyQt5.QtGui import QPen, QColor

WIRE_COLOR_PRESETS = [
    ("Schwarz", (0, 0, 0)),
    ("Rot", (220, 53, 69)),
    ("Gruen", (40, 167, 69)),
    ("Blau", (0, 123, 255)),
]


def _as_qcolor(value):
    """Convert tuples/lists/QColor into a QColor instance."""
    if isinstance(value, QColor):
        return QColor(value)
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        r, g, b = (int(value[0]), int(value[1]), int(value[2]))
        return QColor(r, g, b)
    return QColor(0, 0, 0)


class WireEndHandle(QGraphicsEllipseItem):
    """Griffpunkt an einem Leitungsende (sichtbar bei Auswahl der Leitung).

    Muster analog zum DraggableLineHandle des Symbol-Editors: Ziehen ändert das
    jeweilige Leitungsende, Snapping (Raster + Bauteil-Pole) delegiert der
    Owner (Wire). `is_handle` markiert das Item, damit Serialisierungs- und
    Trefferlogik es überspringen kann.
    """

    is_handle = True

    def __init__(self, owner, radius=5):
        super().__init__(-radius, -radius, radius * 2, radius * 2, owner)
        self.owner = owner
        self.setBrush(QColor(255, 255, 255))
        self.setPen(QPen(QColor(60, 120, 200), 1))
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.SizeAllCursor)
        self.setZValue(20)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            return self.owner.snap_end_handle_position(self, value)
        if change == QGraphicsItem.ItemPositionHasChanged:
            if not self.owner._updating_handles:
                self.owner._end_handle_moved(self)
        return super().itemChange(change, value)


class Wire(QGraphicsLineItem):
    """Leitung/Verbindungslinie mit Enden-Griffpunkten.

    Geometrie-Modell: Die Item-Position bleibt (0,0); `line()` enthält absolute
    Szenen-Koordinaten und `start_point`/`end_point` sind die autoritativen
    Szenen-Endpunkte (Serialisierung, Splitting). Die Griffpunkte liegen als
    Child-Items lokal bei `line().p1()/p2()` und sind nur bei Auswahl aktiv.
    """

    HIGHLIGHT_COLOR = QColor(0, 120, 215)
    BASE_WIDTH = 2

    def __init__(self, start_point, end_point, grid_size=20, color=None):
        super().__init__()
        self.start_point = QPointF(start_point)
        self.end_point = QPointF(end_point)
        self.grid_size = grid_size
        self._color = _as_qcolor(color)
        self._updating_handles = False
        # Messwert-Annotationen (z. B. Strompfeil), Kind-Items dieser Leitung
        self.annotations = []

        self.setLine(QLineF(self.start_point, self.end_point))
        self.setPen(QPen(self._color, self.BASE_WIDTH))

        # selectable and movable for easy editing
        self.setFlag(QGraphicsLineItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsLineItem.ItemIsMovable, True)
        self.setFlag(QGraphicsLineItem.ItemSendsGeometryChanges, True)

        # Enden-Griffpunkte (initial inaktiv, sichtbar erst bei Auswahl)
        self.start_handle = WireEndHandle(self)
        self.end_handle = WireEndHandle(self)
        self._sync_handle_positions()
        self._set_handles_active(False)

    # ------------------------------------------------------------------
    # Enden-Griffpunkte
    # ------------------------------------------------------------------
    def _set_handles_active(self, active):
        """Griffpunkte anzeigen/aktivieren (nur bei Auswahl der Leitung)."""
        buttons = Qt.LeftButton if active else Qt.NoButton
        for handle in (self.start_handle, self.end_handle):
            handle.setVisible(active)
            handle.setEnabled(active)
            handle.setAcceptedMouseButtons(buttons)

    def _sync_handle_positions(self):
        """Griffpunkte auf die aktuellen Linien-Enden setzen (ohne Feedback)."""
        self._updating_handles = True
        try:
            self.start_handle.setPos(self.line().p1())
            self.end_handle.setPos(self.line().p2())
        finally:
            self._updating_handles = False

    def snap_end_handle_position(self, handle, local_point):
        """Zieh-Position eines Griffpunkts einrasten (Raster, dann Bauteil-Pole).

        Zuerst Raster-Snap in Szenen-Koordinaten. Liegt danach ein Pol eines
        Bauteils (kleine Anschlusskreise) in der Nähe, wird magnetisch auf
        diesen Pol eingerastet.
        """
        scene_point = self.mapToScene(local_point)
        snapped = self._snap_to_grid(scene_point)
        pole = self._nearest_component_pole(snapped)
        if pole is not None:
            snapped = QPointF(pole)
        return self.mapFromScene(snapped)

    def _end_handle_moved(self, handle):
        """Gezogenes Leitungsende übernehmen (Raster/Pole-Snap erfolgte schon)."""
        scene_point = self.mapToScene(handle.pos())
        if handle is self.start_handle:
            self.start_point = QPointF(scene_point)
        else:
            self.end_point = QPointF(scene_point)
        self.setLine(QLineF(self.start_point, self.end_point))
        # Nur den gezogenen Griff neu setzen; der andere bleibt am anderen Ende.
        self._updating_handles = True
        try:
            handle.setPos(self.mapFromScene(scene_point))
        finally:
            self._updating_handles = False

    def _nearest_component_pole(self, scene_point):
        """Nächsten Bauteil-Pol innerhalb eines halben Rasters liefern (oder None).

        Duck-Typing über `get_pole_points`, damit wire.py keine Abhängigkeit
        auf SymbolComponent braucht.
        """
        if not self.scene():
            return None
        tolerance = self.grid_size / 2.0
        best = None
        best_dist = tolerance * tolerance
        for item in self.scene().items():
            getter = getattr(item, "get_pole_points", None)
            if not callable(getter) or getattr(item, "is_handle", False):
                continue
            try:
                poles = getter()
            except RuntimeError:
                continue
            for pole in poles:
                dx = pole.x() - scene_point.x()
                dy = pole.y() - scene_point.y()
                dist = dx * dx + dy * dy
                if dist <= best_dist:
                    best = pole
                    best_dist = dist
        return best

    @property
    def color(self):
        """Return the current wire color as QColor."""
        return QColor(self._color)

    def color_rgb(self):
        """Return the current wire color as (r, g, b) tuple."""
        return (self._color.red(), self._color.green(), self._color.blue())

    def set_color(self, color):
        """Update the wire color and refresh rendering."""
        self._color = _as_qcolor(color)
        self.setPen(QPen(self._color, self.BASE_WIDTH))
        self.update()

    # ------------------------------------------------------------------
    # Kontextmenü (Rechtsklick): Farbe wechseln / löschen
    # ------------------------------------------------------------------
    def _main_window(self):
        if self.scene() and self.scene().views():
            return self.scene().views()[0].window()
        return None

    def _push_undo(self):
        push = getattr(self._main_window(), "_push_undo_snapshot", None)
        if callable(push):
            push()

    def contextMenuEvent(self, event):
        from PyQt5.QtWidgets import QMenu
        # Liegt an der Klickposition eine Messwert-Annotation (z. B. der
        # Spannungsbogen des Bauteils unter/über dieser Leitung), hat deren
        # Menü Vorrang — die Annotation selbst stapelt unter der Leitung.
        from src.components.annotations import deliver_context_menu_to_annotation
        if deliver_context_menu_to_annotation(self, event):
            return
        menu = QMenu()
        color_menu = menu.addMenu("Farbe")
        for name, rgb in WIRE_COLOR_PRESETS:
            color_menu.addAction(name).triggered.connect(
                lambda checked=False, c=rgb: self._set_color_with_undo(c))
        menu.addSeparator()
        menu.addAction("Löschen").triggered.connect(self._delete_with_undo)
        menu.exec_(event.screenPos())
        event.accept()

    def _set_color_with_undo(self, rgb):
        self._push_undo()
        self.set_color(rgb)

    def _delete_with_undo(self):
        # Aus dem eigenen Kontextmenü: Szene erst nach dem Ereignis ändern
        # (Absturzregel — wie Bauteil/Bogen).
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, self._delete_now)

    def _delete_now(self):
        try:
            scene = self.scene()
        except RuntimeError:
            return  # bereits zerstört
        if scene is None:
            return
        self._push_undo()
        scene.removeItem(self)

    def update_end_point(self, point):
        """Endpunkt der Leitung aktualisieren (Live-Vorschau beim Zeichnen)."""
        self.end_point = QPointF(point)
        self.setLine(QLineF(self.start_point, self.end_point))
        self._sync_handle_positions()

    def _snap_to_grid(self, point):
        """Punkt zum Raster einrasten."""
        x = round(point.x() / self.grid_size) * self.grid_size
        y = round(point.y() / self.grid_size) * self.grid_size
        return QPointF(x, y)

    def itemChange(self, change, value):
        """Position-Aenderungen mit Grid-Snapping; Griffpunkte bei Auswahl."""
        if (change == QGraphicsItem.ItemPositionChange and self.scene()
                and getattr(self, "_snap_enabled", True)):
            snapped_pos = self._snap_to_grid(value)
            return snapped_pos
        if change == QGraphicsItem.ItemPositionHasChanged:
            line = self.line()
            self.start_point = self.mapToScene(line.p1())
            self.end_point = self.mapToScene(line.p2())
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self._set_handles_active(bool(value))
        return super().itemChange(change, value)

    def paint(self, painter, option, widget):
        """Leitung mit Auswahlhervorhebung zeichnen."""
        base_pen = QPen(self._color, self.BASE_WIDTH)
        base_pen.setCapStyle(Qt.RoundCap)

        if self.isSelected():
            highlight_pen = QPen(self.HIGHLIGHT_COLOR, self.BASE_WIDTH + 2)
            highlight_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(highlight_pen)
            painter.drawLine(self.line())
            base_pen.setWidth(self.BASE_WIDTH + 1)

        painter.setPen(base_pen)
        painter.drawLine(self.line())
