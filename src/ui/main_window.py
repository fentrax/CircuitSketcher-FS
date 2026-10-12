"""
Hauptfenster - Haupt-Anwendungsfenster
"""
from PyQt5.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
                             QMenuBar, QMenu, QAction, QFileDialog, QMessageBox,
                             QToolBar, QPushButton, QLabel, QGraphicsItem, QCheckBox,
                             QComboBox, QApplication, QShortcut, QScrollArea,
                             QInputDialog)
from PyQt5.QtCore import Qt, QPointF, QPoint, QLineF, QRectF
from PyQt5.QtGui import QKeySequence, QImage, QPainter, QCursor, QColor
from PyQt5.QtCore import QTimer

from ..canvas.grid_canvas import GridCanvas
from ..components.annotations import VoltageAnnotation, CurrentAnnotation
from ..components.contact_mirror import ContactMirrorItem
from ..components.symbol_component import (SymbolComponent, RAIL_SYMBOLS,
                                             RELAY_CONTACT_SYMBOLS, COIL_SYMBOL_IDS)
from ..components.wire import Wire, WIRE_COLOR_PRESETS
from ..symbols import SYMBOLS_DIR, load_symbol_definitions
from .component_toolbar import ComponentToolbar
from .symbol_editor import SymbolEditorDialog
import json
import math
from pathlib import Path


