"""
Symbol Editor - allows drawing custom symbols with fine-grained grid,
including orientation-specific layouts and text placeholders.
"""
import copy
import json
import math
from pathlib import Path

from PyQt5.QtCore import QPointF, Qt, QRectF, QLineF, QTimer
from PyQt5.QtGui import (QColor, QKeySequence, QPen, QPainterPath,
                         QPainterPathStroker, QPainter)
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QShortcut,
    QVBoxLayout,
    QInputDialog,
    QApplication,
)

from ..canvas.grid_canvas import GridCanvas
from ..components.wire import WIRE_COLOR_PRESETS
from ..symbols import SYMBOLS_DIR


def derive_rotated_orientation(data, clockwise=False):
    """Orientierungs-Daten um 90 Grad drehen (reine Funktion, ohne Qt).

    Gegen den Uhrzeigersinn (Standard) bildet die Drehung (x, y) -> (-y, x)
    den linken Pol auf den oberen ab: horizontal -> vertical. Fuer den
    Rueckweg (vertical -> horizontal) wird im Uhrzeigersinn gedreht,
    (x, y) -> (y, -x). Bounds werden nicht mitgedreht — der Editor berechnet
    sie beim Speichern neu.
    """
    def rot(point):
        x, y = float(point[0]), float(point[1])
        return [y, -x] if clockwise else [-y, x]

    def rot_item(item):
        item = dict(item)
        if item.get("type") == "line":
            item["start"] = rot(item["start"])
            item["end"] = rot(item["end"])
        elif item.get("type") == "circle":
            item["center"] = rot(item["center"])
        return item

    def rot_placeholder(placeholder):
        placeholder = dict(placeholder)
        placeholder["position"] = rot(placeholder.get("position", [0, 0]))
        return placeholder

    return {
        "items": [rot_item(i) for i in data.get("items", [])],
        "placeholders": [rot_placeholder(ph) for ph in data.get("placeholders", [])],
        "connection_points": [rot(pt) for pt in data.get("connection_points", [])],
        "origin": rot(data.get("origin", [0.0, 0.0])),
    }


PLACEHOLDER_LABELS = {
    "name": "Name",
    "voltage": "Spannung",
    "current": "Strom",
    "resistance": "Widerstand",
}

PLACEHOLDER_DISPLAY = {
    "name": "[Name]",
    "voltage": "[Spannung]",
    "current": "[Strom]",
    "resistance": "[Widerstand]",
}


class EditableHandle(QGraphicsEllipseItem):
    """Generic draggable handle that snaps to the editor grid."""

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
        if getattr(self.owner, "_updating_handles", False) or getattr(self.owner, "_updating_radius_handle", False):
            return value if change == QGraphicsItem.ItemPositionChange else super().itemChange(change, value)
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            snapped_local = self.owner.snap_handle_position(self, value)
            return snapped_local
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.owner.handle_moved(self)
        return super().itemChange(change, value)


class DraggableLineHandle(EditableHandle):
    """Handle for moving a line endpoint without moving the line item."""

    def itemChange(self, change, value):
        if not self.isVisible():
            return super().itemChange(change, value)
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            snapped_local = self.owner.snap_handle_position(self, value)
            return snapped_local
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.owner.handle_moved(self)
        return super().itemChange(change, value)


