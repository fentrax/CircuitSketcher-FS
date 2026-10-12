"""
Basis-Bauteil - Abstrakte Klasse für alle Schaltungsbauteile
"""
from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QPen
from PyQt5.QtWidgets import (
    QAction,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsTextItem,
    QInputDialog,
    QMenu,
)


PLACEHOLDER_PROMPTS = {
    "name": ("Name", "Beschriftung eingeben:"),
    "voltage": ("Spannung", "Spannung eingeben:"),
    "current": ("Strom", "Strom eingeben:"),
    "resistance": ("Widerstand", "Widerstand eingeben:"),
}


class _TextGripHandle(QGraphicsEllipseItem):
    """Griffpunkt an einem Platzhalter-Text (sichtbar bei Auswahl des Bauteils).

    Ziehen verschiebt den Text frei; das Bauteil selbst bleibt liegen. Das
    Griffpunkt-Item ist Kind des BAUTEILS (nicht des Textes), damit die
    Drag-Deltas direkt in Bauteil-Koordinaten anfallen — die Aufrecht-Drehung
    des Textes würde die Ziehrichtung sonst verfälschen. `is_handle` markiert
    das Item, damit Treffer-/Serialisierungslogik es überspringt.
    """

    is_handle = True

    def __init__(self, component, text_item, radius=4):
        super().__init__(-radius, -radius, radius * 2, radius * 2, component)
        self.component = component
        self.text_item = text_item
        self.setBrush(QColor(255, 255, 255))
        self.setPen(QPen(QColor(60, 120, 200), 1))
        self.setCursor(Qt.SizeAllCursor)
        self.setZValue(20)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setVisible(component.isSelected())

    def mousePressEvent(self, event):
        event.accept()

    def mouseMoveEvent(self, event):
        # Delta in Griffpunkt-Koordinaten (= Bauteil-Koordinaten) auf den Text
        # anwenden; der Griffpunkt folgt automatisch über dessen itemChange.
        delta = event.pos() - event.lastPos()
        if not delta.isNull():
            self.text_item.setPos(self.text_item.pos() + delta)
        event.accept()

    def mouseReleaseEvent(self, event):
        # Undo-Snapshot übernimmt der gemeinsame Release-Handler des Fensters
        # (Bauteil ist bei sichtbarem Griffpunkt zwangsläufig ausgewählt).
        event.accept()


class _PlaceholderTextItem(QGraphicsTextItem):
    """Interaktiver Textknoten für Symbolplatzhalter.

    Per Drag verschiebbar (linke Maustaste halten); der individuelle Versatz
    wird in `component.placeholder_offsets` festgehalten und übersteht damit
    Rotation, Undo/Redo und Speichern/Laden. Doppelklick bearbeitet den Wert.
    """

    def __init__(self, component, key):
        super().__init__(component)
        self.component = component
        self.key = key
        self._standard_pos = None
        self._applying_offset = False
        self.setDefaultTextColor(QColor(0, 0, 0))
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setZValue(10)
        # Kennzeichen für Aufräum-Sicherheitsnetze (z. B. _clear_preview).
        self.is_placeholder_text = True
        # Griffpunkt zum Verschieben des Textes (Kind des Bauteils, siehe
        # Klassen-Docstring); Sichtbarkeit folgt der Bauteil-Auswahl.
        self.grip = _TextGripHandle(component, self)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            grip = getattr(self, "grip", None)
            if grip is not None:
                grip.setPos(value)
            if not self._applying_offset and self._standard_pos is not None:
                standard = self._standard_pos
                offsets = getattr(self.component, "placeholder_offsets", None)
                if offsets is not None:
                    offsets[self.key] = [
                        self.pos().x() - standard.x(),
                        self.pos().y() - standard.y(),
                    ]
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        # Klick-durchreichend: Solange das Bauteil NICHT ausgewählt ist, fällt
        # der Klick durch das Label hindurch auf das Bauteil darunter — sonst
        # würde man beim Ziehen versehentlich nur das Label verschieben und
        # das Bauteil käme nie auf der Leitung an (Splitting würde nie
        # ausgelöst). Erst bei bereits ausgewähltem Bauteil lässt sich das
        # Label selbst greifen und feinpositionieren.
        if not self.component.isSelected():
            event.ignore()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        title, prompt = PLACEHOLDER_PROMPTS.get(
            self.key, (self.key.capitalize(), f"{self.key.capitalize()} eingeben:")
        )
        current_value = self.component.get_placeholder_value(self.key)
        value, ok = QInputDialog.getText(None, title, prompt, text=current_value)
        if ok:
            self.component._push_undo_from_component()
            self.component.set_placeholder_value(self.key, value)
        event.accept()


