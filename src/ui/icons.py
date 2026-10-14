"""
Einheitliche Vektor-Icons für Werkzeugleiste und Palette.

Alle Icons werden zur Laufzeit mit QPainter gezeichnet (keine Bilddateien,
scharf bei jeder Bildschirmskalierung) und teilen Strichstärke und Farbe.
"""
import math

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

ICON_COLOR = QColor(45, 55, 72)
ACCENT = QColor(0, 102, 204)
DANGER = QColor(200, 45, 60)


def _canvas(size):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size / 24.0, size / 24.0)   # Zeichnen im 24er-Raster
    pen = QPen(ICON_COLOR, 1.8)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    return pixmap, painter


def _arrow_head(painter, tip, angle_deg, color=ICON_COLOR, size=4.5):
    rad = math.radians(angle_deg)
    back = QPointF(tip.x() - math.cos(rad) * size, tip.y() - math.sin(rad) * size)
    perp = QPointF(-math.sin(rad) * size * 0.6, math.cos(rad) * size * 0.6)
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawPolygon(QPolygonF([tip, back + perp, back - perp]))
    painter.restore()


def _draw(name, painter):
    if name == "new":
        path = QPainterPath()
        path.moveTo(6, 3); path.lineTo(14, 3); path.lineTo(18, 7)
        path.lineTo(18, 21); path.lineTo(6, 21); path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QPointF(14, 3), QPointF(14, 7))
        painter.drawLine(QPointF(14, 7), QPointF(18, 7))
    elif name == "open":
        path = QPainterPath()
        path.moveTo(3, 19); path.lineTo(3, 6); path.lineTo(9, 6); path.lineTo(11, 8)
        path.lineTo(19, 8); path.lineTo(19, 11)
        painter.drawPath(path)
        lid = QPainterPath()
        lid.moveTo(3, 19); lid.lineTo(6, 11); lid.lineTo(22, 11); lid.lineTo(19, 19)
        lid.closeSubpath()
        painter.drawPath(lid)
    elif name == "save":
        painter.drawRoundedRect(QRectF(4, 4, 16, 16), 2, 2)
        painter.drawRect(QRectF(8, 4, 8, 5))
        painter.drawRect(QRectF(7.5, 13, 9, 7))
    elif name in ("undo", "redo"):
        painter.save()
        if name == "redo":
            painter.translate(24, 0)
            painter.scale(-1, 1)
        path = QPainterPath()
        path.moveTo(7, 9)
        path.lineTo(14, 9)
        path.cubicTo(22, 9, 22, 20, 14, 20)
        path.lineTo(9, 20)
        painter.drawPath(path)
        _arrow_head(painter, QPointF(4, 9), 180)
        painter.restore()
    elif name == "rotate":
        painter.drawArc(QRectF(5, 5, 14, 14), 120 * 16, 270 * 16)
        # Pfeilspitze am Bogenende (Uhrzeigersinn)
        _arrow_head(painter, QPointF(8.2, 6.5), -40, ACCENT)
        painter.save()
        painter.setPen(QPen(ACCENT, 1.8))
        painter.drawRect(QRectF(10, 10, 4, 4))
        painter.restore()
    elif name == "reverse":
        # Zwei gegenläufige Pfeile = Messrichtung umkehren
        painter.save()
        painter.setPen(QPen(ACCENT, 1.8, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(4, 8.5), QPointF(17, 8.5))
        painter.restore()
        _arrow_head(painter, QPointF(20.5, 8.5), 0, ACCENT)
        painter.save()
        painter.setPen(QPen(DANGER, 1.8, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(20, 15.5), QPointF(7, 15.5))
        painter.restore()
        _arrow_head(painter, QPointF(3.5, 15.5), 180, DANGER)
    elif name == "delete":
        painter.save()
        painter.setPen(QPen(DANGER, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawLine(QPointF(4, 6), QPointF(20, 6))
        painter.drawLine(QPointF(9, 6), QPointF(10, 3))
        painter.drawLine(QPointF(10, 3), QPointF(14, 3))
        painter.drawLine(QPointF(14, 3), QPointF(15, 6))
        path = QPainterPath()
        path.moveTo(6, 6); path.lineTo(7.5, 21); path.lineTo(16.5, 21); path.lineTo(18, 6)
        painter.drawPath(path)
        painter.drawLine(QPointF(10, 10), QPointF(10, 17))
        painter.drawLine(QPointF(14, 10), QPointF(14, 17))
        painter.restore()
    elif name in ("zoom_in", "zoom_out"):
        painter.drawEllipse(QRectF(3.5, 3.5, 13, 13))
        painter.drawLine(QPointF(14.5, 14.5), QPointF(20.5, 20.5))
        painter.drawLine(QPointF(6.5, 10), QPointF(13.5, 10))
        if name == "zoom_in":
            painter.drawLine(QPointF(10, 6.5), QPointF(10, 13.5))
    elif name == "zoom_fit":
        for x, y, dx, dy in ((3, 3, 1, 1), (21, 3, -1, 1), (3, 21, 1, -1), (21, 21, -1, -1)):
            painter.drawLine(QPointF(x, y), QPointF(x + 5 * dx, y))
            painter.drawLine(QPointF(x, y), QPointF(x, y + 5 * dy))
        painter.drawRect(QRectF(8, 8, 8, 8))
    elif name == "grid":
        painter.save()
        painter.setPen(QPen(ICON_COLOR, 1.2))
        for v in (4, 9.33, 14.66, 20):
            painter.drawLine(QPointF(v, 4), QPointF(v, 20))
            painter.drawLine(QPointF(4, v), QPointF(20, v))
        painter.restore()
    elif name == "select":
        path = QPainterPath()
        path.moveTo(6, 3); path.lineTo(6, 19); path.lineTo(10, 15)
        path.lineTo(13, 21); path.lineTo(15.5, 20); path.lineTo(12.5, 14)
        path.lineTo(18, 14); path.closeSubpath()
        painter.drawPath(path)
    elif name == "wire":
        painter.drawLine(QPointF(4, 18), QPointF(12, 18))
        painter.drawLine(QPointF(12, 18), QPointF(12, 6))
        painter.drawLine(QPointF(12, 6), QPointF(20, 6))
        painter.save()
        painter.setBrush(ICON_COLOR)
        painter.drawEllipse(QPointF(12, 18), 1.6, 1.6)
        painter.restore()
    elif name == "voltage":
        painter.save()
        painter.setPen(QPen(ACCENT, 1.8, Qt.SolidLine, Qt.RoundCap))
        path = QPainterPath()
        path.moveTo(4, 16)
        path.quadTo(12, 2, 20, 16)
        painter.drawPath(path)
        painter.restore()
        _arrow_head(painter, QPointF(20, 16), 60, ACCENT)
        painter.drawLine(QPointF(3, 20), QPointF(21, 20))
    elif name == "current":
        painter.drawLine(QPointF(3, 12), QPointF(21, 12))
        _arrow_head(painter, QPointF(17, 12), 0, DANGER, size=8)
    else:
        painter.drawRect(QRectF(5, 5, 14, 14))


_CACHE = {}


def icon(name, size=24):
    """Icon nach Namen (new, open, save, undo, redo, rotate, delete, zoom_in,
    zoom_out, zoom_fit, grid, select, wire, voltage, current)."""
    key = (name, size)
    if key not in _CACHE:
        result = QIcon()
        for scale in (1, 2):   # 2x für HiDPI-Bildschirme
            pixmap, painter = _canvas(size * scale)
            _draw(name, painter)
            painter.end()
            pixmap.setDevicePixelRatio(scale)
            result.addPixmap(pixmap)
        _CACHE[key] = result
    return _CACHE[key]


def symbol_icon(definition, size=28):
    """Vorschaubild eines Symbols aus seiner horizontalen Geometrie."""
    orientation = definition.get_orientation("horizontal")
    points = []
    for item in orientation.items:
        if item.get("type") == "line":
            points += [item.get("start", [0, 0]), item.get("end", [0, 0])]
        elif item.get("type") == "circle":
            cx, cy = item.get("center", [0, 0])
            r = float(item.get("radius", 0))
            points += [[cx - r, cy - r], [cx + r, cy + r]]
    result = QIcon()
    if not points:
        return result
    min_x = min(float(p[0]) for p in points)
    max_x = max(float(p[0]) for p in points)
    min_y = min(float(p[1]) for p in points)
    max_y = max(float(p[1]) for p in points)
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)
    for scale in (1, 2):
        px = size * scale
        pixmap = QPixmap(px, px)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        factor = (px - 4 * scale) / max(width, height)
        painter.translate(px / 2.0, px / 2.0)
        painter.scale(factor, factor)
        painter.translate(-(min_x + max_x) / 2.0, -(min_y + max_y) / 2.0)
        pen = QPen(ICON_COLOR, 1.6 * scale / factor)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        for item in orientation.items:
            if item.get("type") == "line":
                s = item.get("start", [0, 0])
                e = item.get("end", [0, 0])
                painter.drawLine(QPointF(float(s[0]), float(s[1])), QPointF(float(e[0]), float(e[1])))
            elif item.get("type") == "circle":
                c = item.get("center", [0, 0])
                r = float(item.get("radius", 0))
                painter.drawEllipse(QPointF(float(c[0]), float(c[1])), r, r)
        painter.end()
        pixmap.setDevicePixelRatio(scale)
        result.addPixmap(pixmap)
    return result