class SymbolLineItem(QGraphicsItem):
    """Editable line item with draggable endpoints."""

    HIGHLIGHT_COLOR = QColor(0, 120, 215)
    LINE_WIDTH = 2

    def __init__(self, start_point, end_point=None, grid_step=1.0, color=None):
        super().__init__()
        self.grid_step = grid_step or 1.0
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

        if end_point is None:
            end_point = QPointF(start_point)

        self._start_scene = QPointF(start_point)
        self._end_scene = QPointF(end_point)
        self._line = QLineF(self._start_scene, self._end_scene)
        self._suppress_position_change = False
        self._updating_handles = False
        self._color = self._coerce_color(color)

        self.start_handle = DraggableLineHandle(self)
        self.start_handle.setCursor(Qt.SizeAllCursor)
        self.end_handle = DraggableLineHandle(self)
        self.end_handle.setCursor(Qt.SizeAllCursor)
        self._recalculate_geometry()
        self._set_handles_active(False)

    def boundingRect(self):
        pen_width = self.LINE_WIDTH + 2
        rect = QRectF(self.start_handle.pos(), self.end_handle.pos()).normalized()
        rect = rect.adjusted(-pen_width, -pen_width, pen_width, pen_width)
        return rect

    def shape(self):
        path = QPainterPath()
        path.moveTo(self.start_handle.pos())
        path.lineTo(self.end_handle.pos())
        stroker = QPainterPathStroker()
        stroker.setWidth(6)
        return stroker.createStroke(path)

    def paint(self, painter: QPainter, option, widget=None):
        base_pen = QPen(self._color, self.LINE_WIDTH)
        base_pen.setCapStyle(Qt.RoundCap)

        if self.isSelected():
            highlight_pen = QPen(self.HIGHLIGHT_COLOR, self.LINE_WIDTH + 2)
            highlight_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(highlight_pen)
            painter.drawLine(self.start_handle.pos(), self.end_handle.pos())
            base_pen.setWidth(self.LINE_WIDTH + 1)

        painter.setPen(base_pen)
        painter.drawLine(self.start_handle.pos(), self.end_handle.pos())

    def snap_scene_point(self, point: QPointF) -> QPointF:
        step = self.grid_step
        x = round(point.x() / step) * step
        y = round(point.y() / step) * step
        return QPointF(x, y)

    def snap_handle_position(self, handle, local_point: QPointF) -> QPointF:
        scene_point = self.mapToScene(local_point)
        snapped_scene = self.snap_scene_point(scene_point)
        return self.mapFromScene(snapped_scene)

    def handle_moved(self, handle):
        scene_point = self.mapToScene(handle.pos())
        if handle is self.start_handle:
            self._start_scene = self.snap_scene_point(scene_point)
        elif handle is self.end_handle:
            self._end_scene = self.snap_scene_point(scene_point)
        self._recalculate_geometry()
        if self.scene():
            self.scene().editor_dialog.mark_modified()

    def update_end_point(self, scene_point):
        self._end_scene = self.snap_scene_point(scene_point)
        self._recalculate_geometry()

    def scene_start(self):
        return QPointF(self._start_scene)

    def scene_end(self):
        return QPointF(self._end_scene)

    def to_dict(self):
        start = self.scene_start()
        end = self.scene_end()
        return {
            "type": "line",
            "start": [start.x(), start.y()],
            "end": [end.x(), end.y()],
            "color": list(self.color_rgb()),
        }

    def _recalculate_geometry(self):
        center = QPointF(
            (self._start_scene.x() + self._end_scene.x()) / 2.0,
            (self._start_scene.y() + self._end_scene.y()) / 2.0,
        )
        local_start = self._start_scene - center
        local_end = self._end_scene - center

        self._suppress_position_change = True
        self.setPos(center)
        self._suppress_position_change = False

        self.prepareGeometryChange()
        self._updating_handles = True
        self.start_handle.setPos(local_start)
        self.end_handle.setPos(local_end)
        self._updating_handles = False
        self._line = QLineF(local_start, local_end)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene() and not self._suppress_position_change:
            delta = value - self.pos()
            if not delta.isNull():
                self._start_scene += delta
                self._end_scene += delta
            snapped = self.snap_scene_point(value)
            delta_snap = snapped - value
            if not delta_snap.isNull():
                self._start_scene += delta_snap
                self._end_scene += delta_snap
            return snapped
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self._set_handles_active(bool(value))
        return super().itemChange(change, value)

    @staticmethod
    def from_dict(data, grid_step):
        start = QPointF(*data["start"])
        end = QPointF(*data["end"])
        color = data.get("color")
        return SymbolLineItem(start, end, grid_step, color=color)

    def _set_handles_active(self, active: bool):
        buttons = Qt.LeftButton if active else Qt.NoButton
        for handle in (self.start_handle, self.end_handle):
            handle.setVisible(active)
            handle.setEnabled(active)
            handle.setAcceptedMouseButtons(buttons)

    @staticmethod
    def _coerce_color(value):
        if isinstance(value, QColor):
            return QColor(value)
        if isinstance(value, (tuple, list)) and len(value) >= 3:
            r, g, b = (int(value[0]), int(value[1]), int(value[2]))
            return QColor(r, g, b)
        return QColor(0, 0, 0)

    def set_line_color(self, color):
        """Update line color and redraw."""
        self._color = self._coerce_color(color)
        self.update()

    def color_rgb(self):
        """Return the color as (r, g, b) tuple."""
        return (self._color.red(), self._color.green(), self._color.blue())


class CircleRadiusHandle(EditableHandle):
    """Handle dedicated to adjusting circle radius."""

    def __init__(self, owner, radius=5):
        super().__init__(owner, radius)
        self.setCursor(Qt.OpenHandCursor)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            snapped_local = self.owner.snap_handle_position(self, value)
            return snapped_local
        if change == QGraphicsItem.ItemPositionHasChanged:
            if not getattr(self.owner, "_updating_radius_handle", False):
                self.owner.radius_handle_moved(self)
        return super().itemChange(change, value)


class SymbolCircleItem(QGraphicsItem):
    """Editable circle with draggable radius handle."""

    def __init__(self, center_point, grid_step=1.0, radius=0):
        super().__init__()
        self.grid_step = grid_step or 1.0
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

        self._center_scene = QPointF(center_point)
        self._radius = max(radius, self.grid_step)
        self._suppress_position_change = False
        self._updating_radius_handle = False

        self.radius_handle = CircleRadiusHandle(self)
        self.radius_handle.setBrush(QColor(255, 255, 255))
        self.radius_handle.setPen(QPen(QColor(200, 100, 0), 1))
        self._recalculate_geometry()
        self._set_handle_active(False)

    def boundingRect(self):
        margin = 6
        return QRectF(
            -self._radius - margin,
            -self._radius - margin,
            2 * (self._radius + margin),
            2 * (self._radius + margin),
        )

    def shape(self):
        path = QPainterPath()
        path.addEllipse(QPointF(0, 0), self._radius, self._radius)
        return path

    def paint(self, painter: QPainter, option, widget=None):
        pen = QPen(QColor(0, 0, 0), 2)
        if self.isSelected():
            pen.setColor(QColor(0, 120, 215))
            pen.setWidth(3)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(0, 0), self._radius, self._radius)

    def snap_scene_point(self, point: QPointF) -> QPointF:
        step = self.grid_step
        x = round(point.x() / step) * step
        y = round(point.y() / step) * step
        return QPointF(x, y)

    def snap_handle_position(self, handle, local_point: QPointF) -> QPointF:
        scene_point = self.mapToScene(local_point)
        snapped_scene = self.snap_scene_point(scene_point)
        return self.mapFromScene(snapped_scene)

    def radius_handle_moved(self, handle):
        local = handle.pos()
        length = math.hypot(local.x(), local.y())
        if length == 0:
            direction = QPointF(1, 0)
        else:
            direction = QPointF(local.x() / length, local.y() / length)
        radius = max(length, self.grid_step)
        radius = round(radius / self.grid_step) * self.grid_step
        self._radius = radius
        self._recalculate_geometry(update_handle=False)
        new_local = QPointF(direction.x() * self._radius, direction.y() * self._radius)
        self._updating_radius_handle = True
        try:
            self.radius_handle.setPos(new_local)
        finally:
            self._updating_radius_handle = False
        if self.scene():
            self.scene().editor_dialog.mark_modified()

    def set_radius_from_point(self, scene_point):
        snapped = self.snap_scene_point(scene_point)
        vec = snapped - self._center_scene
        radius = math.hypot(vec.x(), vec.y())
        radius = max(radius, self.grid_step)
        radius = round(radius / self.grid_step) * self.grid_step
        self._radius = radius
        self._recalculate_geometry()

    def set_center_scene(self, point):
        self._center_scene = self.snap_scene_point(point)
        self._recalculate_geometry()

    def scene_center(self):
        return QPointF(self._center_scene)

    def radius(self):
        return float(self._radius)

    def to_dict(self):
        center = self.scene_center()
        return {
            "type": "circle",
            "center": [center.x(), center.y()],
            "radius": self.radius(),
        }

    def _recalculate_geometry(self, update_handle=True):
        self._suppress_position_change = True
        self.setPos(self._center_scene)
        self._suppress_position_change = False
        if update_handle:
            self._updating_radius_handle = True
            self.radius_handle.setPos(QPointF(self._radius, 0))
            self._updating_radius_handle = False
        self.prepareGeometryChange()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene() and not self._suppress_position_change:
            snapped = self.snap_scene_point(value)
            return snapped
        if change == QGraphicsItem.ItemPositionHasChanged and not self._suppress_position_change:
            self._center_scene = self.pos()
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self._set_handle_active(bool(value))
        return super().itemChange(change, value)

    @staticmethod
    def from_dict(data, grid_step):
        center = QPointF(*data["center"])
        radius = data["radius"]
        return SymbolCircleItem(center, grid_step, radius)

    def _set_handle_active(self, active: bool):
        buttons = Qt.LeftButton if active else Qt.NoButton
        self.radius_handle.setVisible(active)
        self.radius_handle.setEnabled(active)
        self.radius_handle.setAcceptedMouseButtons(buttons)