class MainWindow(QMainWindow):
    """Haupt-Anwendungsfenster"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SchaltungsZeichner")
        self.setGeometry(100, 100, 1200, 800)

        self.symbol_directory = SYMBOLS_DIR
        self.symbol_definitions = {}
        self.symbol_errors = []

        self.selected_component_type = None
        self.drawing_wire = False
        self.temp_wire = None
        self.wire_start_point = None
        self.preview_component = None  # Vorschau-Bauteil
        self.preview_orientation = "horizontal"  # Aktuelle Orientierung der Vorschau
        self.preview_rotation_step = 0  # 0/90/180/270°-Schritt für Vorschau und Platzierung
        self._preview_menu_open = False  # Kontextmenü der Vorschau offen?
        self.current_wire_color = tuple(WIRE_COLOR_PRESETS[0][1])
        self.wire_color_combo = None
        self._updating_wire_color_ui = False
        self._pending_selection_sync = False
        self._last_press_scene_pos = None  # zur Erkennung echter Drag-Bewegungen
        self._clipboard = None             # interne Zwischenablage (JSON-Fragment)
        self.current_file = None           # Pfad der geöffneten Datei
        self._dirty = False                # ungespeicherte Änderungen?
        from ..canvas.sheet_frame import DEFAULT_SHEET_META
        self.sheet_meta = dict(DEFAULT_SHEET_META)  # A4-Blatt/Schriftfeld
        # Funktionsschema-Simulation
        self.sim_engine = None
        self.sim_readings = {}
        self._mirror_dialog = None
        self._sim_timer = None
        from PyQt5.QtCore import QTimer
        self._sim_clock = QTimer(self)
        self._sim_clock.timeout.connect(self._sim_tick)
        self.auto_wire_after_place = True  # Leitung nach Auswahl

        self.undo_stack = []
        self.redo_stack = []

        self.setup_ui()
        self.create_menus()
        self.create_toolbar()

        # ESC schaltet auf den Auswahlmodus (wie der Toolbar-Button), bricht
        # aber zusätzlich eine laufende Leitungs-Zeichnung ab.
        QShortcut(QKeySequence.Cancel, self, activated=self.escape_pressed)

    def setup_ui(self):
        """Benutzeroberfläche einrichten"""
        # Zentrales Widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Hauptlayout
        main_layout = QHBoxLayout(central_widget)

        # Bauteil-Toolbar (linke Seite) — in einem Scrollbereich: die Palette
        # ist mit 18 Symbolen höher als manche Fenster, ohne Scrollen würden
        # die Gruppen unten abgeschnitten/gequetscht.
        self.component_toolbar = ComponentToolbar()
        self.component_toolbar.component_selected.connect(self.on_component_selected)
        self.component_toolbar.symbol_edit_requested.connect(self.edit_symbol_by_id)
        self.component_toolbar.setMaximumWidth(200)
        toolbar_scroll = QScrollArea()
        toolbar_scroll.setWidget(self.component_toolbar)
        toolbar_scroll.setWidgetResizable(True)
        toolbar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        toolbar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        toolbar_scroll.setMaximumWidth(220)
        toolbar_scroll.setMinimumWidth(185)
        main_layout.addWidget(toolbar_scroll)

        # Zeichenfläche (Mitte)
        self.canvas = GridCanvas(grid_size=20)

        # Event-Handler für Scene-Events (nicht überschreiben, sondern erweitern)
        original_mouse_press = self.canvas.scene.mousePressEvent
        original_mouse_move = self.canvas.scene.mouseMoveEvent
        original_mouse_release = self.canvas.scene.mouseReleaseEvent

        def enhanced_mouse_press(event):
            self.canvas_mouse_press(event)
            # Original-Handler aufrufen, wenn Event nicht vollständig verarbeitet wurde
            if not event.isAccepted():
                original_mouse_press(event)

        def enhanced_mouse_move(event):
            self.canvas_mouse_move(event)
            if not event.isAccepted():
                original_mouse_move(event)

        def enhanced_mouse_release(event):
            self.canvas_mouse_release(event)
            if not event.isAccepted():
                original_mouse_release(event)

        self.canvas.scene.mousePressEvent = enhanced_mouse_press
        self.canvas.scene.mouseMoveEvent = enhanced_mouse_move
        self.canvas.scene.mouseReleaseEvent = enhanced_mouse_release
        # Automatische Knotenpunkte + optionaler A4-Blattrahmen (Dekoration)
        self.junction_layer = None
        self.sheet_frame = None
        self.sim_overlay = None
        self._ensure_decorations()
        self.canvas.scene.selectionChanged.connect(self.on_scene_selection_changed)
        # Absturzsicherung: alle 3 Minuten bei ungespeicherten Änderungen
        from PyQt5.QtCore import QTimer
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start(3 * 60 * 1000)
        # Vorschau entfernen, wenn die Maus den Zeichenbereich verlässt
        self.canvas.mouse_left_canvas.connect(self._on_mouse_left_canvas)
        self.canvas.setMouseTracking(True)
        main_layout.addWidget(self.canvas, stretch=1)

        # Statusleiste
        self.statusBar().showMessage("Bereit")
        self.load_symbol_library()
        self._update_window_title()

    def load_symbol_library(self):
        """Lädt Symboldefinitionen aus dem Symbolverzeichnis."""
        definitions, errors = load_symbol_definitions(self.symbol_directory)
        self.symbol_definitions = {definition.symbol_id: definition for definition in definitions}
        self.symbol_errors = errors

        self.component_toolbar.set_symbols(definitions)

        if errors:
            for path, message in errors:
                print(f"[Symbol-Ladefehler] {path}: {message}")
            self.statusBar().showMessage(
                f"{len(definitions)} Symbole geladen, {len(errors)} Fehler. Details in der Konsole."
            )
        else:
            self.statusBar().showMessage(f"{len(definitions)} Symbole geladen.")

    def create_menus(self):
        """Menüleiste erstellen"""
        menubar = self.menuBar()

        # Datei-Menü
        file_menu = menubar.addMenu("&Datei")

        new_action = QAction("&Neu", self)
        new_action.setShortcut(QKeySequence.New)
        new_action.triggered.connect(self.new_file)
        file_menu.addAction(new_action)

        open_action = QAction("&Öffnen", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self.open_file)
        file_menu.addAction(open_action)

        save_action = QAction("&Speichern", self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self.save_file)
        file_menu.addAction(save_action)

        file_menu.addSeparator()

        export_png_action = QAction("Als PNG exportieren", self)
        export_png_action.triggered.connect(self.export_png)
        file_menu.addAction(export_png_action)

        export_svg_action = QAction("Als SVG exportieren", self)
        export_svg_action.triggered.connect(self.export_svg)
        file_menu.addAction(export_svg_action)

        file_menu.addSeparator()

        print_action = QAction("&Drucken...", self)
        print_action.setShortcut(QKeySequence.Print)
        print_action.triggered.connect(self.print_file)
        file_menu.addAction(print_action)

        file_menu.addSeparator()

        self.recent_menu = file_menu.addMenu("Zuletzt &geöffnet")
        self.autosave_restore_action = QAction("Absturzsicherung &wiederherstellen...", self)
        self.autosave_restore_action.triggered.connect(self.restore_autosave)
        file_menu.addAction(self.autosave_restore_action)
        self._update_recent_menu()

        file_menu.addSeparator()

        exit_action = QAction("B&eenden", self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Bearbeiten-Menü
        edit_menu = menubar.addMenu("&Bearbeiten")

        undo_action = QAction("&Rückgängig", self)
        undo_action.setShortcut(QKeySequence.Undo)
        undo_action.triggered.connect(self.undo)
        edit_menu.addAction(undo_action)

        redo_action = QAction("&Wiederherstellen", self)
        redo_action.setShortcut(QKeySequence.Redo)
        edit_menu.addAction(redo_action)

        edit_menu.addSeparator()

        copy_action = QAction("&Kopieren", self)
        copy_action.setShortcut(QKeySequence.Copy)
        copy_action.triggered.connect(self.copy_selection)
        edit_menu.addAction(copy_action)

        paste_action = QAction("Einf&ügen", self)
        paste_action.setShortcut(QKeySequence.Paste)
        paste_action.triggered.connect(self.paste_clipboard)
        edit_menu.addAction(paste_action)

        duplicate_action = QAction("&Duplizieren", self)
        duplicate_action.setShortcut(QKeySequence("Ctrl+D"))
        duplicate_action.triggered.connect(self.duplicate_selection)
        edit_menu.addAction(duplicate_action)

        edit_menu.addSeparator()

        delete_action = QAction("&Löschen", self)
        delete_action.setShortcut(QKeySequence.Delete)
        delete_action.triggered.connect(self.delete_selected)
        edit_menu.addAction(delete_action)

        # Ansicht-Menü
        view_menu = menubar.addMenu("&Ansicht")
        self.sheet_toggle_action = QAction("A4-&Blattrahmen", self)
        self.sheet_toggle_action.setCheckable(True)
        self.sheet_toggle_action.setChecked(self.sheet_meta.get("visible", False))
        self.sheet_toggle_action.toggled.connect(self._set_sheet_visible)
        view_menu.addAction(self.sheet_toggle_action)

        sheet_edit_action = QAction("&Schriftfeld bearbeiten...", self)
        sheet_edit_action.triggered.connect(self.edit_sheet_meta)
        view_menu.addAction(sheet_edit_action)

        self.auto_wire_action = QAction("&Leitung nach Platzierung", self)
        self.auto_wire_action.setCheckable(True)
        self.auto_wire_action.setChecked(self.auto_wire_after_place)
        self.auto_wire_action.setToolTip("Nach dem Platzieren eines Bauteils automatisch eine Leitung am nächsten Anschluss beginnen")
        self.auto_wire_action.toggled.connect(self._set_auto_wire)
        view_menu.addAction(self.auto_wire_action)

        # Werkzeuge-Menü
        tools_menu = menubar.addMenu("&Werkzeuge")

        symbol_editor_action = QAction("Symbol-Editor...", self)
        symbol_editor_action.triggered.connect(self.show_symbol_editor)
        tools_menu.addAction(symbol_editor_action)

        mirror_action = QAction("Kontakt&spiegel...", self)
        mirror_action.triggered.connect(self.show_contact_mirror)
        tools_menu.addAction(mirror_action)

        # Hilfe-Menü
        help_menu = menubar.addMenu("&Hilfe")

        guide_action = QAction("&Anleitung", self)
        guide_action.setShortcut(QKeySequence(Qt.Key_F1))
        guide_action.triggered.connect(self.show_guide)
        help_menu.addAction(guide_action)

        help_menu.addSeparator()

        about_action = QAction("&Über", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def create_toolbar(self):
        """Toolbar mit häufigen Aktionen erstellen"""
        toolbar = QToolBar("Haupt-Toolbar")
        self.addToolBar(toolbar)

        # Hinweis-Label
        info_label = QLabel("Tipp: Rechtsklick auf Bauteil für Optionen")
        info_label.setStyleSheet("padding: 5px; color: #666;")
        toolbar.addWidget(info_label)

        toolbar.addSeparator()

        # Simulation (Funktionsschema): Start/Stop/Reset
        self.sim_start_btn = QPushButton("▶ Simulation")
        self.sim_start_btn.setToolTip("Simulation starten: Schalter klicken, "
                                      "Relais/Lampen/Motoren reagieren")
        self.sim_start_btn.clicked.connect(self.start_simulation)
        toolbar.addWidget(self.sim_start_btn)

        self.sim_stop_btn = QPushButton("■ Stop")
        self.sim_stop_btn.setToolTip("Simulation beenden (auch ESC)")
        self.sim_stop_btn.clicked.connect(self.stop_simulation)
        self.sim_stop_btn.setEnabled(False)
        toolbar.addWidget(self.sim_stop_btn)

        self.sim_reset_btn = QPushButton("⟲")
        self.sim_reset_btn.setToolTip("Simulation zurücksetzen (Schalter- und "
                                      "Relaisstellungen auf Anfang)")
        self.sim_reset_btn.clicked.connect(self.reset_simulation)
        self.sim_reset_btn.setEnabled(False)
        toolbar.addWidget(self.sim_reset_btn)

        mirror_btn = QPushButton("🪞 Kontaktspiegel")
        mirror_btn.setToolTip("Zuordnung Relais → Kontakte (öffnet sich auch "
                              "automatisch beim Start der Simulation)")
        mirror_btn.clicked.connect(self.show_contact_mirror)
        toolbar.addWidget(mirror_btn)

        toolbar.addSeparator()

        # Raster ein-/ausblenden Checkbox
        self.grid_checkbox = QCheckBox("Raster anzeigen")
        self.grid_checkbox.setChecked(True)
        self.grid_checkbox.stateChanged.connect(self.toggle_grid)
        toolbar.addWidget(self.grid_checkbox)

        toolbar.addSeparator()
        color_label = QLabel("Linienfarbe:")
        color_label.setStyleSheet("padding-left: 6px;")
        toolbar.addWidget(color_label)

        self.wire_color_combo = QComboBox()
        self.wire_color_combo.setToolTip("Farbe fuer neue Leitungen; wirkt auch auf ausgewaehlte Leitungen.")
        for name, rgb in WIRE_COLOR_PRESETS:
            rgb_tuple = self._coerce_rgb(rgb)
            self.wire_color_combo.addItem(name, rgb_tuple)
            index = self.wire_color_combo.count() - 1
            self.wire_color_combo.setItemData(index, QColor(*rgb_tuple), Qt.DecorationRole)
        self.wire_color_combo.currentIndexChanged.connect(self.on_wire_color_changed)
        initial_index = self._index_for_wire_color(self.current_wire_color)
        if initial_index != -1:
            self.wire_color_combo.setCurrentIndex(initial_index)
        toolbar.addWidget(self.wire_color_combo)

        toolbar.addSeparator()

        # Zoom-Buttons
        zoom_in_btn = QPushButton("🔍+")
        zoom_in_btn.setToolTip("Hineinzoomen")
        zoom_in_btn.clicked.connect(self.canvas.zoom_in)
        toolbar.addWidget(zoom_in_btn)

        zoom_out_btn = QPushButton("🔍-")
        zoom_out_btn.setToolTip("Herauszoomen")
        zoom_out_btn.clicked.connect(self.canvas.zoom_out)
        toolbar.addWidget(zoom_out_btn)

        zoom_reset_btn = QPushButton("100%")
        zoom_reset_btn.setToolTip("Zoom zurücksetzen")
        zoom_reset_btn.clicked.connect(self.canvas.zoom_reset)
        toolbar.addWidget(zoom_reset_btn)

        toolbar.addSeparator()

        # Alles löschen Button
        clear_btn = QPushButton("Alles löschen")
        clear_btn.clicked.connect(self.clear_canvas)
        toolbar.addWidget(clear_btn)

    def show_symbol_editor(self):
        """Symbol-Editor als separates Werkzeug öffnen"""
        editor = SymbolEditorDialog(self, symbols_dir=self.symbol_directory)
        editor.exec_()

        # Nach dem Schließen des Editors die Symbol-Bibliothek neu laden
        self.load_symbol_library()
        self.statusBar().showMessage("Symbol-Bibliothek neu geladen")

    def edit_symbol_component(self, component):
        """Symbol eines platzierten Bauteils im Symbol-Editor bearbeiten."""
        symbol_id = getattr(component, "symbol_id", None)
        if symbol_id is None:
            return
        self.edit_symbol_by_id(symbol_id)

    def edit_symbol_by_id(self, symbol_id):
        """Symbol anhand seiner ID im Editor öffnen (Rechtsklick-Pfad).

        Öffnet den Editor mit der Definition dieses Symbols; 'Speichern'
        schreibt direkt in die Original-Datei. Nach dem Schließen werden die
        Bibliothek und ALLE platzierten Instanzen dieses Symbols auf die
        geänderte Definition aktualisiert (Position, Drehung und
        Platzhalterwerte bleiben erhalten).
        """
        definition = self.symbol_definitions.get(symbol_id)
        if definition is None or not Path(definition.file_path).exists():
            self.statusBar().showMessage(
                f"Symboldefinition für '{symbol_id}' nicht gefunden."
            )
            return

        editor = SymbolEditorDialog(self, symbols_dir=self.symbol_directory)
        editor.load_symbol_file(str(definition.file_path))
        editor.exec_()

        self.load_symbol_library()
        self._refresh_symbol_instances(symbol_id)
        self.statusBar().showMessage(f"Symbol '{symbol_id}' aktualisiert")

    def _refresh_symbol_instances(self, symbol_id):
        """Alle platzierten Instanzen eines Symbols auf die neu geladene
        Definition umstellen (Live-Aktualisierung nach 'Symbol ändern')."""
        definition = self.symbol_definitions.get(symbol_id)
        if definition is None:
            return
        for item in list(self.canvas.scene.items()):
            if getattr(item, "symbol_id", None) != symbol_id:
                continue
            if not isinstance(item, SymbolComponent):
                continue
            item.definition = definition
            item.component_type = definition.name
            if item.orientation not in definition.orientations:
                # Geometrie hat die Orientierung nicht mehr -> zurücksetzen
                item.orientation = "horizontal"
                item.rotation_step = 0
            item.apply_orientation()
            item.update()

    def _clear_preview(self):
        """Halbtransparente Platzierungs-Vorschau aus der Szene entfernen.

        Wird vor jedem Werkzeug-/Symbolwechsel und nach Platzierung aufgerufen,
        damit keine verwaisten Vorschau-Symbole sichtbar bleiben (Bugfix).
        """
        if not self.preview_component:
            return
        try:
            if self.preview_component.scene() == self.canvas.scene:
                self.canvas.scene.removeItem(self.preview_component)
        except (RuntimeError, AttributeError):
            # Item wurde bereits gelöscht
            pass
        self.preview_component = None
        # Sicherheitsnetz: frei gewordene Label-Texte mitkehren (früher
        # blieben bei Vorschau-Rotationen Geister-Kopien in der Szene).
        for item in list(self.canvas.scene.items()):
            if getattr(item, "is_placeholder_text", False) and item.parentItem() is None:
                self.canvas.scene.removeItem(item)

    def _on_mouse_left_canvas(self):
        """Maus hat den Zeichenbereich verlassen: Vorschau ausblenden.

        Betrifft nur die halbtransparente Platzierungs-Vorschau an der
        Mausposition — platzierte Bauteile und eine laufende Leitungs-
        Zeichnung (temp_wire) bleiben unberührt. Während das Rechtsklick-
        Kontextmenü der Vorschau offen ist, wird nichts entfernt.
        """
        if self._preview_menu_open:
            return
        self._clear_preview()

    def _cancel_pending_wire(self):
        """Eine laufende Leitungs-Zeichnung abbrechen (Vorschau entfernen)."""
        if self.temp_wire is not None:
            try:
                if self.temp_wire.scene() == self.canvas.scene:
                    self.canvas.scene.removeItem(self.temp_wire)
            except (RuntimeError, AttributeError):
                pass
            self.temp_wire = None
        self.drawing_wire = False
        self.wire_start_point = None

    def escape_pressed(self):
        """ESC: laufende Leitung abbrechen, Werkzeug aber BEHALTEN, damit
        sofort die nächste gesetzt werden kann. Ohne aktives Zeichenwerkzeug
        (oder während der Simulation) wie bisher auf Auswahl schalten."""
        if self.sim_engine is not None:
            self.activate_select_mode()
            return
        if self.selected_component_type == "wire":
            had_pending = self.drawing_wire
            self._cancel_pending_wire()
            if had_pending:
                self.statusBar().showMessage(
                    "Leitung abgebrochen – Werkzeug bleibt aktiv, "
                    "nächster Klick setzt eine neue Leitung.")
                return
        self.activate_select_mode()

    def activate_select_mode(self):
        """Auf den Auswahlmodus schalten (auch per ESC).

        Bricht zusätzlich eine eventuell laufende Leitungs-Zeichnung ab und
        beendet die Simulation, weil on_component_selected('select') beides
        nicht zurücksetzt.
        """
        if self.sim_engine is not None:
            self.stop_simulation()
        self._cancel_pending_wire()
        # Den Rest (selected_component_type=None, RubberBandDrag, Vorschau löschen)
        # übernimmt on_component_selected('select').
        self.on_component_selected("select")

    def on_component_selected(self, component_type):
        """Bauteilauswahl von Toolbar verarbeiten"""
        self.selected_component_type = component_type
        self.preview_orientation = "horizontal"
        self.preview_rotation_step = 0

        if component_type != "wire":
            # Werkzeugwechsel: eine noch laufende Leitungs-Zeichnung abbrechen,
            # sonst bleibt sie als eingefrorenes Reststueck in der Szene liegen
            # und verfaelscht das automatische Trennen beim Platzieren.
            self._cancel_pending_wire()

        if component_type == "wire":
            self.statusBar().showMessage("Leitungsmodus: Klicken zum Starten, nochmal klicken zum Beenden")
        elif component_type in ("voltage", "current"):
            self.canvas.setDragMode(self.canvas.NoDrag)
            hint = ("Spannungsmodus: Auf ein Bauteil klicken, um den Spannungsbogen "
                    "daraufzusetzen (Doppelklick ändert den Wert).")
            if component_type == "current":
                hint = ("Strommodus: Auf eine Leitung klicken, um den Strompfeil "
                        "daraufzusetzen (Doppelklick ändert den Wert).")
            self.statusBar().showMessage(hint)
        elif component_type == "contact_mirror":
            self.canvas.setDragMode(self.canvas.NoDrag)
            self.statusBar().showMessage(
                "Kontakt-Spiegel: Klicken zum Platzieren — zeigt alle Kontakte "
                "eines Relais (Rechtsklick: Relais zuweisen).")
        elif component_type == "select":
            self.selected_component_type = None
            self.canvas.setDragMode(self.canvas.RubberBandDrag)
            self.statusBar().showMessage("Auswahlmodus")
            self._clear_preview()
        else:
            # WICHTIG: beim Wechsel von Symbol A -> B muss die alte Vorschau
            # entfernt werden, sonst bleibt sie bis zur nächsten Mausbewegung sichtbar.
            self._clear_preview()
            self.canvas.setDragMode(self.canvas.NoDrag)
            definition = self.symbol_definitions.get(component_type)
            display_name = definition.name if definition else component_type
            self.statusBar().showMessage(
                f"Auf Zeichenfläche klicken, um {display_name} zu platzieren "
                f"(aktuell {self.preview_rotation_step * 90}°). Rechtsklick rotiert."
            )

    def canvas_mouse_press(self, event):
        """Mausklick auf Zeichenfläche verarbeiten"""
        # Mittlere Maustaste für Pan ignorieren - wird vom View (GridCanvas) behandelt
        if event.button() == Qt.MiddleButton:
            event.ignore()
            return

        pos = event.scenePos()
        snapped_pos = self.canvas.snap_to_grid(pos)
        self._last_press_scene_pos = QPointF(pos)

        # Laufende Simulation: Klicks bedienen Schalter/Taster, Editieren gesperrt
        if (self.sim_engine is not None and event.button() == Qt.LeftButton):
            self._sim_press(event)
            return

        if event.button() == Qt.LeftButton:
            if self.selected_component_type == "wire":
                if not self.drawing_wire:
                    # Leitung zeichnen starten
                    self.drawing_wire = True
                    self.wire_start_point = snapped_pos
                    self.temp_wire = Wire(
                        snapped_pos,
                        snapped_pos,
                        grid_size=self.canvas.grid_size,
                        color=self.current_wire_color,
                    )
                    self.canvas.scene.addItem(self.temp_wire)
                else:
                    # Leitung beenden und GLEICH die nächste am Endpunkt
                    # beginnen (kontinuierliches Zeichnen von Linienzügen).
                    self.temp_wire.update_end_point(snapped_pos)
                    # Liegt die neue Leitung über bestehenden Bauteilen,
                    # wird sie an deren Polen getrennt und angedockt.
                    self._split_new_wire_at_components(self.temp_wire)
                    self._push_undo_snapshot()
                    self.wire_start_point = snapped_pos
                    self.temp_wire = Wire(
                        snapped_pos,
                        snapped_pos,
                        grid_size=self.canvas.grid_size,
                        color=self.current_wire_color,
                    )
                    self.canvas.scene.addItem(self.temp_wire)
                    self.statusBar().showMessage(
                        "Leitung platziert – nächste Leitung läuft am Endpunkt weiter "
                        "(ESC beendet)."
                    )

            elif self.selected_component_type in ("voltage", "current"):
                # Messwert-Annotation platzieren (Spannungsbogen/Strompfeil)
                self._place_measurement_annotation(pos)

            elif self.selected_component_type == "contact_mirror":
                # Kontakt-Spiegel für ein Relais platzieren
                self._place_contact_mirror(snapped_pos)

            elif self.selected_component_type:
                # Bauteil platzieren - mit gespeicherter Rotation
                component = self.create_component(
                    self.selected_component_type,
                    snapped_pos.x(),
                    snapped_pos.y(),
                    orientation=self.preview_orientation,
                    rotation_step=self.preview_rotation_step,
                )
                if component:
                    self.canvas.scene.addItem(component)
                    # Falls das Bauteil Pole hat und nicht das
                    # Durchführungs-Symbol 'Strom' ist: bestehende Leitungen,
                    # die durch den Platzierungspunkt verlaufen, an den Polen
                    # aufteilen und andocken.
                    split_count = self._split_wires_at_component(component, snapped_pos)
                    self._push_undo_snapshot()
                    definition = self.symbol_definitions.get(self.selected_component_type)
                    display_name = definition.name if definition else self.selected_component_type
                    message = (
                        f"{display_name} ({self.preview_rotation_step * 90}°) platziert "
                        f"bei ({int(snapped_pos.x())}, {int(snapped_pos.y())})"
                    )
                    if split_count:
                        message += f" – {split_count} Leitung(en) aufgeteilt"
                    self.statusBar().showMessage(message)

                    # Vorschau entfernen nach Platzierung
                    self._clear_preview()
                    # Leitung nach Auswahl: automatisch am nächsten Pol starten
                    if self.auto_wire_after_place and component is not None:
                        self._start_wire_at_nearest_pole(component, snapped_pos)

        elif event.button() == Qt.RightButton:
            # Rechtsklick beendet das Leitungszeichnen: laufendes Segment
            # verwerfen, fertige Segmente bleiben — das WERKZEUG bleibt aktiv,
            # der nächste Linksklick setzt sofort die nächste Leitung.
            if self.selected_component_type == "wire":
                had_pending = self.drawing_wire
                self._cancel_pending_wire()
                if had_pending:
                    self.statusBar().showMessage(
                        "Leitung beendet – Klick setzt die nächste (ESC beendet das Werkzeug).")
                event.accept()
                return
            # Rechtsklick auf Vorschau-Bauteil -> Menü anzeigen
            if self.preview_component and self.selected_component_type and self.selected_component_type not in ["wire", "select"]:
                self.show_preview_context_menu(event)

    def canvas_mouse_move(self, event):
        """Mausbewegung auf Zeichenfläche verarbeiten"""
        # Wenn gerade gepannt wird, ignorieren - wird vom View behandelt
        if self.canvas._is_panning:
            event.ignore()
            return

        pos = event.scenePos()
        snapped_pos = self.canvas.snap_to_grid(pos)

        if self.drawing_wire and self.temp_wire:
            # Leitung-Vorschau aktualisieren
            self.temp_wire.update_end_point(snapped_pos)
        elif (self.selected_component_type
              and self.selected_component_type not in ["wire", "select", "voltage", "current", "contact_mirror"]):
            # Bauteil-Vorschau anzeigen
            self._clear_preview()

            self.preview_component = self.create_component(
                self.selected_component_type,
                snapped_pos.x(),
                snapped_pos.y(),
                orientation=self.preview_orientation,
                rotation_step=self.preview_rotation_step,
            )
            if self.preview_component:
                self.preview_component.setOpacity(0.5)  # Halbtransparent
                self.preview_component.setFlag(QGraphicsItem.ItemIsMovable, False)
                self.preview_component.setFlag(QGraphicsItem.ItemIsSelectable, False)
                self.canvas.scene.addItem(self.preview_component)

    def canvas_mouse_release(self, event):
        """Mausloslassen auf Zeichenfläche verarbeiten"""
        # Mittlere Maustaste für Pan ignorieren - wird vom View behandelt
        if event.button() == Qt.MiddleButton:
            event.ignore()
            return
        if (self.sim_engine is not None and event.button() == Qt.LeftButton):
            self._sim_release(event)
            return
        # Wenn gerade ein Bauteil oder eine Leitung per Drag bewegt wurde,
        # einen Undo-Snapshot ablegen, damit die Bewegung rückgängig ist.
        if event.button() == Qt.LeftButton and self.selected_component_type in (None, "select"):
            selected = self.canvas.scene.selectedItems()
            if selected:
                # Verschobene Bauteile trennen liegende Leitungen auf —
                # dasselbe Andocken wie beim Platzieren (nur bei echter
                # Bewegung, nicht bei bloßem Anklicken zum Auswählen).
                moved = (self._last_press_scene_pos is not None
                         and (event.scenePos() - self._last_press_scene_pos).manhattanLength() > 2)
                if moved:
                    split_count = 0
                    for item in list(selected):
                        if isinstance(item, SymbolComponent):
                            split_count += self._split_component_on_wires(item)
                    if split_count:
                        self.statusBar().showMessage(
                            f"{split_count} Leitung(en) am Bauteil angedockt "
                            "(rückgängig mit Ctrl+Z)."
                        )
                self._push_undo_snapshot()

    def show_preview_context_menu(self, event):
        """Kontextmenü für Vorschau-Bauteil anzeigen"""
        menu = QMenu()

        # Drehen
        rotate_action = QAction("Drehen (90°)", None)
        rotate_action.triggered.connect(lambda: self.rotate_preview())
        menu.addAction(rotate_action)

        # Menü an Mausposition anzeigen; solange es offen ist, bewegt sich die
        # Maus ausserhalb des Canvas -> Vorschau darf nicht entfernt werden.
        self._preview_menu_open = True
        try:
            menu.exec_(event.screenPos())
        finally:
            self._preview_menu_open = False

    def rotate_preview(self):
        """Vorschau-Bauteil um 90° weiterdrehen (0/90/180/270)."""
        self.preview_rotation_step = (self.preview_rotation_step + 1) % 4
        self.preview_orientation = "horizontal" if self.preview_rotation_step % 2 == 0 else "vertical"

        # Vorschau aktualisieren
        if self.preview_component and hasattr(self.preview_component, "rotate_component"):
            self.preview_component.rotate_component()

        definition = self.symbol_definitions.get(self.selected_component_type)
        display_name = definition.name if definition else "Bauteil"
        self.statusBar().showMessage(
            f"{display_name}-Vorschau auf {self.preview_rotation_step * 90}° eingestellt "
            f"– Linksklick zum Platzieren"
        )

    def create_component(self, component_type, x, y, orientation="horizontal", rotation_step=0):
        """Bauteil basierend auf Symboldefinition erstellen"""
        definition = self.symbol_definitions.get(component_type)
        if not definition:
            return None
        component = SymbolComponent(
            definition,
            orientation=orientation,
            x=x,
            y=y,
            rotation_step=rotation_step,
        )
        # Funktionsschema: Spulen automatisch benennen (K1, K2 …/KT1 …),
        # Kontakte dem ersten vorhandenen Relais zuweisen.
        self._assign_default_fs_name(component)
        return component

    # ------------------------------------------------------------------
    # Messwert-Annotationen (Spannungsbogen / Strompfeil)
    # ------------------------------------------------------------------

    def _component_at(self, scene_pos):
        """Oberstes Bauteil an der Position liefern (Vorschau ausgenommen)."""
        for item in self.canvas.scene.items(scene_pos):
            if isinstance(item, SymbolComponent) and item is not self.preview_component:
                return item
        return None

    def _wire_at(self, scene_pos):
        """Leitung unter dem Punkt liefern (innerhalb eines Rasters)."""
        tolerance = float(self.canvas.grid_size)
        for item in self.canvas.scene.items():
            if getattr(item, "is_handle", False) or not isinstance(item, Wire):
                continue
            if item is self.temp_wire:
                continue
            if self._point_on_wire(scene_pos, item, tolerance):
                return item
        return None

    def _place_measurement_annotation(self, scene_pos):
        """Spannungsbogen auf Bauteil oder Strompfeil auf Leitung setzen."""
        if self.selected_component_type == "voltage":
            component = self._component_at(scene_pos)
            if component is None:
                self.statusBar().showMessage(
                    "Kein Bauteil an dieser Stelle – auf ein Bauteil klicken."
                )
                return
            annotation = VoltageAnnotation(component, "U")
            # Bogen immer über der Bauteilmitte (Pol-Mittelpunkt) setzen,
            # nicht an der Klickstelle — sonst sitzt er auf dem Ursprung
            # (linker Pol) auf.
            poles = component.get_pole_points()
            if len(poles) == 2:
                mid = QPointF((poles[0].x() + poles[1].x()) / 2.0,
                              (poles[0].y() + poles[1].y()) / 2.0)
                annotation.setPos(component.mapFromScene(mid))
            component.annotations.append(annotation)
            self._push_undo_snapshot()
            annotation.edit_value()
            self.statusBar().showMessage(
                "Spannungsbogen platziert – Doppelklick ändert den Wert, Ziehen verschiebt."
            )
        elif self.selected_component_type == "current":
            wire = self._wire_at(scene_pos)
            if wire is None:
                self.statusBar().showMessage(
                    "Keine Leitung an dieser Stelle – auf eine Leitung klicken."
                )
                return
            angle = math.degrees(math.atan2(
                wire.end_point.y() - wire.start_point.y(),
                wire.end_point.x() - wire.start_point.x()))
            # Fusspunkt des Klicks auf die Leitung projizieren: der Pfeil sitzt
            # exakt auf der Leitungsachse statt an der (ungenauen) Klickstelle.
            wire_line = QLineF(wire.start_point, wire.end_point)
            target = self._project_point_on_line(scene_pos, wire_line)
            annotation = CurrentAnnotation(wire, "I", angle)
            annotation.setPos(wire.mapFromScene(target))
            wire.annotations.append(annotation)
            self._push_undo_snapshot()
            annotation.edit_value()
            self.statusBar().showMessage(
                "Strompfeil platziert – Doppelklick ändert den Wert, Rechtsklick dreht die Richtung."
            )

    # ------------------------------------------------------------------
    # Kontakt-Spiegel (platzierbares Element, ein Relais)
    # ------------------------------------------------------------------
    def _default_relay_name(self):
        """Niedrigstes vorhandenes Sofortrelais (K1 vor K2/K10), sonst 'K1'."""
        plain = []
        for item in self.canvas.scene.items():
            if getattr(item, "symbol_id", "") == "relay_coil":
                name = str(item.placeholder_values.get("name", "")).strip()
                if name:
                    plain.append(name)
        plain.sort(key=lambda n: (len(n), n))
        return plain[0] if plain else "K1"

    def _place_contact_mirror(self, scene_pos):
        """Kontakt-Spiegel für ein Relais an der Klickstelle platzieren."""
        mirror = ContactMirrorItem(
            self._default_relay_name(),
            engine_provider=lambda: self.sim_engine,
            grid_size=self.canvas.grid_size,
        )
        mirror.setPos(scene_pos)
        self.canvas.scene.addItem(mirror)
        self._push_undo_snapshot()
        self._mark_dirty()
        self.statusBar().showMessage(
            "Kontakt-Spiegel platziert – Rechtsklick: Relais zuweisen, "
            "Doppelklick: Name ändern."
        )

    def refresh_mirrors(self):
        """Alle Kontakt-Spiegel neu zeichnen (nach Zuweisung/Undo/Sim-Takt)."""
        for item in self.canvas.scene.items():
            if isinstance(item, ContactMirrorItem):
                item.refresh()

    def _try_split_wire_at_poles(self, wire, in_pole, out_pole, pole_axis):
        """Eine Leitung an den Polen eines Bauteils trennen, wenn sie überlappt.

        Einheitliche Regel für alle Trenn-Richtungen: Die Pole-Spanne des
        Bauteils muss die Leitung überlappen (beide Pole nahe der Leitungs-
        geraden, Spanne schneidet das Segment). Docks = auf das Segment
        begrenzte Pol-Projektionen, nach t sortiert; Randstücke unter 1 px
        entstehen nicht. Eine Leitung, die bereits AN einem Pol endet (z. B.
        magnetisch angedockt), wird nicht erneut getrennt.

        Rückgabe: Liste der neu entstandenen Leitungen (leer = nicht getrennt).
        """
        tolerance = float(self.canvas.grid_size)
        start = QPointF(wire.start_point)
        end = QPointF(wire.end_point)
        wire_line = QLineF(start, end)
        seg_sq = wire_line.dx() ** 2 + wire_line.dy() ** 2
        if seg_sq == 0:
            return []
        if not self._axis_parallel(pole_axis, wire_line):
            return []
        in_pole, out_pole = QPointF(in_pole), QPointF(out_pole)

        def pole_t(p):
            return ((p.x() - start.x()) * wire_line.dx()
                    + (p.y() - start.y()) * wire_line.dy()) / seg_sq

        def foot(t):
            return QPointF(start.x() + t * wire_line.dx(),
                           start.y() + t * wire_line.dy())

        in_t, out_t = pole_t(in_pole), pole_t(out_pole)
        # Beide Pole nahe der (unbegrenzten) Leitungsgeraden?
        for p, t in ((in_pole, in_t), (out_pole, out_t)):
            if (p - foot(t)).manhattanLength() > tolerance:
                return []
        # Spanne ohne Überlappung mit dem Segment: nichts zu trennen. Die
        # Bauteilmitte muss NICHT auf der Leitung liegen — reicht eine
        # Bauteilhälfte über, wird die Leitung bis zum überdeckten Pol
        # zurückgekürzt (vorher wurde dafür gar nicht getrennt).
        if max(in_t, out_t) <= 0.0 or min(in_t, out_t) >= 1.0:
            return []
        # Bereits an einem Pol angedockte Leitung nicht erneut trennen.
        for pole in (in_pole, out_pole):
            for wend in (start, end):
                if (pole - wend).manhattanLength() <= 2.0:
                    return []
        # Docks auf das Segment begrenzen und in Leitungsrichtung sortieren,
        # damit die beiden Stücke start→dock bzw. dock→end ergeben.
        t_lo, t_hi = (in_t, out_t) if in_t <= out_t else (out_t, in_t)
        dock_lo = foot(max(0.0, min(1.0, t_lo)))
        dock_hi = foot(max(0.0, min(1.0, t_hi)))
        if (dock_lo - dock_hi).manhattanLength() < 2.0:
            return []
        color = wire.color_rgb()
        self.canvas.scene.removeItem(wire)
        pieces = []
        if (dock_lo - start).manhattanLength() > 1.0:
            piece = Wire(start, QPointF(dock_lo),
                         grid_size=self.canvas.grid_size, color=color)
            self.canvas.scene.addItem(piece)
            pieces.append(piece)
        if (end - dock_hi).manhattanLength() > 1.0:
            piece = Wire(QPointF(dock_hi), end,
                         grid_size=self.canvas.grid_size, color=color)
            self.canvas.scene.addItem(piece)
            pieces.append(piece)
        return pieces

    def _split_wires_at_component(self, component, placement_pos):
        """Leitungen am platzierten/verschobenen Bauteil aufteilen und andocken.

        Voraussetzungen für ein Splitting:
        - Bauteil hat mindestens 2 Pole (siehe SymbolComponent.get_pole_points():
          Anschlusspunkte, sonst kleine Kreise/Linien-Enden).
        - Bauteil ist NICHT das Durchführungs-Symbol 'Strom' (trennt nicht).

        Jede Leitung, die von der Pole-Spanne des Bauteils überlappt wird,
        wird an den Polen durchtrennt und angedockt (Details siehe
        _try_split_wire_at_poles). Der Platzierungspunkt dient nur für den
        Hinweis auf quer stehende Bauteile.

        Rückgabe: Anzahl der aufgeteilten Leitungen (für die Statusmeldung).
        """
        # 'Strom' ist eine Durchführung und darf die Leitung nicht trennen.
        if getattr(component, "symbol_id", "") == "Strom":
            return 0

        poles = component.get_pole_points()
        if len(poles) < 2:
            return 0
        in_pole, out_pole = poles[0], poles[1]
        pole_axis = QLineF(QPointF(in_pole), QPointF(out_pole))
        tolerance = float(self.canvas.grid_size)

        split_count = 0
        skipped_transverse = False
        for item in list(self.canvas.scene.items()):
            if getattr(item, "is_handle", False):
                continue
            if not isinstance(item, Wire):
                continue
            if item is self.temp_wire:
                continue  # laufende Zeichen-Vorschau ist keine echte Leitung
            wire_line = QLineF(item.start_point, item.end_point)
            if not self._axis_parallel(pole_axis, wire_line):
                # Hinweis nur, wenn die Leitung tatsächlich am Bauteil
                # vorbeiführt (Treffernähe am Platzierungspunkt).
                near = self._project_point_on_line(placement_pos, wire_line)
                if (QPointF(placement_pos) - near).manhattanLength() <= tolerance:
                    skipped_transverse = True
                continue
            if self._try_split_wire_at_poles(item, in_pole, out_pole, pole_axis):
                split_count += 1

        if skipped_transverse and not split_count:
            self.statusBar().showMessage(
                "Bauteil steht quer zur Leitung – bitte passend drehen "
                "(Rechtsklick auf die Vorschau)."
            )
        return split_count

    def _split_component_on_wires(self, component):
        """Verschobenes Bauteil: liegende Leitungen auftrennen und andocken."""
        poles = component.get_pole_points()
        if len(poles) < 2:
            return 0
        mid = QPointF((poles[0].x() + poles[1].x()) / 2.0,
                      (poles[0].y() + poles[1].y()) / 2.0)
        return self._split_wires_at_component(component, mid)

    def _split_new_wire_at_components(self, wire):
        """Frisch gezeichnete Leitung an bestehenden Bauteilen auftrennen.

        Spiegelrichtung zu _split_wires_at_component (dort trennt ein Bauteil
        bestehende Leitungen, hier eine neue Leitung an bestehenden Bauteilen)
        — dieselbe Überlappungs-Regel via _try_split_wire_at_poles, als
        Worklist (eine neue Leitung kann mehrere Bauteile überqueren; neue
        Stücke werden erneut geprüft).
        """
        components = [
            item for item in list(self.canvas.scene.items())
            if isinstance(item, SymbolComponent)
            and getattr(item, "symbol_id", "") != "Strom"
        ]
        worklist = [wire]
        split_count = 0
        while worklist and split_count < 16:
            current = worklist.pop()
            wire_line = QLineF(current.start_point, current.end_point)
            for component in components:
                poles = component.get_pole_points()
                if len(poles) < 2:
                    continue
                pole_axis = QLineF(QPointF(poles[0]), QPointF(poles[1]))
                if not self._axis_parallel(pole_axis, wire_line):
                    continue
                pieces = self._try_split_wire_at_poles(
                    current, poles[0], poles[1], pole_axis)
                if pieces:
                    worklist.extend(pieces)
                    split_count += 1
                    break  # `current` ist ersetzt — nächste Leitung aus der Liste
        if split_count:
            self.statusBar().showMessage(
                f"Leitung an {split_count} Bauteil(en) angedockt "
                "(rückgängig mit Ctrl+Z)."
            )
        return split_count

    @staticmethod
    def _axis_parallel(axis, wire_line, min_cos=0.85):
        """Prüfen, ob die Pole-Achse (annähernd) parallel zur Leitung liegt."""
        ax, ay = axis.dx(), axis.dy()
        wx, wy = wire_line.dx(), wire_line.dy()
        a_len = (ax * ax + ay * ay) ** 0.5
        w_len = (wx * wx + wy * wy) ** 0.5
        if a_len == 0 or w_len == 0:
            return False
        cos_angle = (ax * wx + ay * wy) / (a_len * w_len)
        return abs(cos_angle) >= min_cos

    @staticmethod
    def _project_point_on_line(point, line):
        """Senkrechte Projektion eines Punkts auf die Linie (Segment begrenzt)."""
        dx, dy = line.dx(), line.dy()
        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            return QPointF(line.p1())
        t = ((point.x() - line.x1()) * dx + (point.y() - line.y1()) * dy) / length_sq
        t = max(0.0, min(1.0, t))
        return QPointF(line.x1() + t * dx, line.y1() + t * dy)

    @staticmethod
    def _point_on_wire(point, wire, tolerance):
        """Liegt `point` auf der Wire-Linie (innerhalb tolerance)?"""
        line = QLineF(wire.start_point, wire.end_point)
        # Schnell-Ausschluss: Punkt im erweiterten Bounding-Rechteck?
        rect = QRectF(line.p1(), line.p2()).normalized()
        if not rect.adjusted(-tolerance, -tolerance, tolerance, tolerance).contains(point):
            return False
        # Lotrechtster Abstand Punkt <-> Gerade, begrenzt auf das Segment.
        # QLineF liefert mit .length() die Segementlänge; wir benutzen die
        # Projektion auf den Richtungsvektor, um sicherzustellen, dass der
        # Punkt tatsächlich zwischen den Endpunkten liegt.
        seg = line.length()
        if seg == 0:
            return False
        dx = line.dx()
        dy = line.dy()
        # Projektionsparameter t (0..1 = innerhalb des Segments)
        t = ((point.x() - line.x1()) * dx + (point.y() - line.y1()) * dy) / (seg * seg)
        if t < 0.0 or t > 1.0:
            return False
        # Senkrechter Abstand
        proj_x = line.x1() + t * dx
        proj_y = line.y1() + t * dy
        dist = ((point.x() - proj_x) ** 2 + (point.y() - proj_y) ** 2) ** 0.5
        return dist <= tolerance

    # ------------------------------------------------------------------
    # Undo / Redo (Snapshot-basiert)
    # ------------------------------------------------------------------
    MAX_UNDO_STACK = 50

    def _capture_snapshot(self):
        """Vollständiger JSON-Snapshot des aktuellen Szenenzustands."""
        components_data = []
        wires_data = []
        annotations_data = []
        for item in self.canvas.scene.items():
            if getattr(item, "is_handle", False):
                continue  # Griffpunkte sind reine UI, kein eigener Zustand
            if isinstance(item, SymbolComponent):
                components_data.append({
                    "type": "symbol",
                    "symbol_id": item.symbol_id,
                    "x": float(item.x()),
                    "y": float(item.y()),
                    "orientation": item.orientation,
                    "rotation_step": int(getattr(item, "rotation_step", 0)),
                    "scale_factor": float(getattr(item, "scale_factor", 1.0)),
                    "placeholder_values": dict(item.placeholder_values),
                    "placeholder_offsets": {
                        key: [float(off[0]), float(off[1])]
                        for key, off in getattr(item, "placeholder_offsets", {}).items()
                    },
                })
                # Spannungs-Annotationen referenzieren ihren Index im
                # components-Array (gleiche Iteration, stabile Reihenfolge).
                for annotation in getattr(item, "annotations", []):
                    if isinstance(annotation, VoltageAnnotation):
                        annotations_data.append(
                            dict(annotation.to_dict(), component=len(components_data) - 1)
                        )
            elif isinstance(item, Wire):
                wires_data.append({
                    "type": "wire",
                    "start_x": float(item.start_point.x()),
                    "start_y": float(item.start_point.y()),
                    "end_x": float(item.end_point.x()),
                    "end_y": float(item.end_point.y()),
                    "color": list(item.color_rgb()),
                })
                # Strom-Annotationen referenzieren ihren Index im wires-Array.
                for annotation in getattr(item, "annotations", []):
                    if isinstance(annotation, CurrentAnnotation):
                        annotations_data.append(
                            dict(annotation.to_dict(), wire=len(wires_data) - 1)
                        )
            elif isinstance(item, ContactMirrorItem):
                # Kontakt-Spiegel: eigenständiges Element, ein Relais pro Spiegel.
                # Das Basisprogramm überspringt diesen Annotation-Typ beim Laden.
                annotations_data.append({
                    "type": "contact_mirror",
                    "x": float(item.pos().x()),
                    "y": float(item.pos().y()),
                    "value": item.relay_name,
                })
        return {"version": "1.0", "components": components_data,
                "wires": wires_data, "annotations": annotations_data,
                "sheet": dict(self.sheet_meta)}

    def _restore_snapshot(self, data):
        """Szene aus einem Snapshot wiederherstellen (ohne Undo zu triggern)."""
        # Preview entfernen, da sie sonst beim clear() mit gelöscht und
        # inkonsistent würde.
        self._clear_preview()
        if self.sim_engine is not None:
            self.stop_simulation()
        self.canvas.scene.clear()

        # Erzeugte Elemente nach Snapshot-Index merken, damit Annotationen
        # ihr Ziel (Bauteil/Leitung) wiederfinden — auch wenn einzelne
        # Einträge ungültig sind und übersprungen wurden.
        created_components = [None] * len(data.get("components", []))
        for index, comp_data in enumerate(data.get("components", [])):
            if comp_data.get("type") != "symbol":
                continue
            definition = self.symbol_definitions.get(comp_data.get("symbol_id"))
            if not definition:
                continue
            orientation = comp_data.get("orientation", "horizontal")
            # rotation_step: neuere Dateien enthalten ihn direkt; ältere nur
            # 'orientation'. Dort wird der Schritt aus der Orientierung
            # abgeleitet (horizontal -> 0, vertical -> 1).
            if "rotation_step" in comp_data:
                rotation_step = comp_data.get("rotation_step", 0)
            else:
                rotation_step = 1 if orientation == "vertical" else 0
            component = SymbolComponent(
                definition,
                orientation=orientation,
                x=comp_data.get("x", 0),
                y=comp_data.get("y", 0),
                rotation_step=rotation_step,
            )
            scale_factor = comp_data.get("scale_factor", 1.0)
            if scale_factor and scale_factor != 1.0:
                component.scale_factor = 1.0
                component.scale_component(scale_factor)
            for key, value in comp_data.get("placeholder_values", {}).items():
                component.set_placeholder_value(key, value)
            # Schienen: gespeicherte Länge wieder anwenden
            if (component.symbol_id in RAIL_SYMBOLS
                    and "length" in (comp_data.get("placeholder_values") or {})):
                try:
                    component.apply_rail_length(
                        float(comp_data["placeholder_values"]["length"]), snap=False)
                except (TypeError, ValueError):
                    pass
            # Individuelle Versätze der Platzhaltertexte wiederherstellen
            offsets = comp_data.get("placeholder_offsets") or {}
            if offsets:
                component.placeholder_offsets = {
                    key: [float(off[0]), float(off[1])]
                    for key, off in offsets.items()
                }
                component.update_text()
            self.canvas.scene.addItem(component)
            created_components[index] = component

        created_wires = [None] * len(data.get("wires", []))
        for index, wire_data in enumerate(data.get("wires", [])):
            if wire_data.get("type") != "wire":
                continue
            start = QPointF(wire_data.get("start_x", 0), wire_data.get("start_y", 0))
            end = QPointF(wire_data.get("end_x", 0), wire_data.get("end_y", 0))
            color = wire_data.get("color")
            wire = Wire(start, end, grid_size=self.canvas.grid_size, color=color)
            self.canvas.scene.addItem(wire)
            created_wires[index] = wire

        # Messwert-Annotationen wiederherstellen (Ziel über Index)
        for ann in data.get("annotations", []):
            ann_type = ann.get("type")
            if ann_type == "voltage":
                index = ann.get("component", -1)
                target = created_components[index] if 0 <= index < len(created_components) else None
                if target is None:
                    continue
                annotation = VoltageAnnotation(
                    target, ann.get("value", "U"), flipped=ann.get("flip", False))
                annotation.setPos(ann.get("x", 0), ann.get("y", 0))
                target.annotations.append(annotation)
            elif ann_type == "current":
                index = ann.get("wire", -1)
                target = created_wires[index] if 0 <= index < len(created_wires) else None
                if target is None:
                    continue
                annotation = CurrentAnnotation(
                    target, ann.get("value", "I"), ann.get("angle", 0))
                # Gespeichert sind Szenen-Koordinaten (Leitungslage ist nicht
                # Teil des Snapshots) → zurück in Eltern-Koordinaten wandeln.
                annotation.setPos(target.mapFromScene(
                    QPointF(ann.get("x", 0), ann.get("y", 0))))
                target.annotations.append(annotation)
            elif ann_type == "contact_mirror":
                mirror = ContactMirrorItem(
                    ann.get("value", "K1"),
                    engine_provider=lambda: self.sim_engine,
                    grid_size=self.canvas.grid_size)
                mirror.setPos(ann.get("x", 0), ann.get("y", 0))
                self.canvas.scene.addItem(mirror)

        # A4-Blatt/Schriftfeld wiederherstellen
        sheet = data.get("sheet") or {}
        if isinstance(sheet, dict):
            self.sheet_meta.update(sheet)
            self.sheet_meta["visible"] = bool(sheet.get("visible", False))
        self._ensure_decorations()
        self.sheet_toggle_action.setChecked(self.sheet_meta.get("visible", False))
        self.sheet_frame.setVisible(self.sheet_meta.get("visible", False))
        self.refresh_mirrors()

    def _push_undo_snapshot(self):
        """Aktuellen Zustand auf den Undo-Stack legen (Redo wird geleert)."""
        snapshot = self._capture_snapshot()
        self.undo_stack.append(snapshot)
        if len(self.undo_stack) > self.MAX_UNDO_STACK:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self._mark_dirty()

    # ------------------------------------------------------------------
    # Kopieren / Einfügen / Duplizieren
    # ------------------------------------------------------------------
    def copy_selection(self):
        """Ausgewählte Bauteile und Leitungen in die interne Zwischenablage.

        Leitungen, deren beide Enden an Polen ausgewählter Bauteile andocken,
        werden automatisch mitkopiert (Teilschaltungen bleiben verbunden).
        Koordinaten werden auf die Auswahl-Normiert (min = 0/0).
        """
        selected = self.canvas.scene.selectedItems()
        components = [i for i in selected if isinstance(i, SymbolComponent)]
        wires = [i for i in selected if isinstance(i, Wire)]
        if not components and not wires:
            self.statusBar().showMessage("Nichts zum Kopieren ausgewählt.")
            return
        # Verbund-Leitungen ausgewählter Bauteile mitnehmen
        pole_keys = set()
        for comp in components:
            for pole in comp.get_pole_points():
                pole_keys.add((round(pole.x()), round(pole.y())))
        for wire in list(self.canvas.scene.items()):
            if (not isinstance(wire, Wire) or wire in wires
                    or wire is self.temp_wire):
                continue
            s = (round(wire.start_point.x()), round(wire.start_point.y()))
            e = (round(wire.end_point.x()), round(wire.end_point.y()))
            if s in pole_keys and e in pole_keys:
                wires.append(wire)

        # Koordinaten bleiben ABSOLUT (Originalposition) — Einfügen landet
        # versetzt nahe beim Original statt weit weg beim Ursprung.
        comp_index = {id(c): i for i, c in enumerate(components)}
        wire_index = {id(w): i for i, w in enumerate(wires)}
        comp_data = []
        for comp in components:
            entry = {
                "symbol_id": comp.symbol_id,
                "dx": comp.x(), "dy": comp.y(),
                "rotation_step": int(getattr(comp, "rotation_step", 0)),
                "orientation": comp.orientation,
                "scale_factor": float(getattr(comp, "scale_factor", 1.0)),
                "placeholder_values": dict(comp.placeholder_values),
                "placeholder_offsets": {
                    k: [float(o[0]), float(o[1])]
                    for k, o in getattr(comp, "placeholder_offsets", {}).items()},
            }
            comp_data.append(entry)
        wire_data = [{
            "start": [w.start_point.x(), w.start_point.y()],
            "end": [w.end_point.x(), w.end_point.y()],
            "color": list(w.color_rgb()),
        } for w in wires]
        annotations = []
        for comp in components:
            for ann in getattr(comp, "annotations", []):
                if getattr(ann, "ANNOTATION_TYPE", None) == "voltage":
                    annotations.append({**ann.to_dict(),
                                        "component": comp_index[id(comp)]})
        for wire in wires:
            for ann in getattr(wire, "annotations", []):
                if getattr(ann, "ANNOTATION_TYPE", None) == "current":
                    d = ann.to_dict()
                    annotations.append({"type": "current",
                                        "wire": wire_index[id(wire)],
                                        "x": d["x"], "y": d["y"],
                                        "angle": d.get("angle", 0), "value": d.get("value", "")})
        self._clipboard = {"components": comp_data, "wires": wire_data,
                           "annotations": annotations}
        self.statusBar().showMessage(
            f"{len(comp_data)} Bauteil(e) und {len(wire_data)} Leitung(en) kopiert.")

    def paste_clipboard(self, offset=None):
        """Zwischenablage versetzt (Standard +2 Raster diagonal) einfügen."""
        if not self._clipboard:
            self.statusBar().showMessage("Zwischenablage ist leer.")
            return
        grid = self.canvas.grid_size
        dx, dy = offset if offset else (grid * 2, grid * 2)
        new_components = []
        for entry in self._clipboard["components"]:
            definition = self.symbol_definitions.get(entry.get("symbol_id"))
            if not definition:
                continue
            comp = SymbolComponent(
                definition,
                orientation=entry.get("orientation", "horizontal"),
                x=entry["dx"] + dx, y=entry["dy"] + dy,
                rotation_step=entry.get("rotation_step", 0))
            scale = entry.get("scale_factor", 1.0)
            if scale and scale != 1.0:
                comp.scale_factor = 1.0
                comp.scale_component(scale)
            for key, value in entry.get("placeholder_values", {}).items():
                comp.set_placeholder_value(key, value)
            if (comp.symbol_id in RAIL_SYMBOLS
                    and "length" in entry.get("placeholder_values", {})):
                try:
                    comp.apply_rail_length(
                        float(entry["placeholder_values"]["length"]), snap=False)
                except (TypeError, ValueError):
                    pass
            comp.placeholder_offsets = {
                k: [float(o[0]), float(o[1])]
                for k, o in entry.get("placeholder_offsets", {}).items()}
            self.canvas.scene.addItem(comp)
            comp.update_text()
            new_components.append(comp)
        new_wires = []
        for entry in self._clipboard["wires"]:
            wire = Wire(QPointF(entry["start"][0] + dx, entry["start"][1] + dy),
                        QPointF(entry["end"][0] + dx, entry["end"][1] + dy),
                        grid_size=grid, color=entry.get("color"))
            self.canvas.scene.addItem(wire)
            new_wires.append(wire)
        for ann in self._clipboard.get("annotations", []):
            if ann.get("type") == "voltage":
                target = (new_components[ann["component"]]
                          if 0 <= ann.get("component", -1) < len(new_components) else None)
                if target is None:
                    continue
                annotation = VoltageAnnotation(target, ann.get("value", "U"),
                                               flipped=ann.get("flip", False))
                annotation.setPos(ann.get("x", 0), ann.get("y", 0))
                target.annotations.append(annotation)
            elif ann.get("type") == "current":
                target = (new_wires[ann["wire"]]
                          if 0 <= ann.get("wire", -1) < len(new_wires) else None)
                if target is None:
                    continue
                annotation = CurrentAnnotation(target, ann.get("value", "I"),
                                               ann.get("angle", 0))
                annotation.setPos(target.mapFromScene(
                    QPointF(ann.get("x", 0) + dx, ann.get("y", 0) + dy)))
                target.annotations.append(annotation)
        self.canvas.scene.clearSelection()
        for item in new_components + new_wires:
            item.setSelected(True)
        self._push_undo_snapshot()
        self.statusBar().showMessage(
            f"{len(new_components)} Bauteil(e) und {len(new_wires)} Leitung(en) eingefügt.")

    def duplicate_selection(self):
        self.copy_selection()
        if self._clipboard:
            self.paste_clipboard()

    # ------------------------------------------------------------------
    # Pfeiltasten-Feinverschiebung
    # ------------------------------------------------------------------
    def keyPressEvent(self, event):
        # Pfeiltaste = Feinverschiebung (1 px, ohne Raster-Snap);
        # Shift+Pfeiltaste = Rasterschritt.
        fine = not (event.modifiers() & Qt.ShiftModifier)
        step = 1 if fine else self.canvas.grid_size
        moves = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0),
                 Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}
        if event.key() in moves:
            selected = self.canvas.scene.selectedItems()
            if selected:
                dx, dy = moves[event.key()]
                targets = [i for i in selected if isinstance(i, (SymbolComponent, Wire))]
                for item in targets:
                    if fine:
                        # Raster-Snap der Items für die Feinverschiebung
                        # kurzzeitig aus (setPos würde sonst zurückrastern).
                        item._snap_enabled = False
                try:
                    for item in targets:
                        item.setPos(item.pos() + QPointF(dx, dy))
                finally:
                    for item in targets:
                        item._snap_enabled = True
                self._push_undo_snapshot()
                event.accept()
                return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Drucken (A4 einpassen; Blattrahmen/Schriftfeld wird mitgedruckt)
    # ------------------------------------------------------------------
    def print_file(self):
        from PyQt5.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter(QPrinter.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec_() != QPrintDialog.Accepted:
            return
        self._render_to_printer(printer)

    def _content_bounds(self):
        rect = QRectF()
        for item in self.canvas.scene.items():
            if getattr(item, "is_decoration", False) or getattr(item, "is_handle", False):
                if item is not self.sheet_frame:
                    continue
            if isinstance(item, (SymbolComponent, Wire)) or item is self.sheet_frame:
                mapped = item.mapRectToScene(item.boundingRect())
                rect = mapped if rect.isNull() else rect.united(mapped)
        return rect

    def _render_to_printer(self, printer):
        from PyQt5.QtPrintSupport import QPrinter
        painter = QPainter(printer)
        try:
            page_rect = printer.pageRect(QPrinter.DevicePixel)
            content = self._content_bounds()
            if content.isNull() or content.isEmpty():
                return
            margin = 40
            avail = QRectF(page_rect.x() + margin, page_rect.y() + margin,
                           page_rect.width() - 2 * margin,
                           page_rect.height() - 2 * margin)
            scale = min(avail.width() / content.width(),
                        avail.height() / content.height(), 2.0)
            target = QRectF(
                avail.x() + (avail.width() - content.width() * scale) / 2,
                avail.y() + (avail.height() - content.height() * scale) / 2,
                content.width() * scale, content.height() * scale)
            # Dekorationen (Knotenpunkte) mitdrucken; temp-Wire nicht
            if self.temp_wire is not None:
                self.temp_wire.setVisible(False)
            try:
                self.canvas.scene.render(painter, target, content)
            finally:
                if self.temp_wire is not None:
                    self.temp_wire.setVisible(True)
        finally:
            painter.end()

    # ------------------------------------------------------------------
    # A4-Blatt / Schriftfeld
    # ------------------------------------------------------------------
    def _set_sheet_visible(self, visible):
        self.sheet_meta["visible"] = bool(visible)
        self.sheet_frame.setVisible(bool(visible))
        self._mark_dirty()

    def edit_sheet_meta(self):
        from PyQt5.QtWidgets import QDialog, QFormLayout, QLineEdit, QDialogButtonBox
        dialog = QDialog(self)
        dialog.setWindowTitle("Schriftfeld")
        form = QFormLayout(dialog)
        fields = {}
        for label, key in (("Titel", "title"), ("Fach / Thema", "subject"),
                           ("Name / Klasse", "name"), ("Datum", "date")):
            edit = QLineEdit(str(self.sheet_meta.get(key, "") or ""))
            form.addRow(label, edit)
            fields[key] = edit
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec_() == QDialog.Accepted:
            self._mark_dirty()
            for key, edit in fields.items():
                self.sheet_meta[key] = edit.text().strip()

    # ------------------------------------------------------------------
    # Datei-Komfort: Änderungsmarker, Zuletzt geöffnet, Autosave
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Funktionsschema-Simulation
    # ------------------------------------------------------------------
    def start_simulation(self):
        """Simulation starten: Logik lösen, Takt laufen lassen."""
        from ..simulation.solver import SimEngine
        self._cancel_pending_wire()
        self.sim_engine = SimEngine(self.canvas.scene)
        self.sim_engine.evaluate()
        self._refresh_meter_readings()
        self.sim_overlay.setVisible(True)
        self._sim_clock.start(100)  # 10 Takte/s: Zeitrelais + Reaktion
        self.sim_start_btn.setEnabled(False)
        self.sim_stop_btn.setEnabled(True)
        self.sim_reset_btn.setEnabled(True)
        self.statusBar().showMessage(
            "Simulation läuft – Schalter/Taster anklicken, ESC beendet.")
        # Kontaktspiegel anbieten: platzierte Spiegel-Elemente zeigen den
        # Zustand bereits live — der Übersichts-Dialog öffnet nur, wenn
        # noch keiner platziert ist. WA_DeleteOnClose lässt die Referenz
        # verwaisen: RuntimeError = nicht mehr da.
        try:
            mirror_open = self._mirror_dialog is not None and self._mirror_dialog.isVisible()
        except (RuntimeError, AttributeError):
            mirror_open = False
        has_mirror_items = any(isinstance(i, ContactMirrorItem)
                               for i in self.canvas.scene.items())
        if not mirror_open and not has_mirror_items:
            if any(getattr(c, "symbol_id", "") in COIL_SYMBOL_IDS
                   for c in self.canvas.scene.items()):
                self.show_contact_mirror()

    def stop_simulation(self):
        """Simulation beenden; Zeichnung bleibt unverändert."""
        self._sim_clock.stop()
        self.sim_engine = None
        self.sim_readings = {}
        self._mirror_dialog = None
        if self.sim_overlay is not None:
            self.sim_overlay.setVisible(False)
        self.sim_start_btn.setEnabled(True)
        self.sim_stop_btn.setEnabled(False)
        self.sim_reset_btn.setEnabled(False)
        self.statusBar().showMessage("Simulation beendet.")
        self.canvas.viewport().update()

    def reset_simulation(self):
        """Alle Schalter-/Relaisstellungen auf Anfang."""
        if self.sim_engine is not None:
            self.sim_engine.reset()
            self._refresh_meter_readings()
            self.statusBar().showMessage("Simulation zurückgesetzt.")

    def _sim_tick(self):
        """Takt: Zeitrelais fortschalten, Messwerte neu lösen, neu zeichnen."""
        if self.sim_engine is None:
            self._sim_clock.stop()
            return
        self.sim_engine.tick(0.1)
        self._refresh_meter_readings()
        if self.sim_engine.message:
            self.statusBar().showMessage(self.sim_engine.message)
        self.refresh_mirrors()
        self.canvas.viewport().update()

    def _refresh_meter_readings(self):
        """Volt-/Amperemeter: reale Werte, wenn das Netz numerisch lösbar ist."""
        from ..simulation.dc import meter_readings
        try:
            _result, self.sim_readings = meter_readings(self.canvas.scene)
        except Exception:
            self.sim_readings = {}

    def _sim_press(self, event):
        """Klick in der Simulation: Schalter/Taster bedienen.

        Die Auswertung (Netzliste mit mapToScene!) wird per singleShot NACH
        dem C++-Dispatch ausgeführt — mapToScene im Press-Dispatch führt zum
        nativen Absturz (gleiche Falle wie bei den Annotationen).
        """
        from PyQt5.QtCore import QTimer
        pos = event.scenePos()
        from ..simulation.solver import MANUAL_SWITCHES
        for item in self.canvas.scene.items(pos):
            sid = getattr(item, "symbol_id", "")
            if sid in MANUAL_SWITCHES:
                if self.sim_engine.press_manual(item, pressed=True):
                    pass  # Taster: Drücken
                else:
                    self.sim_engine.toggle_manual(item)  # Schalter: umschalten
                QTimer.singleShot(0, self._sim_apply)
                event.accept()
                return
        event.accept()  # sonstige Klicks blockieren das Editieren

    def _sim_apply(self):
        """Auswertung + Neuzeichnen (außerhalb des Maus-Dispatchs)."""
        if self.sim_engine is None:
            return
        try:
            self.sim_engine.evaluate()
            self._refresh_meter_readings()
        except RuntimeError:
            self.stop_simulation()
            return
        self.refresh_mirrors()
        self.canvas.viewport().update()

    def _sim_release(self, event):
        """Loslassen: momentane Taster öffnen wieder (Auswertung verzögert)."""
        from PyQt5.QtCore import QTimer
        from ..simulation.solver import MANUAL_SWITCHES
        for item in self.canvas.scene.items():
            sid = getattr(item, "symbol_id", "")
            if sid in MANUAL_SWITCHES and MANUAL_SWITCHES[sid][1]:
                self.sim_engine.press_manual(item, pressed=False)
        QTimer.singleShot(0, self._sim_apply)
        event.accept()

    def show_contact_mirror(self):
        """Kontaktspiegel: Zuordnung Relais -> Kontakte (Name, Art, Ort)."""
        from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QTableWidget,
                                     QTableWidgetItem, QDialogButtonBox, QLabel)
        from ..simulation.solver import CONTACTS, COIL_SYMBOLS
        coils = [c for c in self.canvas.scene.items()
                 if getattr(c, "symbol_id", "") in COIL_SYMBOLS]
        contacts = [c for c in self.canvas.scene.items()
                    if getattr(c, "symbol_id", "") in CONTACTS]
        dialog = QDialog(self)
        dialog.setWindowTitle("Kontaktspiegel")
        dialog.resize(640, 400)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        layout = QVBoxLayout(dialog)
        if not coils:
            layout.addWidget(QLabel("Keine Relaisspulen in der Zeichnung. "
                                    "Kontakte werden über den Namen (z. B. K1) "
                                    "ihrer Spule zugeordnet."))
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(
            ["Relais", "Art", "Verzögerung", "Kontakt", "Position (Spalte/Zeile)"])
        for coil in sorted(coils, key=lambda c: str(c.placeholder_values.get("name", ""))):
            name = str(coil.placeholder_values.get("name", "") or "?")
            delay = (str(coil.placeholder_values.get("delay", "2 s"))
                     if coil.symbol_id == "timer_coil" else "–")
            art = "Zeitrelais" if coil.symbol_id == "timer_coil" else "Sofortrelais"
            own = [c for c in contacts
                   if str(c.placeholder_values.get("name", "")).strip() == name.strip()]
            if not own:
                row = table.rowCount()
                table.insertRow(row)
                table.setItem(row, 0, QTableWidgetItem(name))
                table.setItem(row, 1, QTableWidgetItem(art))
                table.setItem(row, 2, QTableWidgetItem(delay))
                table.setItem(row, 3, QTableWidgetItem("(keine Kontakte)"))
                table.setItem(row, 4, QTableWidgetItem(""))
            for contact in own:
                is_no, timing = CONTACTS[contact.symbol_id]
                kind = ("Schliesser" if is_no else "Öffner")
                if timing == "pickup":
                    kind += " (anzugsverzögert)"
                elif timing == "dropout":
                    kind += " (abfallverzögert)"
                row = table.rowCount()
                table.insertRow(row)
                table.setItem(row, 0, QTableWidgetItem(name))
                table.setItem(row, 1, QTableWidgetItem(art))
                table.setItem(row, 2, QTableWidgetItem(delay))
                table.setItem(row, 3, QTableWidgetItem(kind))
                table.setItem(row, 4, QTableWidgetItem(
                    f"{int(contact.x() / self.canvas.grid_size)}/"
                    f"{int(contact.y() / self.canvas.grid_size)}"))
        table.resizeColumnsToContents()
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.clicked.connect(dialog.close)
        layout.addWidget(buttons)
        # Bereits offener Spiegel erneut öffnen? Dann nur nach vorn holen.
        try:
            if self._mirror_dialog is not None and self._mirror_dialog.isVisible():
                self._mirror_dialog.raise_()
                self._mirror_dialog.activateWindow()
                dialog.deleteLater()
                return
        except (RuntimeError, AttributeError):
            pass
        def _forget(*_args, handle=dialog):
            if getattr(self, "_mirror_dialog", None) is handle:
                self._mirror_dialog = None
        dialog.destroyed.connect(_forget)
        # Nicht-modal: bleibt offen, während die Simulation läuft
        dialog.show()
        self._mirror_dialog = dialog

    def _assign_default_fs_name(self, component):
        """Funktionsschema: Spulen automatisch benennen (K1, K2 …/KT1 …),
        Kontakte standardmäßig dem ersten vorhandenen Relais zuweisen."""
        sid = getattr(component, "symbol_id", "")
        if sid not in COIL_SYMBOL_IDS and sid not in RELAY_CONTACT_SYMBOLS:
            return
        existing = set()
        plain_coils = []      # Sofortrelais (bevorzugt für Kontakte)
        any_coils = []
        for item in self.canvas.scene.items():
            item_sid = getattr(item, "symbol_id", "")
            if item_sid in COIL_SYMBOL_IDS and item is not component:
                name = str(item.placeholder_values.get("name", "")).strip()
                if name:
                    existing.add(name)
                    any_coils.append(name)
                    if item_sid == "relay_coil":
                        plain_coils.append(name)
        # niedrigste Nummer zuerst (K1 vor K2/K10 — Länge, dann Text)
        plain_coils.sort(key=lambda n: (len(n), n))
        any_coils.sort(key=lambda n: (len(n), n))
        first_plain = plain_coils[0] if plain_coils else None
        first_any = any_coils[0] if any_coils else None
        if sid in COIL_SYMBOL_IDS:
            prefix = "KT" if sid == "timer_coil" else "K"
            number = 1
            while f"{prefix}{number}" in existing:
                number += 1
            component.set_placeholder_value("name", f"{prefix}{number}")
        else:
            default = first_plain or first_any
            if default:
                component.set_placeholder_value("name", default)

    def _start_wire_at_nearest_pole(self, component, reference_pos):
        """Leitung nach Auswahl: Platzierungs-Werkzeug auf Leitung umschalten
        und eine neue Leitung am nächsten Pol des Bauteils beginnen."""
        poles = component.get_pole_points()
        if not poles:
            return
        nearest = min(poles, key=lambda p: (p.x() - reference_pos.x()) ** 2
                      + (p.y() - reference_pos.y()) ** 2)
        self.on_component_selected("wire")
        self.drawing_wire = True
        self.wire_start_point = QPointF(nearest)
        self.temp_wire = Wire(QPointF(nearest), QPointF(nearest),
                              grid_size=self.canvas.grid_size,
                              color=self.current_wire_color)
        self.canvas.scene.addItem(self.temp_wire)
        self.statusBar().showMessage(
            "Leitung läuft am Pol mit - weiterklicken zum Setzen (ESC beendet).")

    def _set_auto_wire(self, enabled):
        self.auto_wire_after_place = bool(enabled)

    def _ensure_decorations(self):
        """Knotenpunkte + Blattrahmen in der Szene halten.

        scene.clear() (Undo-Restore, Alles löschen) entfernt ALLE Items,
        inklusive Dekorationen — sie werden hier neu erzeugt.
        """
        from ..canvas.junction_layer import JunctionDotsItem
        from ..canvas.sheet_frame import SheetFrameItem
        from ..simulation.overlay import SimulationOverlayItem
        try:
            junction_alive = self.junction_layer is not None and self.junction_layer.scene() is not None
        except RuntimeError:
            junction_alive = False
        if not junction_alive:
            self.junction_layer = JunctionDotsItem(owner=self)
            self.canvas.scene.addItem(self.junction_layer)
        try:
            frame_alive = self.sheet_frame is not None and self.sheet_frame.scene() is not None
        except RuntimeError:
            frame_alive = False
        if not frame_alive:
            self.sheet_frame = SheetFrameItem(lambda: self.sheet_meta)
            self.sheet_frame.setVisible(self.sheet_meta.get("visible", False))
            self.canvas.scene.addItem(self.sheet_frame)
        try:
            sim_alive = (self.sim_overlay is not None
                         and self.sim_overlay.scene() is not None)
        except RuntimeError:
            sim_alive = False
        if not sim_alive:
            self.sim_overlay = SimulationOverlayItem(
                lambda: self.sim_engine, lambda: self.sim_readings)
            self.sim_overlay.setVisible(self.sim_engine is not None)
            self.canvas.scene.addItem(self.sim_overlay)

    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            self._update_window_title()

    def _clear_dirty(self):
        if self._dirty:
            self._dirty = False
            self._update_window_title()

    def _update_window_title(self):
        name = self.current_file.name if self.current_file else "Unbenannt"
        star = "*" if self._dirty else ""
        self.setWindowTitle(f"SchaltungsZeichner Funktionsschema - {name}{star}")

    def _autosave_path(self):
        from PyQt5.QtCore import QStandardPaths
        base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        return Path(base) / "autosave.sz.json"

    def _autosave(self):
        if not self._dirty:
            return
        try:
            path = self._autosave_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            snapshot = self._capture_snapshot()
            snapshot["autosave_of"] = str(self.current_file) if self.current_file else ""
            path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        except OSError:
            pass  # Sicherung ist Best-Effort

    def restore_autosave(self):
        path = self._autosave_path()
        if not path.exists():
            self.statusBar().showMessage("Keine Absturzsicherung vorhanden.")
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.statusBar().showMessage("Absturzsicherung ist beschädigt.")
            return
        self._push_undo_snapshot()
        self._restore_snapshot(data)
        self._mark_dirty()
        self.statusBar().showMessage("Absturzsicherung wiederhergestellt.")

    def closeEvent(self, event):
        if self._dirty:
            from PyQt5.QtWidgets import QMessageBox
            answer = QMessageBox.question(
                self, "Ungespeicherte Änderungen",
                "Die Zeichnung enthält ungespeicherte Änderungen. "
                "Trotzdem beenden?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Save,
                QMessageBox.No)
            if answer == QMessageBox.Save:
                self.save_file()
                event.accept() if not self._dirty else event.ignore()
                return
            if answer == QMessageBox.No:
                event.ignore()
                return
        super().closeEvent(event)

    def _update_recent_menu(self):
        from PyQt5.QtCore import QSettings
        settings = QSettings()
        files = settings.value("recentFiles", []) or []
        self.recent_menu.clear()
        if not files:
            self.recent_menu.setEnabled(False)
            return
        self.recent_menu.setEnabled(True)
        for path in files[:8]:
            action = self.recent_menu.addAction(str(path))
            action.triggered.connect(
                lambda checked=False, p=str(path): self._open_path(p))

    def _remember_recent_file(self, path):
        from PyQt5.QtCore import QSettings
        settings = QSettings()
        files = [str(f) for f in (settings.value("recentFiles", []) or [])]
        entry = str(path)
        if entry in files:
            files.remove(entry)
        files.insert(0, entry)
        settings.setValue("recentFiles", files[:8])
        self._update_recent_menu()

    def _open_path(self, path):
        self.load_circuit(path)

    def undo(self):
        """Letzte Aktion rückgängig machen.

        Der undo_stack speichert nach jeder Änderung den neuen Zustand. Das
        oberste Element ist also der aktuelle Zustand; es wandert auf den
        redo_stack. Das dann oberste Element ist der Zielzustand.
        """
        if len(self.undo_stack) < 1:
            self.statusBar().showMessage("Nichts zum Rückgängigmachen.")
            return
        # Aktuellen Zustand für späteres Redo sichern.
        self.redo_stack.append(self._capture_snapshot())
        # Aktuellen (obersten) Eintrag verwerfen – er entspricht dem Ist-Zustand.
        self.undo_stack.pop()
        if self.undo_stack:
            target = self.undo_stack[-1]
            self._restore_snapshot(target)
            self.statusBar().showMessage("Rückgängig.")
        else:
            # Stack ist leer -> leerer Anfangszustand.
            self._restore_snapshot({"version": "1.0", "components": [], "wires": []})
            self.statusBar().showMessage("Rückgängig (Anfangszustand).")

    def redo(self):
        """Zuletzt rückgängig gemachte Aktion wiederherstellen."""
        if not self.redo_stack:
            self.statusBar().showMessage("Nichts zum Wiederherstellen.")
            return
        # Den aktuellen (rückgängig gemachten) Zustand auf den undo_stack legen,
        # damit ein erneutes Undo wieder hierher führt.
        self.undo_stack.append(self._capture_snapshot())
        following = self.redo_stack.pop()
        self._restore_snapshot(following)
        self.statusBar().showMessage("Wiederhergestellt.")

    def rotate_selected(self):
        """Ausgewählte Bauteile drehen"""
        selected_items = self.canvas.scene.selectedItems()
        rotated = False
        for item in selected_items:
            if hasattr(item, 'rotate_component'):
                item.rotate_component()
                rotated = True
        if rotated:
            self._push_undo_snapshot()

    def scale_selected(self, factor):
        """Ausgewählte Bauteile skalieren"""
        selected_items = self.canvas.scene.selectedItems()
        scaled = False
        for item in selected_items:
            if hasattr(item, 'scale_component'):
                item.scale_component(factor)
                scaled = True
        if scaled:
            self._push_undo_snapshot()

    def delete_selected(self):
        """Ausgewählte Elemente löschen"""
        selected_items = self.canvas.scene.selectedItems()
        if not selected_items:
            return
        if self.sim_engine is not None:
            self.stop_simulation()
        self._push_undo_snapshot()
        for item in selected_items:
            # Annotationen hängen als Kinder am Ziel und zusätzlich in dessen
            # Registry — ohne Austrag würde eine gelöschte Annotation weiter
            # serialisiert (Geist in Snapshots).
            if getattr(item, "is_annotation", False):
                parent = item.parentItem()
                registry = getattr(parent, "annotations", None)
                if registry is not None and item in registry:
                    registry.remove(item)
            self.canvas.scene.removeItem(item)

    def toggle_grid(self, state):
        """Raster ein-/ausblenden"""
        show_grid = (state == Qt.Checked)
        self.canvas.set_grid_visible(show_grid)

    @staticmethod
    def _coerce_rgb(value):
        """Return (r, g, b) tuple for different color representations."""
        if isinstance(value, QColor):
            return (value.red(), value.green(), value.blue())
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return (int(value[0]), int(value[1]), int(value[2]))
        return (0, 0, 0)

    def _index_for_wire_color(self, rgb):
        """Find combo index for a given RGB tuple."""
        if not self.wire_color_combo:
            return -1
        target = self._coerce_rgb(rgb)
        for idx in range(self.wire_color_combo.count()):
            data = self.wire_color_combo.itemData(idx)
            if data is None:
                continue
            if self._coerce_rgb(data) == target:
                return idx
        return -1

    def on_wire_color_changed(self, index):
        """Update default wire color and recolor selected wires if requested."""
        if self.wire_color_combo is None or index < 0:
            return
        data = self.wire_color_combo.itemData(index)
        if data is None:
            return
        rgb = self._coerce_rgb(data)
        self.current_wire_color = rgb
        if self._updating_wire_color_ui:
            return
        if self.drawing_wire and self.temp_wire:
            self.temp_wire.set_color(rgb)
        updated = False
        for item in self.canvas.scene.selectedItems():
            if isinstance(item, Wire):
                item.set_color(rgb)
                updated = True
        if updated:
            self.statusBar().showMessage("Leitungsfarbe aktualisiert.")

    def on_scene_selection_changed(self):
        """Defer sync to avoid interfering with drag operations."""
        if self._pending_selection_sync:
            return
        self._pending_selection_sync = True
        QTimer.singleShot(0, self._sync_wire_color_from_selection)

    def _sync_wire_color_from_selection(self):
        """Sync color selector with selected wires when colors match."""
        self._pending_selection_sync = False
        if not self.wire_color_combo:
            return
        if QApplication.mouseButtons() != Qt.NoButton:
            # Mouse is currently pressed; postpone until released.
            self._pending_selection_sync = True
            QTimer.singleShot(50, self._sync_wire_color_from_selection)
            return
        selected = [item for item in self.canvas.scene.selectedItems() if isinstance(item, Wire)]
        if not selected:
            return
        first_rgb = selected[0].color_rgb()
        if any(item.color_rgb() != first_rgb for item in selected[1:]):
            return
        index = self._index_for_wire_color(first_rgb)
        if index == -1:
            self.current_wire_color = tuple(first_rgb)
            return
        try:
            self._updating_wire_color_ui = True
            self.wire_color_combo.blockSignals(True)
            self.wire_color_combo.setCurrentIndex(index)
        finally:
            self.wire_color_combo.blockSignals(False)
            self._updating_wire_color_ui = False
        self.current_wire_color = tuple(first_rgb)
        color_name = next(
            (label for label, rgb in WIRE_COLOR_PRESETS if self._coerce_rgb(rgb) == self.current_wire_color),
            f"RGB {self.current_wire_color}",
        )
        self.statusBar().showMessage(f"Linienfarbe: {color_name}")

    def clear_canvas(self):
        """Alle Elemente von Zeichenfläche löschen"""
        reply = QMessageBox.question(self, "Zeichenfläche leeren",
                                     "Möchten Sie wirklich die Zeichenfläche leeren?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            if self.sim_engine is not None:
                self.stop_simulation()
            self._push_undo_snapshot()
            self.canvas.scene.clear()
            self._ensure_decorations()

    def new_file(self):
        """Neue Datei erstellen"""
        self.clear_canvas()
        self.current_file = None
        self._clear_dirty()
        self._update_window_title()

    def open_file(self):
        """Gespeicherte Schaltung öffnen"""
        filename, _ = QFileDialog.getOpenFileName(
            self, "Schaltung öffnen", "",
            "Schaltungsdateien (*.sz *.sz.json *.json)")
        if not filename:
            return
        self._open_path(filename)

    def load_circuit(self, filename):
        """Schaltung aus Datei laden (ohne Dialog)."""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._push_undo_snapshot()
            self._restore_snapshot(data)
            self.current_file = Path(filename)
            self._clear_dirty()
            self._update_window_title()
            self._remember_recent_file(filename)
            components_count = len(data.get("components", []))
            wires_count = len(data.get("wires", []))
            QMessageBox.information(
                self, "Erfolg",
                f"Schaltung erfolgreich geladen!\n{components_count} Komponenten, {wires_count} Leitungen"
            )
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Laden der Schaltung fehlgeschlagen: {str(e)}")

    def save_file(self):
        """Aktuelle Schaltung speichern (bei bekannter Datei ohne Dialog)"""
        if self.current_file is not None:
            return self._save_to(self.current_file)
        filename, _ = QFileDialog.getSaveFileName(
            self, "Schaltung speichern", "",
            "Schaltungsdateien (*.sz *.sz.json *.json)")
        if not filename:
            return
        self._save_to(Path(filename))

    def _save_to(self, path):
        # Pfad normalisieren (Dialog-Eingabe): resolve() beseitigt relative
        # Anteile und ../-Segmente — schreiben nur an eindeutig aufgelöste Ziele.
        path = Path(path).resolve()
        try:
            data = self._capture_snapshot()
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding='utf-8')
            self.current_file = Path(path)
            self._clear_dirty()
            self._update_window_title()
            self._remember_recent_file(str(path))
            QMessageBox.information(
                self, "Erfolg",
                f"Schaltung erfolgreich gespeichert!\n"
                f"{len(data['components'])} Komponenten, {len(data['wires'])} Leitungen"
            )
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Speichern der Schaltung fehlgeschlagen: {str(e)}")

    def export_png(self, filename=None, scale=2):
        """Zeichenfläche als PNG exportieren - nur sichtbarer Bereich.

        scale ist der Auflösungsfaktor (1 = Scene-Einheiten 1:1). Ohne
        filename-Parameter (GUI-Aufruf) fragt ein kleiner Dialog den
        Faktor ab; Tests können beides direkt übergeben.
        """
        if filename is None:
            filename, _ = QFileDialog.getSaveFileName(self, "Als PNG exportieren", "", "PNG Dateien (*.png)")
            if not filename:
                return
            scale, ok = QInputDialog.getInt(
                self, "Auflösung",
                "Auflösungsfaktor (1 = Standard, 2 = doppelte Pixelzahl je Achse):",
                2, 1, 8, 1)
            if not ok:
                return
        try:
            # Nur den sichtbaren Bereich exportieren
            visible_rect = self.canvas.get_visible_scene_rect()

            # Zielbild: sichtbarer Bereich mal Auflösungsfaktor
            width = max(1, int(visible_rect.width() * scale))
            height = max(1, int(visible_rect.height() * scale))
            image = QImage(width, height, QImage.Format_ARGB32)
            image.fill(Qt.white)

            # Szene auf Bild rendern - nur sichtbarer Bereich, skaliert
            painter = QPainter(image)
            self.canvas.scene.render(
                painter,
                QRectF(0, 0, width, height),
                visible_rect)
            painter.end()

            # Bild speichern (Rückgabe prüfen: stillscheitender Export wäre
            # sonst ein «Erfolg» mit leerer Datei)
            if not image.save(filename):
                raise IOError("QImage.save() meldete False (Pfad beschreibbar?)")
            if not hasattr(self, "_batch_export"):
                QMessageBox.information(self, "Erfolg",
                    f"Als PNG erfolgreich exportiert!\n"
                    f"Größe: {width}x{height} px")
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Export fehlgeschlagen: {str(e)}")

    def _export_content_rect(self):
        """Rechteck der gezeichneten Elemente für den SVG-Export.

        Deko-Items (Junction-Layer, Raster) melden als boundingRect die
        gesamte Szene — sie würden die viewBox auf das leere 10000x10000-
        Raster aufblähen. Das sichtbare A4-Blatt zählt dagegen zur Zeichnung.
        """
        from ..canvas.sheet_frame import SheetFrameItem
        rect = QRectF()
        for item in self.canvas.scene.items():
            if getattr(item, "is_decoration", False):
                if isinstance(item, SheetFrameItem) and item.isVisible():
                    rect = rect.united(item.mapRectToScene(item.boundingRect()))
                continue
            if getattr(item, "is_handle", False) or getattr(item, "is_anchor", False):
                continue
            try:
                rect = rect.united(item.mapRectToScene(item.boundingRect()))
            except RuntimeError:
                continue
        return rect

    def export_svg(self, filename=None):
        """Zeichenfläche als SVG exportieren (Inhaltsrechteck, nicht Raster).

        Die viewBox umfasst die gezeichneten Elemente plus Rand — früher wurde
        das feste 10000x10000-Szenenrechteck benutzt, wodurch die SVG fast
        leer wirkte. painter.begin() wird geprüft, damit ein fehlendes
        SVG-Modul (z. B. im gebündelten Build) nicht still eine leere Datei
        produziert.
        """
        if filename is None:
            filename, _ = QFileDialog.getSaveFileName(self, "Als SVG exportieren", "", "SVG Dateien (*.svg)")
            if not filename:
                return
        painter = None
        try:
            from PyQt5.QtSvg import QSvgGenerator
        except ImportError as e:
            QMessageBox.critical(
                self, "Fehler",
                "SVG-Modul (PyQt5.QtSvg) ist in dieser Installation nicht "
                f"vorhanden:\n{e}")
            return
        try:
            content_rect = self._export_content_rect().adjusted(-20, -20, 20, 20)
            if content_rect.isEmpty():
                QMessageBox.warning(self, "Nichts zu exportieren",
                                    "Die Zeichenfläche enthält keine Elemente.")
                return

            generator = QSvgGenerator()
            generator.setFileName(filename)
            generator.setSize(content_rect.size().toSize())
            generator.setViewBox(content_rect)

            painter = QPainter()
            if not painter.begin(generator):
                raise IOError("QPainter konnte das SVG-Ziel nicht öffnen")
            self.canvas.scene.render(painter, source=content_rect)
            painter.end()
            painter = None

            QMessageBox.information(self, "Erfolg",
                f"Als SVG erfolgreich exportiert!\n"
                f"Größe: {int(content_rect.width())}x{int(content_rect.height())}")
        except Exception as e:
            if painter is not None:
                try:
                    painter.end()
                except Exception:
                    pass
            QMessageBox.critical(self, "Fehler", f"Export fehlgeschlagen: {str(e)}")

    def show_guide(self):
        """Anleitungs-Dialog anzeigen (F1)"""
        from .guide_dialog import GuideDialog
        GuideDialog(self).exec_()

    def show_about(self):
        """Info-Dialog anzeigen (Logo + Kontakt)"""
        from .about_dialog import AboutDialog
        AboutDialog(self).exec_()
