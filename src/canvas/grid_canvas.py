"""
Grid Canvas - Main drawing area with grid and magnetic snapping
"""
import math

from PyQt5.QtWidgets import QGraphicsView, QGraphicsScene
from PyQt5.QtCore import Qt, QPointF, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor, QPolygonF


class GridCanvas(QGraphicsView):
    """Canvas with grid background and magnetic snapping"""

    # Feuert, wenn der Mauszeiger den Zeichenbereich verlässt (z. B. um die
    # halbtransparente Platzierungs-Vorschau zu entfernen).
    mouse_left_canvas = pyqtSignal()
    # Neue Zoomstufe (1.0 = 100 %) — für die Anzeige in der Statusleiste
    zoom_changed = pyqtSignal(float)

    def __init__(self, parent=None, grid_size=20, subdivisions=1):
        super().__init__(parent)
        self.grid_size = grid_size
        self.subdivisions = max(1, subdivisions)
        self.snap_to_subgrid = False
        self.grid_visible = True  # Raster standardmäßig sichtbar

        # Pan mit mittlerer Maustaste
        self._is_panning = False
        self._pan_start_pos = None

        # Cache calculated sizes
        self._minor_grid_size = (
            self.grid_size / self.subdivisions if self.subdivisions > 1 else self.grid_size
        )

        # Grid styling
        self.major_grid_color = QColor(200, 200, 200)
        self.minor_grid_color = QColor(235, 235, 235)
        # "lines" (z. B. Symbol-Editor) oder "dots" (Schaltplan wie EPLAN/KiCad)
        self.grid_style = "lines"
        self.dot_color = QColor(150, 158, 170)
        self.dot_major_color = QColor(95, 105, 120)

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        # Set canvas size - große Arbeitsfläche für Scrolling
        self.scene.setSceneRect(-5000, -5000, 10000, 10000)
        self._zoom_factor = 1.0

        # Configure view
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        # Scrollbars anzeigen wenn nötig
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # Enable drag mode
        self.setDragMode(QGraphicsView.RubberBandDrag)

        # Initial bei Ursprung (0,0) zentrieren
        self.centerOn(0, 0)

    def drawBackground(self, painter, rect):
        """Draw grid background"""
        painter.fillRect(rect, QColor(255, 255, 255))

        # Nur Raster zeichnen wenn sichtbar
        if not self.grid_visible:
            return

        if self.grid_style == "dots":
            self._draw_dot_grid(painter, rect)
            return

        painter.save()

        def draw_grid(step_size, color):
            pen = QPen(color)
            pen.setWidth(1)
            painter.setPen(pen)

            left = math.floor(rect.left() / step_size) * step_size
            top = math.floor(rect.top() / step_size) * step_size

            x = left
            while x <= rect.right():
                painter.drawLine(int(round(x)), int(rect.top()), int(round(x)), int(rect.bottom()))
                x += step_size

            y = top
            while y <= rect.bottom():
                painter.drawLine(int(rect.left()), int(round(y)), int(rect.right()), int(round(y)))
                y += step_size

        # Draw finer grid first so major grid remains visible on top
        if self.subdivisions > 1:
            draw_grid(self._minor_grid_size, self.minor_grid_color)

        draw_grid(self.grid_size, self.major_grid_color)
        painter.restore()

    #: Punktabstand am Bildschirm mindestens (px) — sonst wird ausgedünnt
    MIN_DOT_SPACING_PX = 7.0
    #: Jeder n-te Rasterpunkt etwas kräftiger (Orientierung, 5 × 20 px = 100 px)
    MAJOR_EVERY = 5

    def _draw_dot_grid(self, painter, rect):
        """Punktraster: ein Punkt je Rasterschnittpunkt, jeder fünfte etwas
        kräftiger. Beim Herauszoomen werden die Punkte ausgedünnt, damit das
        Blatt nicht grau wird (und das Zeichnen schnell bleibt)."""
        scale = abs(painter.worldTransform().m11()) or 1.0
        step = float(self.grid_size)
        major = step * self.MAJOR_EVERY
        while step * scale < self.MIN_DOT_SPACING_PX:
            step *= self.MAJOR_EVERY
        painter.save()
        for spacing, color, width, skip_major in (
                (step, self.dot_color, 1.5, step < major),
                (max(step, major), self.dot_major_color, 2.2, False)):
            pen = QPen(color, width)
            pen.setCosmetic(True)          # Punktgrösse unabhängig vom Zoom
            pen.setCapStyle(Qt.RoundCap)   # runde statt quadratische Punkte
            painter.setPen(pen)
            left = math.floor(rect.left() / spacing) * spacing
            top = math.floor(rect.top() / spacing) * spacing
            points = QPolygonF()
            y = top
            while y <= rect.bottom():
                x = left
                on_major_row = abs(y / major - round(y / major)) < 1e-6
                while x <= rect.right():
                    if not (skip_major and on_major_row
                            and abs(x / major - round(x / major)) < 1e-6):
                        points.append(QPointF(x, y))
                    x += spacing
                y += spacing
            painter.drawPoints(points)
        painter.restore()

    def set_grid_style(self, style):
        """'dots' oder 'lines'."""
        self.grid_style = "dots" if style == "dots" else "lines"
        self.viewport().update()

    def set_grid_visible(self, visible):
        """Raster ein-/ausblenden"""
        self.grid_visible = visible
        self.viewport().update()

    def snap_to_grid(self, point, use_minor=None):
        """Snap a point to the nearest grid intersection"""
        if use_minor is None:
            use_minor = self.snap_to_subgrid

        step = self._minor_grid_size if use_minor and self.subdivisions > 1 else self.grid_size
        if step == 0:
            step = self.grid_size

        x = round(point.x() / step) * step
        y = round(point.y() / step) * step
        return QPointF(x, y)

    def set_subdivisions(self, subdivisions):
        """Update subdivision factor and redraw grid"""
        self.subdivisions = max(1, subdivisions)
        self._minor_grid_size = (
            self.grid_size / self.subdivisions if self.subdivisions > 1 else self.grid_size
        )
        self.viewport().update()

    def set_snap_to_subgrid(self, enabled):
        """Toggle snapping to the finer grid"""
        self.snap_to_subgrid = bool(enabled)

    @property
    def minor_grid_size(self):
        """Return the current minor grid size used for subdivisions"""
        return self._minor_grid_size

    def set_zoom_factor(self, factor):
        """Apply a zoom factor to the view"""
        factor = max(0.1, min(10.0, float(factor)))  # Limit zoom: 0.1x to 10x
        if factor == self._zoom_factor:
            return
        self.resetTransform()
        self.scale(factor, factor)
        self._zoom_factor = factor
        self.zoom_changed.emit(factor)

    def wheelEvent(self, event):
        """Zoom mit Mausrad"""
        # Zoom-Faktor berechnen
        zoom_in_factor = 1.15
        zoom_out_factor = 1 / zoom_in_factor

        # Zoom anwenden
        if event.angleDelta().y() > 0:
            # Hineinzoomen
            zoom_factor = zoom_in_factor
        else:
            # Herauszoomen
            zoom_factor = zoom_out_factor

        # Neue Zoom-Stufe berechnen
        new_zoom = self._zoom_factor * zoom_factor
        new_zoom = max(0.1, min(10.0, new_zoom))  # Limit zoom

        # Zoom anwenden mit Mausposition als Zentrum
        old_pos = self.mapToScene(event.pos())
        self.set_zoom_factor(new_zoom)
        new_pos = self.mapToScene(event.pos())
        delta = new_pos - old_pos
        self.translate(delta.x(), delta.y())

    def zoom_in(self):
        """Hineinzoomen um 15%"""
        self.set_zoom_factor(self._zoom_factor * 1.15)

    def zoom_out(self):
        """Herauszoomen um 15%"""
        self.set_zoom_factor(self._zoom_factor / 1.15)

    def zoom_reset(self):
        """Zoom zurücksetzen auf 100%"""
        self.set_zoom_factor(1.0)

    def zoom_to_rect(self, rect, margin=0.9):
        """Bereich (Szenenkoordinaten) einpassen und zentrieren."""
        if rect is None or rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
            self.zoom_reset()
            return
        viewport = self.viewport().rect()
        factor = min(viewport.width() / rect.width(),
                     viewport.height() / rect.height()) * margin
        self.set_zoom_factor(min(factor, 4.0))
        self.centerOn(rect.center())

    def get_visible_scene_rect(self):
        """Gibt den aktuell sichtbaren Bereich der Szene zurück"""
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def mousePressEvent(self, event):
        """Mouse-Press Event für Pan mit mittlerer Maustaste"""
        if event.button() == Qt.MiddleButton:
            # Pan-Modus starten
            self._is_panning = True
            self._pan_start_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Mouse-Move Event für Pan"""
        if self._is_panning:
            # Pan durchführen - Scene-Koordinaten verwenden
            # Aktuelle Mausposition in Scene-Koordinaten
            new_pos = self.mapToScene(event.pos())
            # Start-Position in Scene-Koordinaten
            old_pos = self.mapToScene(self._pan_start_pos)
            # Delta in Scene-Koordinaten
            delta = new_pos - old_pos

            # Aktuellen Center holen und verschieben
            current_center = self.mapToScene(self.viewport().rect().center())
            new_center = current_center - delta

            # View zum neuen Center verschieben
            self.centerOn(new_center)

            # Start-Position für nächsten Frame aktualisieren
            self._pan_start_pos = event.pos()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Mouse-Release Event für Pan"""
        if event.button() == Qt.MiddleButton and self._is_panning:
            # Pan-Modus beenden
            self._is_panning = False
            self._pan_start_pos = None
            self.setCursor(Qt.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        """Maus verlässt den Zeichenbereich -> Vorschau-Aufräumer informieren."""
        self.mouse_left_canvas.emit()
        super().leaveEvent(event)