class SymbolPlaceholderItem(QGraphicsTextItem):
    """Placeholder text marker that snaps its center to the grid."""

    def __init__(self, key, position, grid_step=1.0, alignment="center"):
        super().__init__(PLACEHOLDER_DISPLAY.get(key, f"[{key}]"))
        self.key = key
        self.grid_step = grid_step
        self.alignment = alignment
        self.setDefaultTextColor(QColor(60, 60, 60))
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setZValue(5)

        self._center = QPointF(position[0], position[1])
        self._apply_center()

    def _apply_center(self):
        rect = self.boundingRect()
        self.setPos(self._center.x() - rect.width() / 2.0, self._center.y() - rect.height() / 2.0)

    def _snap_point(self, point):
        step = self.grid_step if self.grid_step else 1.0
        x = round(point.x() / step) * step
        y = round(point.y() / step) * step
        return QPointF(x, y)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            rect = self.boundingRect()
            center = QPointF(value.x() + rect.width() / 2.0, value.y() + rect.height() / 2.0)
            snapped_center = self._snap_point(center)
            new_pos = QPointF(
                snapped_center.x() - rect.width() / 2.0,
                snapped_center.y() - rect.height() / 2.0,
            )
            return new_pos
        if change == QGraphicsItem.ItemPositionHasChanged:
            rect = self.boundingRect()
            center = QPointF(self.pos().x() + rect.width() / 2.0, self.pos().y() + rect.height() / 2.0)
            self._center = self._snap_point(center)
            if self.scene():
                self.scene().editor_dialog.mark_modified()
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        parent = self.parentItem()
        if parent and hasattr(parent, "set_placeholder_value"):
            title = PLACEHOLDER_LABELS.get(self.key, self.key.capitalize())
            prompt = f"{title} eingeben:"
            current_value = ""
            if hasattr(parent, "get_placeholder_value"):
                current_value = parent.get_placeholder_value(self.key)
            value, ok = QInputDialog.getText(None, title, prompt, text=current_value)
            if ok:
                parent.set_placeholder_value(self.key, value)
                if self.scene():
                    self.scene().editor_dialog.mark_modified()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def to_dict(self):
        return {
            "type": "placeholder",
            "key": self.key,
            "position": [self._center.x(), self._center.y()],
            "alignment": self.alignment,
        }


class SymbolConnectionItem(QGraphicsEllipseItem):
    """Connection point marker snapping to the grid."""

    # Violett: hebt Trennpunkte klar von schwarzen Zeichenlinien ab.
    CONNECTION_COLOR = QColor(140, 50, 210)

    def __init__(self, center_point, grid_step=1.0):
        super().__init__()
        self.grid_step = grid_step
        self.radius = max(grid_step, 3)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setPen(QPen(self.CONNECTION_COLOR, 1))
        self.setBrush(self.CONNECTION_COLOR)
        self.setZValue(6)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)

        # Geometrie um den Ursprung; die Platzierung übernimmt setPos.
        # (Positionierung über das rect würde wegen ItemIgnoresTransformations
        # beim Zoom/Pan des Editors am Bildschirm versetzt erscheinen.)
        self.setRect(-self.radius, -self.radius, self.radius * 2, self.radius * 2)

        self._center = QPointF(center_point[0], center_point[1])
        self.setPos(self._center)

    def _snap_point(self, point):
        step = self.grid_step if self.grid_step else 1.0
        x = round(point.x() / step) * step
        y = round(point.y() / step) * step
        return QPointF(x, y)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            # Die Item-Position IST das Zentrum des Trennpunkts.
            return self._snap_point(value)
        if change == QGraphicsItem.ItemPositionHasChanged:
            self._center = QPointF(self.pos())
            # Defensiv: nur Editor-Szenen haben ein editor_dialog-Attribut.
            dialog = getattr(self.scene(), "editor_dialog", None)
            if dialog is not None:
                dialog.mark_modified()
        return super().itemChange(change, value)

    def center(self):
        """Return center point of the connection marker."""
        return QPointF(self._center.x(), self._center.y())


