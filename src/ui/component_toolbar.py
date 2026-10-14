"""
Bauteil-Toolbar - Palette zum Ziehen von Bauteilen

- Symbol-Buttons: Linksklick wählt zum Platzieren, Rechtsklick öffnet ein
  Menü mit "Symbol bearbeiten…" (öffnet den Symbol-Editor mit diesem Symbol).
- Buttons lassen sich per Drag innerhalb ihrer Gruppe umsortieren; die
  Reihenfolge wird dauerhaft gespeichert (QSettings).
"""
import json

from PyQt5.QtCore import QEvent, QMimeData, QSettings, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QDrag
from PyQt5.QtWidgets import (QButtonGroup, QGroupBox, QLabel, QMenu, QPushButton,
                             QVBoxLayout, QWidget)

from .icons import icon, symbol_icon

#: Werkzeuge mit festem Icon (Symbole bekommen ihr Vorschaubild)
TOOL_ICONS = {"select": "select", "wire": "wire", "voltage": "voltage", "current": "current"}

BUTTON_STYLE = """
    QPushButton {
        background-color: #f7f8fa;
        border: 1px solid #d5d9e0;
        border-radius: 4px;
        padding: 4px 6px;
        text-align: left;
    }
    QPushButton:hover { background-color: #eaf2fc; border-color: #9cc3ee; }
    QPushButton:pressed { background-color: #d6e6f8; }
    QPushButton:checked {
        background-color: #d6e6f8;
        border: 1px solid #0066cc;
        font-weight: bold;
    }
"""