class BaseComponent(QGraphicsItem):
    """Basisklasse für alle Schaltungsbauteile"""

    def __init__(self, x=0, y=0):
        super().__init__()
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

        self.component_type = "Basis"
        self.label = ""
        self.value = ""
        self.rotation_angle = 0
        self.scale_factor = 1.0
        self.width = 60
        self.height = 40
        self._custom_bounding_rect = None

        # Verbindungspunkte (relativ zur Mitte)
        self.connection_points = []

        # Platzhaltertexte für dynamische Symbole
        self.placeholder_items = {}
        self.placeholder_configs = {}
        self.placeholder_values = {}
        # Individuelle Verschiebung der Platzhaltertexte {key: [dx, dy]}
        # (überlebt Rotation/Orientierungswechsel und Serialisierung)
        self.placeholder_offsets = {}
        # Messwert-Annotationen (z. B. Spannungsbogen), Kind-Items dieser Komponente
        self.annotations = []

        # Text-Label
        self.text_item = QGraphicsTextItem(self)
        self.text_item.setDefaultTextColor(QColor(0, 0, 0))
        self.text_item.setPos(-20, -50)  # Weiter oben, um Kollisionen zu vermeiden
        self.text_item.setFlag(QGraphicsItem.ItemIsSelectable, False)

        self.setPos(x, y)
        self._update_text_orientation()

    def boundingRect(self):
        """Begrenzungsrechteck definieren"""
        if self._custom_bounding_rect is not None:
            return self._custom_bounding_rect
        return QRectF(-self.width / 2, -self.height / 2, self.width, self.height)

    def paint(self, painter, option, widget):
        """In Unterklassen überschreiben um Bauteil zu zeichnen"""
        pass

    def rotate_component(self):
        """Bauteil um 90° weiterdrehen (0° -> 90° -> 180° -> 270° -> 0°)."""
        new_angle = (self.rotation_angle + 90) % 360
        self.setRotation(new_angle)

    def scale_component(self, factor):
        """Bauteil skalieren"""
        self.scale_factor *= factor
        self.setScale(self.scale_factor)

    def set_label(self, label):
        """Bauteil-Beschriftung setzen"""
        self.label = label
        self.update_text()

    def set_value(self, value):
        """Bauteil-Wert setzen"""
        self.value = value
        self.update_text()

    def set_placeholder_value(self, key, value):
        """Wert für einen Platzhalter aktualisieren"""
        self.placeholder_values[key] = value or ""
        self._update_placeholder_text(key)

    def get_placeholder_value(self, key):
        """Aktuellen Wert eines Platzhalters ermitteln"""
        return self.placeholder_values.get(key, "")

    def clear_placeholders(self):
        """Alle Platzhalter entfernen (individuelle Versätze bleiben erhalten).

        Textitems und ihre Griffpunkte werden wirklich aus der Szene entfernt:
        setParentItem(None) allein liesse sie als freie Elemente in der Szene
        zurück — nach jedem Drehen blieben so Geister-Kopien der Beschriftung
        stehen (unbedienbar, da der Doppelklick die Kopie traf).
        """
        for item in self.placeholder_items.values():
            grip = getattr(item, "grip", None)
            if grip is not None:
                grip_scene = grip.scene()
                if grip_scene is not None:
                    grip_scene.removeItem(grip)
                else:
                    grip.setParentItem(None)
            scene = item.scene()
            if scene is not None:
                scene.removeItem(item)
        self.placeholder_items.clear()
        self.placeholder_configs.clear()

    def configure_placeholders(self, placeholders, defaults=None):
        """Platzhalterkonfiguration anwenden"""
        defaults = defaults or {}
        self.clear_placeholders()

        for entry in placeholders:
            key = entry.get("key")
            if not key:
                continue

            position = entry.get("position", [0, 0])
            alignment = entry.get("alignment", "center")
            pos_point = QPointF(float(position[0]), float(position[1]))

            placeholder_item = _PlaceholderTextItem(self, key)

            if key not in self.placeholder_values:
                self.placeholder_values[key] = defaults.get(key, "")

            self.placeholder_items[key] = placeholder_item
            self.placeholder_configs[key] = {
                "position": pos_point,
                "alignment": alignment.lower(),
            }
            self._update_placeholder_text(key)

    def update_text(self):
        """Textanzeige aktualisieren"""
        text = self.label
        if self.value:
            text += f"\n{self.value}"
        self.text_item.setPlainText(text)
        self._update_text_orientation()
        for key in self.placeholder_items:
            self._update_placeholder_text(key)

    def mouseDoubleClickEvent(self, event):
        """Doppelklick zum Bearbeiten der Eigenschaften"""
        self._push_undo_from_component()
        label, ok1 = QInputDialog.getText(
            None,
            "Bauteil-Beschriftung",
            "Beschriftung eingeben:",
            text=self.label,
        )
        if ok1:
            self.set_label(label)

        value, ok2 = QInputDialog.getText(
            None,
            "Bauteil-Wert",
            "Wert eingeben:",
            text=self.value,
        )
        if ok2:
            self.set_value(value)

    def _main_window(self):
        """Zugehöriges Hauptfenster über die Szene/View-Hierarchie finden.

        Liefert None, wenn das Bauteil (noch) in keiner Szene liegt oder das
        Top-Level-Widget keines mit den erwarteten Methoden ist.
        """
        scene = self.scene()
        if not scene or not scene.views():
            return None
        return scene.views()[0].window()

    def _push_undo_from_component(self):
        """Undo-Snapshot über die zugehörige MainWindow anstossen.

        Sucht das Top-Level-Widget über die Szene/View-Hierarchie und ruft
        dessen _push_undo_snapshot() auf, falls vorhanden. Sicherheitshalber
        werden fehlende Referenzen stillschweigend ignoriert.
        """
        push = getattr(self._main_window(), "_push_undo_snapshot", None)
        if callable(push):
            push()

    def itemChange(self, change, value):
        """Elementänderungen verarbeiten (für Raster-Einrastung)"""
        if change == QGraphicsItem.ItemSelectedHasChanged:
            # Griffpunkte der Platzhalter-Texte ein-/ausblenden (Muster wie
            # bei den Leitungsenden-Griffpunkten: nur bei Auswahl aktiv).
            for text in self.placeholder_items.values():
                grip = getattr(text, "grip", None)
                if grip is not None:
                    grip.setVisible(bool(value))
            # Schienen-Endgriffpunkt (Funktionsschema) genauso
            rail_handle = getattr(self, "rail_handle", None)
            if rail_handle is not None:
                try:
                    rail_handle.setVisible(bool(value))
                except RuntimeError:
                    pass
        if (change == QGraphicsItem.ItemPositionChange and self.scene()
                and getattr(self, "_snap_enabled", True)):
            # Am Raster einrasten
            grid_size = 20
            new_pos = value
            snap_x = round(new_pos.x() / grid_size) * grid_size
            snap_y = round(new_pos.y() / grid_size) * grid_size
            return QPointF(snap_x, snap_y)
        return super().itemChange(change, value)

    def contextMenuEvent(self, event):
        """Rechtsklick-Kontextmenü verarbeiten"""
        menu = QMenu()

        # Drehen
        rotate_action = QAction("Drehen (90°)", None)
        rotate_action.triggered.connect(self.rotate_component)
        menu.addAction(rotate_action)

        # Symbol im Symbol-Editor bearbeiten (falls vom Hauptfenster unterstützt)
        top = self._main_window()
        if top is not None and hasattr(top, "edit_symbol_component"):
            edit_action = QAction("Symbol bearbeiten…", None)
            edit_action.triggered.connect(lambda: top.edit_symbol_component(self))
            menu.addAction(edit_action)

        # Erweiterungen der Unterklasse (z. B. 'Relais zuweisen' für Kontakte)
        extender = getattr(self, "_extend_context_menu", None)
        if callable(extender):
            extender(menu)

        menu.addSeparator()

        # Vergrößern
        scale_up_action = QAction("Vergrößern", None)
        scale_up_action.triggered.connect(lambda: self.scale_component(1.2))
        menu.addAction(scale_up_action)

        # Verkleinern
        scale_down_action = QAction("Verkleinern", None)
        scale_down_action.triggered.connect(lambda: self.scale_component(0.8))
        menu.addAction(scale_down_action)

        menu.addSeparator()

        # Löschen
        delete_action = QAction("Löschen", None)
        delete_action.triggered.connect(self.delete_self)
        menu.addAction(delete_action)

        # Menü anzeigen
        menu.exec_(event.screenPos())

    def delete_self(self):
        """Bauteil von Szene löschen"""
        if self.scene():
            self.scene().removeItem(self)

    def get_connection_points(self):
        """Absolute Positionen der Verbindungspunkte erhalten"""
        points = []
        for point in self.connection_points:
            # Relativen Punkt zu absoluten Szenenkoordinaten transformieren
            absolute_point = self.mapToScene(point)
            points.append(absolute_point)
        return points

    def setRotation(self, angle):
        """Rotation setzen, auf Vielfache von 90° begrenzen (0/90/180/270)."""
        normalized = int(round(angle)) % 360
        constrained_angle = normalized if normalized % 90 == 0 else round(normalized / 90) * 90 % 360
        self.rotation_angle = constrained_angle
        QGraphicsItem.setRotation(self, self.rotation_angle)
        self._update_text_orientation()

    def _update_text_orientation(self):
        """Beschriftung und Platzhalter aufrecht halten (Gegenrotation)."""
        if self.text_item:
            self.text_item.setRotation(-self.rotation_angle)
        for item in self.placeholder_items.values():
            item.setRotation(-self.rotation_angle)
        # Messwert-Texte (z. B. Spannungswert) ebenfalls aufrecht halten
        for annotation in self.annotations:
            keep_upright = getattr(annotation, "keep_text_upright", None)
            if callable(keep_upright):
                keep_upright(-self.rotation_angle)

    def set_custom_bounding_rect(self, rect: QRectF):
        """Custom Bounding-Rect setzen"""
        self._custom_bounding_rect = rect

    def _placeholder_label(self, key):
        """Standardanzeige für Platzhalter ohne Wert"""
        labels = {
            "name": "[Name]",
            "voltage": "[Spannung]",
            "current": "[Strom]",
            "resistance": "[Widerstand]",
        }
        return labels.get(key, f"[{key.capitalize()}]")

    def _update_placeholder_text(self, key):
        """Platzhalteranzeige gemäß aktuellem Wert aktualisieren"""
        item = self.placeholder_items.get(key)
        config = self.placeholder_configs.get(key)
        if not item or not config:
            return

        value = self.placeholder_values.get(key, "")
        display_text = value if value else self._placeholder_label(key)
        item.setPlainText(display_text)

        rect = item.boundingRect()
        alignment = config.get("alignment", "center")
        position = config["position"]

        offset_x = rect.width() / 2.0
        if alignment == "left":
            offset_x = 0.0
        elif alignment == "right":
            offset_x = rect.width()

        offset_y = rect.height() / 2.0

        standard_x = position.x() - offset_x
        standard_y = position.y() - offset_y
        item._standard_pos = QPointF(standard_x, standard_y)
        # Individuellen Versatz (Drag durch den Nutzer) anwenden
        dx, dy = self.placeholder_offsets.get(key, (0.0, 0.0))
        item._applying_offset = True
        try:
            item.setPos(standard_x + dx, standard_y + dy)
        finally:
            item._applying_offset = False