class SymbolAnchorItem(QGraphicsItem):
    """Visual marker for the symbol origin."""

    is_anchor = True

    def __init__(self, grid_step=1.0):
        super().__init__()
        self.grid_step = grid_step
        self.size = max(grid_step * 1.2, 12.0)
        self.setZValue(30)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)

    def boundingRect(self):
        half = self.size
        return QRectF(-half, -half, half * 2, half * 2)

    def paint(self, painter, option, widget=None):
        pen = QPen(QColor(200, 0, 0), 2)
        painter.setPen(pen)
        painter.drawLine(QPointF(-self.size, 0.0), QPointF(self.size, 0.0))
        painter.drawLine(QPointF(0.0, -self.size), QPointF(0.0, self.size))
        painter.drawEllipse(QPointF(0, 0), self.grid_step * 0.4, self.grid_step * 0.4)


class SymbolEditorScene(QGraphicsScene):
    """QGraphicsScene with drawing logic for the symbol editor."""

    def __init__(self, canvas, editor_dialog):
        super().__init__()
        self.canvas = canvas
        self.editor_dialog = editor_dialog
        self._active_item = None
        self._start_point = None

    def mousePressEvent(self, event):
        tool = self.editor_dialog.current_tool
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        snapped_point = self.canvas.snap_to_grid(event.scenePos(), use_minor=True)
        grid_step = self.canvas.minor_grid_size

        if tool == "anchor":
            self.editor_dialog.set_anchor_position(snapped_point)
            event.accept()
            return

        if tool == "line":
            self._start_point = snapped_point
            self._active_item = SymbolLineItem(
                snapped_point,
                snapped_point,
                grid_step,
                color=self.editor_dialog.current_line_color,
            )
            self.addItem(self._active_item)
            event.accept()
            return

        if tool == "circle":
            self._start_point = snapped_point
            self._active_item = SymbolCircleItem(snapped_point, grid_step, grid_step)
            self.addItem(self._active_item)
            event.accept()
            return

        if tool.startswith("placeholder_"):
            key = tool.split("_", 1)[1]
            placeholder = SymbolPlaceholderItem(key, [snapped_point.x(), snapped_point.y()], grid_step)
            self.addItem(placeholder)
            self.editor_dialog.mark_modified()
            event.accept()
            return

        if tool == "connection":
            connection = SymbolConnectionItem([snapped_point.x(), snapped_point.y()], grid_step)
            self.addItem(connection)
            self.editor_dialog.mark_modified()
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._active_item:
            current_point = self.canvas.snap_to_grid(event.scenePos(), use_minor=True)
            if isinstance(self._active_item, SymbolLineItem):
                self._active_item.update_end_point(current_point)
            elif isinstance(self._active_item, SymbolCircleItem):
                self._active_item.set_radius_from_point(current_point)
            self.editor_dialog.mark_modified()
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._active_item and event.button() == Qt.LeftButton:
            cleanup = False
            if isinstance(self._active_item, SymbolLineItem):
                end_point = self._active_item.scene_end()
                if (end_point - self._start_point).manhattanLength() < self.canvas.minor_grid_size / 2:
                    cleanup = True
            elif isinstance(self._active_item, SymbolCircleItem):
                radius = self._active_item.radius()
                if radius <= self.canvas.minor_grid_size / 2:
                    cleanup = True

            if cleanup:
                self.removeItem(self._active_item)
            else:
                self._active_item.setFlag(QGraphicsItem.ItemIsMovable, True)
                self._active_item.setFlag(QGraphicsItem.ItemIsSelectable, True)
                self.editor_dialog.mark_modified()

            self._active_item = None
            self._start_point = None
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def cancel_drawing(self):
        """Cancel the current temporary drawing."""
        if self._active_item:
            self.removeItem(self._active_item)
            self._active_item = None
            self._start_point = None