class ComponentToolbar(QWidget):
    """Toolbar mit dynamisch geladenen Symbolgruppen."""

    component_selected = pyqtSignal(str)
    # "Symbol bearbeiten…" aus dem Rechtsklick-Menü eines Symbol-Buttons
    symbol_edit_requested = pyqtSignal(str)

    ORDER_SETTINGS_KEY = "paletteOrder"
    DRAG_MIME_PREFIX = "symbol-button:"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.symbol_buttons = {}
        # Feste Werkzeuge (Auswählen, Leitung, Messwerte) — überdauern set_symbols
        self.tool_buttons = {}
        self._symbol_definitions = []
        # Genau ein Werkzeug ist aktiv und sichtbar hervorgehoben.
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        self._drag_start = None  # (globalPos, QPushButton) für Button-Drag
        self._build_ui()

    def _build_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setAlignment(Qt.AlignTop)

        title = QLabel("Bauteile")
        title.setStyleSheet("font-weight: bold; font-size: 14px; padding: 5px;")
        self.main_layout.addWidget(title)

        # Auswählen bewusst als EINZIGER Eintrag ganz oben — Standardwerkzeug,
        # immer sichtbar erreichbar.
        self.select_group = self._create_group("Auswählen", [
            {"label": "Auswählen", "value": "select"},
        ])
        self.main_layout.addWidget(self.select_group)

        # Leitung bewusst als ZWEITE Gruppe direkt unter 'Auswählen'
        self.tools_group = self._create_group("Werkzeuge", [
            {"label": "Leitung", "value": "wire"},
        ])
        self.main_layout.addWidget(self.tools_group)

        self.groups_layout = QVBoxLayout()
        self.groups_layout.setSpacing(10)
        self.main_layout.addLayout(self.groups_layout)

        # Messwert-Werkzeuge: Spannungsbogen auf Bauteilen, Strompfeil auf Leitungen
        self.messwerte_group = self._create_group("Messwerte", [
            {"label": "Spannung", "value": "voltage", "tooltip": "Blauer Spannungsbogen über einem Bauteil (z. B. 20 V)"},
            {"label": "Strom", "value": "current", "tooltip": "Roter Strompfeil auf einer Leitung (z. B. 15 mA)"},
        ])
        self.main_layout.addWidget(self.messwerte_group)

        # Kontakt-Spiegel (Funktionsschema): platzierbares Element, das alle
        # Kontakte EINES Relais mit aktueller Stellung anzeigt.
        self.mirror_group = self._create_group("Kontaktspiegel", [
            {"label": "Kontakt-Spiegel", "value": "contact_mirror",
             "tooltip": "Kontakte eines Relais mit aktueller Stellung anzeigen\n"
                        "(Rechtsklick: Relais zuweisen)"},
        ])
        self.main_layout.addWidget(self.mirror_group)

        self.main_layout.addStretch()

    def clear_symbol_groups(self):
        """Alle bestehenden Symbolgruppen entfernen."""
        for button in list(self._tool_group.buttons()):
            if getattr(button, "_symbol_id", None):
                self._tool_group.removeButton(button)
        while self.groups_layout.count():
            item = self.groups_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)

    def set_symbols(self, definitions):
        """Symboldefinitionen gruppiert darstellen."""
        self._symbol_definitions = list(definitions)
        self.symbol_buttons.clear()
        self.clear_symbol_groups()

        saved_order = self._load_saved_order()

        # Versteckte Symbole (hidden-Flag in der JSON) bleiben ladbar und im
        # Symbol-Editor verfügbar, erscheinen aber nicht in der Palette.
        categories = {}
        for definition in definitions:
            if getattr(definition, "hidden", False):
                continue
            categories.setdefault(definition.category, []).append(definition)

        for category in sorted(categories, key=str.lower):
            entries = []
            for definition in sorted(categories[category], key=lambda d: d.name.lower()):
                tooltip_parts = [definition.name]
                if definition.description:
                    tooltip_parts.append(definition.description)
                tooltip_parts.append(definition.file_path.name)
                entries.append({
                    "label": definition.name,
                    "value": definition.symbol_id,
                    "tooltip": "\n".join(tooltip_parts),
                    "definition": definition,
                })
            # Gespeicherte Button-Reihenfolge anwenden (unbekannte hinten)
            order = saved_order.get(category, [])
            entries.sort(
                key=lambda e: order.index(e["value"]) if e["value"] in order else len(order)
            )
            group = self._create_group(category, entries)
            self.groups_layout.addWidget(group)

    def _create_group(self, title, items):
        group = QGroupBox(title)
        group_layout = QVBoxLayout()

        for item in items:
            if isinstance(item, tuple):
                label, value = item
                tooltip = None
            else:
                label = item.get("label", "")
                value = item.get("value", "")
                tooltip = item.get("tooltip")

            button = QPushButton(label)
            button.setMinimumHeight(32)
            button.setCheckable(True)
            button.setIconSize(QSize(26, 26))
            definition = item.get("definition") if isinstance(item, dict) else None
            try:
                if definition is not None:
                    button.setIcon(symbol_icon(definition, 26))
                elif value in TOOL_ICONS:
                    button.setIcon(icon(TOOL_ICONS[value], 22))
            except Exception:
                pass  # Vorschaubild ist Zierde — fehlerhafte Symbole trotzdem anbieten
            self._tool_group.addButton(button)
            if value not in ("wire", "select", "voltage", "current"):
                button._symbol_id = value
                button._category = title
                button.setAcceptDrops(True)
                button.installEventFilter(self)
                button.setContextMenuPolicy(Qt.CustomContextMenu)
                button.customContextMenuRequested.connect(
                    lambda pos, btn=button: self._show_symbol_context_menu(btn, pos)
                )
                if tooltip:
                    button.setToolTip(
                        tooltip + "\nRechtsklick: Symbol bearbeiten…\n"
                        "Ziehen: innerhalb der Gruppe einsortieren"
                    )
            elif tooltip:
                button.setToolTip(tooltip)
            button.clicked.connect(lambda checked, val=value: self.component_selected.emit(val))
            button.setStyleSheet(BUTTON_STYLE)
            group_layout.addWidget(button)
            if value:
                self.symbol_buttons[value] = button
                if value in TOOL_ICONS:
                    self.tool_buttons[value] = button

        group.setLayout(group_layout)
        return group

    def button_for(self, value):
        value = value or "select"
        return self.tool_buttons.get(value) or self.symbol_buttons.get(value)

    def set_active(self, value):
        """Aktives Werkzeug hervorheben (z. B. nach ESC oder Menüwahl)."""
        button = self.button_for(value)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    # ------------------------------------------------------------------
    # Rechtsklick-Menü
    # ------------------------------------------------------------------
    def _symbol_context_menu(self):
        """Kontextmenü für Symbol-Buttons (testbar, ohne exec_)."""
        menu = QMenu(self)
        edit_action = menu.addAction("Symbol bearbeiten…")
        edit_action.triggered.connect(
            lambda checked, sender=None: self._emit_edit_for_sender()
        )
        return menu

    def _emit_edit_for_sender(self):
        action = self.sender()
        symbol_id = getattr(action, "_symbol_id", None) if action else None
        if symbol_id:
            self.symbol_edit_requested.emit(symbol_id)

    def _show_symbol_context_menu(self, button, pos):
        menu = self._symbol_context_menu()
        for action in menu.actions():
            action._symbol_id = getattr(button, "_symbol_id", None)
        menu.exec_(button.mapToGlobal(pos))

    # ------------------------------------------------------------------
    # Drag & Drop: Buttons innerhalb ihrer Gruppe umsortieren
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if isinstance(obj, QPushButton) and getattr(obj, "_symbol_id", None):
            event_type = event.type()
            if event_type == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._drag_start = (event.globalPos(), obj)
            elif (
                event_type == QEvent.MouseMove
                and self._drag_start
                and (event.buttons() & Qt.LeftButton)
            ):
                start_pos, start_button = self._drag_start
                if (event.globalPos() - start_pos).manhattanLength() > 12:
                    self._drag_start = None
                    self._start_button_drag(start_button)
            elif event_type == QEvent.DragEnter and event.mimeData().hasText():
                if self._is_valid_button_drag(event.mimeData(), obj):
                    event.acceptProposedAction()
            elif event_type == QEvent.Drop and event.mimeData().hasText():
                if self._is_valid_button_drag(event.mimeData(), obj):
                    source_id = event.mimeData().text()[len(self.DRAG_MIME_PREFIX):]
                    self.move_symbol_button(source_id, obj._symbol_id)
                    event.acceptProposedAction()
        return super().eventFilter(obj, event)

    def _start_button_drag(self, button):
        drag = QDrag(button)
        mime = QMimeData()
        mime.setText(self.DRAG_MIME_PREFIX + button._symbol_id)
        drag.setMimeData(mime)
        drag.exec_(Qt.MoveAction)

    def _is_valid_button_drag(self, mime_data, target_button):
        """Drag zulässig: gleiche Gruppe, anderes Symbol, Ziel ist kein Werkzeug."""
        text = mime_data.text()
        if not text.startswith(self.DRAG_MIME_PREFIX):
            return False
        source_id = text[len(self.DRAG_MIME_PREFIX):]
        source_button = self.symbol_buttons.get(source_id)
        if source_button is None or source_button is target_button:
            return False
        return source_button.parentWidget() is target_button.parentWidget()

    def move_symbol_button(self, source_id, target_id):
        """Button `source_id` vor den Platz von `target_id` verschieben."""
        source_button = self.symbol_buttons.get(source_id)
        target_button = self.symbol_buttons.get(target_id)
        if source_button is None or target_button is None:
            return False
        if source_button is target_button:
            return False
        layout = target_button.parentWidget().layout()
        layout.removeWidget(source_button)
        layout.insertWidget(layout.indexOf(target_button), source_button)
        source_button.show()
        self._save_current_order()
        return True

    # ------------------------------------------------------------------
    # Persistenz der Button-Reihenfolge
    # ------------------------------------------------------------------
    def _category_order_from_layout(self):
        """Aktuelle Reihenfolge je Gruppe aus den Layouts lesen."""
        orders = {}
        for index in range(self.groups_layout.count()):
            group = self.groups_layout.itemAt(index).widget()
            if not isinstance(group, QGroupBox):
                continue
            layout = group.layout()
            ids = []
            for i in range(layout.count()):
                button = layout.itemAt(i).widget()
                if isinstance(button, QPushButton) and getattr(button, "_symbol_id", None):
                    ids.append(button._symbol_id)
            if ids:
                orders[group.title()] = ids
        return orders

    def _save_current_order(self):
        settings = QSettings()
        settings.setValue(self.ORDER_SETTINGS_KEY, json.dumps(self._category_order_from_layout()))

    def _load_saved_order(self):
        settings = QSettings()
        raw = settings.value(self.ORDER_SETTINGS_KEY, "")
        try:
            data = json.loads(raw) if raw else {}
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}