class SymbolEditorDialog(QDialog):
    """Modal dialog for editing custom circuit symbols."""

    def __init__(self, parent=None, major_grid_size=20, subdivisions=10, symbols_dir=None):
        super().__init__(parent)
        self.setWindowTitle("Symbol-Editor")
        self.resize(900, 800)

        self.symbol_directory = Path(symbols_dir) if symbols_dir else SYMBOLS_DIR
        self.current_tool = "select"
        self.current_orientation = "horizontal"
        self.current_file_path = None
        self._is_modified = False
        self.current_line_color = tuple(WIRE_COLOR_PRESETS[0][1])
        self.line_color_combo = None
        self._updating_line_color_ui = False
        self._pending_selection_sync = False

        self.canvas = GridCanvas(grid_size=major_grid_size, subdivisions=subdivisions)
        self.canvas.set_snap_to_subgrid(True)
        self.scene = SymbolEditorScene(self.canvas, self)
        self.canvas.setScene(self.scene)
        self.canvas.scene = self.scene  # maintain attribute compatibility
        self.scene.selectionChanged.connect(self.on_scene_selection_changed)
        visible_cells = 10  # 10x10 grid instead of 15x15
        grid_span = visible_cells * major_grid_size
        half_extent = grid_span / 2
        self.scene.setSceneRect(-half_extent, -half_extent, grid_span, grid_span)
        zoom_factor = 4.0  # Increased zoom for better visibility
        viewport_size = int(grid_span * zoom_factor)
        self.canvas.setMinimumSize(viewport_size, viewport_size)
        self.canvas.set_zoom_factor(zoom_factor)
        self.canvas.centerOn(0, 0)
        self.scene.changed.connect(self.mark_modified)

        self.orientation_data = {
            "horizontal": {
                "items": [],
                "placeholders": [],
                "connection_points": [],
                "origin": [0.0, 0.0],
            },
            "vertical": {
                "items": [],
                "placeholders": [],
                "connection_points": [],
                "origin": [0.0, 0.0],
            },
        }
        # Referenz für «nur eine Orientierung bearbeitet»-Erkennung
        self._original_orientation_data = copy.deepcopy(self.orientation_data)
        self.anchor_item = None

        self._init_ui()
        self._init_shortcuts()
        self.set_tool("select")
        self._load_orientation_scene(self.current_orientation)
        self.reset_modified()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Metadata inputs
        metadata_layout = QHBoxLayout()
        metadata_layout.addWidget(QLabel("ID (aus Dateiname):"))
        self.id_input = QLineEdit()
        self.id_input.setReadOnly(True)
        self.id_input.setPlaceholderText("Wird beim Speichern automatisch gesetzt")
        metadata_layout.addWidget(self.id_input)

        metadata_layout.addWidget(QLabel("Name:"))
        self.name_input = QLineEdit()
        metadata_layout.addWidget(self.name_input)

        metadata_layout.addWidget(QLabel("Kategorie:"))
        self.category_input = QComboBox()
        self.category_input.setEditable(True)
        self.category_input.addItems([
            "Energiequellen",
            "Messgeräte",
            "Passive Bauteile",
            "Steuerung",
            "Verbraucher",
            "Unkategorisiert",
        ])
        metadata_layout.addWidget(self.category_input)

        metadata_layout.addStretch()
        layout.addLayout(metadata_layout)

        # Default values inputs
        defaults_layout = QHBoxLayout()
        self.default_value_inputs = {}
        for key, label in PLACEHOLDER_LABELS.items():
            defaults_layout.addWidget(QLabel(f"{label}:"))
            line_edit = QLineEdit()
            defaults_layout.addWidget(line_edit)
            self.default_value_inputs[key] = line_edit
        defaults_layout.addStretch()
        layout.addLayout(defaults_layout)

        # Tool buttons
        tool_layout = QHBoxLayout()
        tool_layout.addWidget(QLabel("Werkzeug:"))
        self.tool_buttons = {}
        self.tool_buttons["select"] = self._create_tool_button("Auswahl", "select", checked=True)
        tool_layout.addWidget(self.tool_buttons["select"])
        self.tool_buttons["line"] = self._create_tool_button("Linie", "line")
        tool_layout.addWidget(self.tool_buttons["line"])
        self.tool_buttons["circle"] = self._create_tool_button("Kreis", "circle")
        tool_layout.addWidget(self.tool_buttons["circle"])
        self.tool_buttons["connection"] = self._create_tool_button("Anschluss (Trennpunkt)", "connection")
        self.tool_buttons["connection"].setToolTip(
            "Setzt einen Trenn-/Andockpunkt: In der Schaltung wird eine Leitung "
            "an diesen Punkten getrennt und das Bauteil dort angedockt; "
            "Leitungsenden rasten magnetisch darauf ein."
        )
        tool_layout.addWidget(self.tool_buttons["connection"])
        self.tool_buttons["anchor"] = self._create_tool_button("Startpunkt", "anchor")
        tool_layout.addWidget(self.tool_buttons["anchor"])

        for placeholder_key, label in PLACEHOLDER_LABELS.items():
            tool_id = f"placeholder_{placeholder_key}"
            self.tool_buttons[tool_id] = self._create_tool_button(label, tool_id)
            tool_layout.addWidget(self.tool_buttons[tool_id])

        tool_layout.addStretch()

        color_label = QLabel("Linienfarbe:")
        tool_layout.addWidget(color_label)

        self.line_color_combo = QComboBox()
        self.line_color_combo.setToolTip("Farbe fuer neue Linien; wirkt auch auf Auswahl.")
        for name, rgb in WIRE_COLOR_PRESETS:
            rgb_tuple = self._coerce_rgb(rgb)
            self.line_color_combo.addItem(name, rgb_tuple)
            index = self.line_color_combo.count() - 1
            self.line_color_combo.setItemData(index, QColor(*rgb_tuple), Qt.DecorationRole)
        self.line_color_combo.currentIndexChanged.connect(self.on_line_color_changed)
        initial_index = self._index_for_line_color(self.current_line_color)
        if initial_index != -1:
            self.line_color_combo.setCurrentIndex(initial_index)
        tool_layout.addWidget(self.line_color_combo)

        tool_layout.addStretch()

        tool_layout.addWidget(QLabel("Orientierung:"))
        self.orientation_combo = QComboBox()
        self.orientation_combo.addItems(["horizontal", "vertical"])
        self.orientation_combo.currentTextChanged.connect(self._on_orientation_changed)
        tool_layout.addWidget(self.orientation_combo)

        self.derive_btn = QPushButton("⟳ Andere ableiten")
        self.derive_btn.setToolTip(
            "Die jeweils andere Orientierung automatisch aus der aktuellen "
            "Zeichnung ableiten (90° gedreht) — erspart das zweite Mal Zeichnen.")
        self.derive_btn.clicked.connect(self._derive_other_orientation)
        tool_layout.addWidget(self.derive_btn)

        tool_layout.addStretch()

        self.open_btn = QPushButton("Öffnen")
        self.open_btn.clicked.connect(self.open_symbol)
        tool_layout.addWidget(self.open_btn)

        self.save_btn = QPushButton("Speichern")
        self.save_btn.clicked.connect(self.save_symbol)
        tool_layout.addWidget(self.save_btn)

        self.save_as_btn = QPushButton("Speichern unter")
        self.save_as_btn.clicked.connect(self.save_symbol_as)
        tool_layout.addWidget(self.save_as_btn)

        layout.addLayout(tool_layout)
        layout.addWidget(self.canvas)

        info = QLabel(
            "Hinweis: Elemente lassen sich markieren, verschieben und mit Entf entfernen. "
            "Platzhalter repräsentieren Name, Spannung, Strom und Widerstand. "
            "Anschlüsse (Trennpunkte) legen fest, wo in der Schaltung Leitungen beim "
            "Platzieren getrennt und wo Leitungsenden angedockt werden."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Connect change signals to modification tracking
        self.id_input.textChanged.connect(self.mark_modified)
        self.name_input.textChanged.connect(self.mark_modified)
        self.category_input.currentTextChanged.connect(self.mark_modified)
        for line_edit in self.default_value_inputs.values():
            line_edit.textChanged.connect(self.mark_modified)

    def _init_shortcuts(self):
        QShortcut(QKeySequence.Delete, self, activated=self.delete_selected)
        QShortcut(QKeySequence.Cancel, self, activated=self.cancel_current_drawing)

    def _create_tool_button(self, label, tool_name, checked=False):
        btn = QPushButton(label)
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.clicked.connect(lambda: self.set_tool(tool_name))
        return btn

    def set_tool(self, tool_name):
        self.current_tool = tool_name
        for name, button in self.tool_buttons.items():
            button.setChecked(name == tool_name)

        if tool_name == "select":
            self.canvas.setDragMode(self.canvas.RubberBandDrag)
        elif tool_name == "anchor":
            self.canvas.setDragMode(self.canvas.NoDrag)
        else:
            self.canvas.setDragMode(self.canvas.NoDrag)

    @staticmethod
    def _coerce_rgb(value):
        if isinstance(value, QColor):
            return (value.red(), value.green(), value.blue())
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return (int(value[0]), int(value[1]), int(value[2]))
        return (0, 0, 0)

    def _index_for_line_color(self, rgb):
        if not self.line_color_combo:
            return -1
        target = self._coerce_rgb(rgb)
        for idx in range(self.line_color_combo.count()):
            data = self.line_color_combo.itemData(idx)
            if data is None:
                continue
            if self._coerce_rgb(data) == target:
                return idx
        return -1

    def on_line_color_changed(self, index):
        if self.line_color_combo is None or index < 0:
            return
        data = self.line_color_combo.itemData(index)
        if data is None:
            return
        rgb = self._coerce_rgb(data)
        self.current_line_color = rgb
        if self._updating_line_color_ui:
            return
        active_item = getattr(self.scene, "_active_item", None)
        if isinstance(active_item, SymbolLineItem):
            active_item.set_line_color(rgb)
        updated = False
        for item in self.scene.selectedItems():
            if isinstance(item, SymbolLineItem):
                item.set_line_color(rgb)
                updated = True
        if updated:
            self.mark_modified()

    def on_scene_selection_changed(self):
        if self._pending_selection_sync:
            return
        self._pending_selection_sync = True
        QTimer.singleShot(0, self._sync_line_color_from_selection)

    def _sync_line_color_from_selection(self):
        self._pending_selection_sync = False
        if not self.line_color_combo:
            return
        if QApplication.mouseButtons() != Qt.NoButton:
            self._pending_selection_sync = True
            QTimer.singleShot(50, self._sync_line_color_from_selection)
            return
        selected_lines = [item for item in self.scene.selectedItems() if isinstance(item, SymbolLineItem)]
        if not selected_lines:
            return
        first_rgb = selected_lines[0].color_rgb()
        if any(item.color_rgb() != first_rgb for item in selected_lines[1:]):
            return
        index = self._index_for_line_color(first_rgb)
        if index == -1:
            self.current_line_color = tuple(first_rgb)
            return
        try:
            self._updating_line_color_ui = True
            self.line_color_combo.blockSignals(True)
            self.line_color_combo.setCurrentIndex(index)
        finally:
            self.line_color_combo.blockSignals(False)
            self._updating_line_color_ui = False
        self.current_line_color = tuple(first_rgb)

    def mark_modified(self, *_):
        if not self._is_modified:
            self._is_modified = True
            self._update_window_title()

    def reset_modified(self):
        self._is_modified = False
        self._update_window_title()

    def _update_window_title(self):
        filename = Path(self.current_file_path).name if self.current_file_path else "Unbenannt"
        marker = "*" if self._is_modified else ""
        self.setWindowTitle(f"Symbol-Editor - {filename}{marker}")

    def delete_selected(self):
        items = list(self.scene.selectedItems())
        if not items:
            return
        for item in items:
            self.scene.removeItem(item)
        self.mark_modified()

    def cancel_current_drawing(self):
        self.scene.cancel_drawing()

    def _store_current_orientation(self):
        data = self._collect_scene_data()
        data["origin"] = self._get_current_anchor_origin()
        self.orientation_data[self.current_orientation] = data

    def _collect_scene_data(self):
        items = []
        placeholders = []
        connections = []

        for item in self.scene.items():
            if getattr(item, "is_handle", False):
                continue
            if getattr(item, "is_anchor", False):
                continue
            if isinstance(item, SymbolLineItem):
                items.append(item.to_dict())
            elif isinstance(item, SymbolCircleItem):
                items.append(item.to_dict())
            elif isinstance(item, SymbolPlaceholderItem):
                placeholders.append(item.to_dict())
            elif isinstance(item, SymbolConnectionItem):
                point = item.center()
                connections.append([float(point.x()), float(point.y())])

        return {
            "items": items,
            "placeholders": placeholders,
            "connection_points": connections,
        }

    def _get_current_anchor_origin(self):
        if self.anchor_item is not None:
            pos = self.anchor_item.pos()
            return [float(pos.x()), float(pos.y())]
        origin = self.orientation_data.get(self.current_orientation, {}).get("origin", [0.0, 0.0])
        return [float(origin[0]), float(origin[1])]

    def set_anchor_position(self, point: QPointF):
        snapped = self.canvas.snap_to_grid(point, use_minor=True)
        if self.anchor_item is None:
            self.anchor_item = SymbolAnchorItem(self.canvas.minor_grid_size)
            self.scene.addItem(self.anchor_item)
        self.anchor_item.setPos(snapped.x(), snapped.y())
        entry = self.orientation_data.setdefault(
            self.current_orientation,
            {
                "items": [],
                "placeholders": [],
                "connection_points": [],
                "origin": [0.0, 0.0],
            },
        )
        origin_values = [float(snapped.x()), float(snapped.y())]
        entry["origin"] = origin_values
        self.mark_modified()

    def _load_orientation_scene(self, orientation):
        orientation_entry = self.orientation_data.setdefault(
            orientation,
            {
                "items": [],
                "placeholders": [],
                "connection_points": [],
                "origin": [0.0, 0.0],
            },
        )
        data = orientation_entry
        self.scene.blockSignals(True)
        try:
            self.scene.clear()
            self.anchor_item = None
            grid_step = self.canvas.minor_grid_size

            for entry in data.get("items", []):
                item_type = entry.get("type")
                if item_type == "line":
                    item = SymbolLineItem.from_dict(entry, grid_step)
                elif item_type == "circle":
                    item = SymbolCircleItem.from_dict(entry, grid_step)
                else:
                    continue
                self.scene.addItem(item)

            for entry in data.get("placeholders", []):
                key = entry.get("key")
                position = entry.get("position", [0, 0])
                alignment = entry.get("alignment", "center")
                placeholder = SymbolPlaceholderItem(key, position, grid_step, alignment)
                self.scene.addItem(placeholder)

            for point in data.get("connection_points", []):
                connection = SymbolConnectionItem(point, grid_step)
                self.scene.addItem(connection)

            origin = data.get("origin")
            if origin is None:
                origin = [0.0, 0.0]
            origin = [float(origin[0]), float(origin[1])]
            orientation_entry["origin"] = origin

            self.anchor_item = SymbolAnchorItem(self.canvas.minor_grid_size)
            self.anchor_item.setPos(origin[0], origin[1])
            self.scene.addItem(self.anchor_item)
        finally:
            self.scene.blockSignals(False)

    def _derive_other_orientation(self):
        """Andere Orientierung aus der aktuellen Zeichnung ableiten (90°)."""
        self._store_current_orientation()
        current = self.current_orientation
        other = "vertical" if current == "horizontal" else "horizontal"
        self.orientation_data[other] = derive_rotated_orientation(
            self.orientation_data[current], clockwise=(current == "vertical"))
        self.mark_modified()
        QMessageBox.information(
            self, "Orientierung abgeleitet",
            f"Die {other}-Ansicht wurde aus der aktuellen {current}-Zeichnung "
            "abgeleitet (90° gedreht).\n"
            "Feinschliff über die Orientierungs-Auswahl oben möglich.")

    def _offer_derive_other_orientation(self):
        """Beim Speichern fragen, falls nur EINE Orientierung bearbeitet wurde.

        Typischer Fall: Batterie horizontal zur Spannungsquelle umgebaut,
        vertikal blieb der alte Stand — beim Drehen erschien das Batterie-
        Symbol. Default ist Nein, damit handgezeichnete Originale nie still
        überschrieben werden.
        """
        changed = [
            orient for orient, data in self.orientation_data.items()
            if self._original_orientation_data.get(orient) != data
        ]
        if len(changed) != 1:
            return
        source = changed[0]
        target = "vertical" if source == "horizontal" else "horizontal"
        target_data = self.orientation_data.get(target, {})
        if not target_data.get("items"):
            question = (
                f"Die {target}-Ansicht ist noch leer. Soll sie automatisch aus "
                f"der {source}-Zeichnung abgeleitet werden (90° gedreht)?")
        else:
            question = (
                f"Nur die {source}-Ansicht wurde bearbeitet — die {target}-"
                f"Ansicht enthält noch den alten Stand. Soll sie automatisch "
                "übernommen werden (aktuelle Zeichnung, 90° gedreht)?")
        answer = QMessageBox.question(
            self, "Orientierungen", question,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self.orientation_data[target] = derive_rotated_orientation(
                self.orientation_data[source], clockwise=(source == "vertical"))

    def _on_orientation_changed(self, orientation):
        if orientation == self.current_orientation:
            return
        self._store_current_orientation()
        self.current_orientation = orientation
        self._load_orientation_scene(orientation)

    def open_symbol(self):
        if self._is_modified and not self._confirm_discard_changes():
            return

        default_dir = str(self.symbol_directory)
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Symbol öffnen",
            default_dir,
            "Symboldateien (*.symbol.json);;Alle Dateien (*)",
        )
        if not filename:
            return

        self.load_symbol_file(filename)

    def load_symbol_file(self, filename):
        """Symboldefinition aus einer Datei laden (zum Bearbeiten öffnen).

        'Speichern' schreibt anschließend direkt zurück in diese Datei –
        wird für 'Symbol ändern' aus dem Hauptfenster genutzt.
        """
        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._load_from_data(data)
            self.current_file_path = filename
            self.reset_modified()
        except Exception as exc:
            QMessageBox.critical(self, "Fehler", f"Symbol konnte nicht geladen werden:\n{exc}")

    def save_symbol(self):
        if not self.current_file_path:
            self.save_symbol_as()
            return

        self._store_current_orientation()
        self._offer_derive_other_orientation()
        self._save_to_path(self.current_file_path)

    def save_symbol_as(self):
        default_dir = str(self.symbol_directory)
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Symbol speichern",
            default_dir,
            "Symboldateien (*.symbol.json);;Alle Dateien (*)",
        )
        if not filename:
            return

        if not filename.endswith(".symbol.json"):
            filename += ".symbol.json"

        self._store_current_orientation()
        self._offer_derive_other_orientation()
        self._save_to_path(filename)
        self.current_file_path = filename

    def _save_to_path(self, path):
        # Pfad normalisieren (Dialog-Eingabe): resolve() beseitigt relative
        # Anteile und ../-Segmente — schreiben nur an eindeutig aufgelöste Ziele.
        path = str(Path(path).resolve())
        # Generate ID from filename (remove .symbol.json extension)
        filename = Path(path).stem  # Gets "resistor" from "resistor.symbol.json"
        if filename.endswith(".symbol"):
            filename = filename[:-7]  # Remove ".symbol" if present
        symbol_id = filename

        name = self.name_input.text().strip() or symbol_id
        category = self.category_input.currentText().strip() or "Unkategorisiert"

        default_values = {
            key: line_edit.text().strip()
            for key, line_edit in self.default_value_inputs.items()
            if line_edit.text().strip()
        }

        orientations_payload = {}
        for orientation, data in self.orientation_data.items():
            items = data.get("items", [])
            placeholders = data.get("placeholders", [])
            connection_points = data.get("connection_points", [])
            origin = data.get("origin", [0.0, 0.0])

            # Skip orientations that have no items (empty drawings)
            if not items:
                continue

            bounds = self._compute_bounds(items, placeholders, connection_points)
            orientations_payload[orientation] = {
                "items": items,
                "placeholders": placeholders,
                "connection_points": connection_points,
                "bounds": bounds,
                "origin": origin,
            }

        # Validate that we have at least one orientation before saving
        if not orientations_payload:
            QMessageBox.warning(
                self,
                "Keine Zeichnung",
                "Es muss mindestens eine Orientierung mit Zeichenelementen vorhanden sein.",
            )
            return

        # Felder erhalten, die der Editor nicht bearbeitet — sonst ginge z. B.
        # «hidden» (Palette-Ausblendung) beim erneuten Speichern einer
        # vorhandenen Datei verloren (Datenverlust-Bugfix).
        preserved = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if isinstance(existing, dict):
                preserved = existing
        except (OSError, ValueError):
            preserved = {}
        known_keys = {"version", "id", "name", "category",
                      "default_values", "orientations"}

        payload = {k: v for k, v in preserved.items() if k not in known_keys}
        payload.update({
            "version": preserved.get("version", "1.0"),
            "id": symbol_id,
            "name": name,
            "category": category,
            "default_values": default_values,
            "orientations": orientations_payload,
        })

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)

            # Update ID display after successful save
            self.id_input.setText(symbol_id)

            self.reset_modified()
            self._original_orientation_data = copy.deepcopy(self.orientation_data)
            QMessageBox.information(self, "Gespeichert", f"Symbol wurde gespeichert:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Fehler", f"Symbol konnte nicht gespeichert werden:\n{exc}")

    def _load_from_data(self, data):
        self.scene.blockSignals(True)
        try:
            self.id_input.setText(data.get("id", ""))
            self.name_input.setText(data.get("name", ""))
            category = data.get("category", "")
            if category:
                if category not in [self.category_input.itemText(i) for i in range(self.category_input.count())]:
                    self.category_input.addItem(category)
                self.category_input.setCurrentText(category)
            else:
                self.category_input.setCurrentText("")

            defaults = data.get("default_values", {})
            for key, line_edit in self.default_value_inputs.items():
                line_edit.setText(defaults.get(key, ""))

            orientations = data.get("orientations", {})
            for orientation in ["horizontal", "vertical"]:
                orientation_block = orientations.get(orientation, {})
                items = orientation_block.get("items", [])
                placeholders = orientation_block.get("placeholders", [])
                connection_points = orientation_block.get("connection_points", [])
                origin = orientation_block.get("origin")
                if origin is None:
                    temp_bounds = self._compute_bounds(items, placeholders, connection_points)
                    origin = [
                        (temp_bounds["min"][0] + temp_bounds["max"][0]) / 2.0,
                        (temp_bounds["min"][1] + temp_bounds["max"][1]) / 2.0,
                    ]
                origin = [float(origin[0]), float(origin[1])]
                self.orientation_data[orientation] = {
                    "items": items,
                    "placeholders": placeholders,
                    "connection_points": connection_points,
                    "origin": origin,
                }
            self.current_orientation = "horizontal"
            self.orientation_combo.blockSignals(True)
            self.orientation_combo.setCurrentText("horizontal")
            self.orientation_combo.blockSignals(False)
            self._load_orientation_scene("horizontal")
            self._original_orientation_data = copy.deepcopy(self.orientation_data)
        finally:
            self.scene.blockSignals(False)

    def _generate_symbol_id(self, name):
        base = name.strip().lower().replace(" ", "_") or "symbol"
        sanitized = "".join(ch for ch in base if ch.isalnum() or ch == "_")
        return sanitized or "symbol"

    @staticmethod
    def _compute_bounds(items, placeholders, connections):
        xs = []
        ys = []

        for item in items:
            if item.get("type") == "line":
                start = item.get("start", [0, 0])
                end = item.get("end", [0, 0])
                xs.extend([start[0], end[0]])
                ys.extend([start[1], end[1]])
            elif item.get("type") == "circle":
                center = item.get("center", [0, 0])
                radius = item.get("radius", 0)
                xs.extend([center[0] - radius, center[0] + radius])
                ys.extend([center[1] - radius, center[1] + radius])

        for placeholder in placeholders:
            position = placeholder.get("position", [0, 0])
            xs.append(position[0])
            ys.append(position[1])

        for point in connections:
            xs.append(point[0])
            ys.append(point[1])

        if not xs:
            xs = [-10.0, 10.0]
        if not ys:
            ys = [-10.0, 10.0]

        return {
            "min": [min(xs), min(ys)],
            "max": [max(xs), max(ys)],
        }

    def _confirm_discard_changes(self):
        reply = QMessageBox.question(
            self,
            "Änderungen verwerfen?",
            "Nicht gespeicherte Änderungen gehen verloren. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def closeEvent(self, event):
        if self._is_modified and not self._confirm_discard_changes():
            event.ignore()
            return
        super().closeEvent(event)
