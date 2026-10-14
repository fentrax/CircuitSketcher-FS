"""
Anleitungs-Dialog – kompakte Bedienungsanleitung mit den wichtigsten Punkten.

Aufgerufbar über Hilfe → Anleitung (Taste F1).
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

GUIDE_HTML = """
<h2>SchaltungsZeichner – Kurz-Anleitung</h2>

<h3>Bauteile platzieren</h3>
<ol>
<li>In der linken Palette ein Bauteil anklicken (z.&nbsp;B. <i>Widerstand</i>).</li>
<li>Eine halbtransparente Vorschau folgt der Maus.
    <b>Rechtsklick auf die Vorschau</b> dreht sie in 90°-Schritten
    (0° → 90° → 180° → 270°).</li>
<li>Linksklick auf die Zeichenfläche platziert das Bauteil – es rastet am
    Raster ein.</li>
</ol>
<p><b>Tipp:</b> Wird ein Bauteil <i>direkt auf eine bestehende Leitung</i>
gesetzt, wird die Leitung automatisch an den beiden Anschlüssen des Bauteils
getrennt und angedockt — ebenso, wenn ein bestehendes Bauteil <i>per Drag auf
eine Leitung</i> geschoben wird (Andocken beim Loslassen) oder wenn eine
<i>neue Leitung über ein bestehendes Bauteil</i> gezogen wird (Trennung an
dessen Anschlüssen). Ausnahme: das Symbol <i>Strom</i> (Durchführung)
trennt nicht.</p>

<h3>Leitungen zeichnen</h3>
<ol>
<li>Palette → <i>Leitung</i> wählen.</li>
<li>Startpunkt anklicken – jeder weitere Klick setzt eine Leitung bis dorthin
    und die <b>nächste Leitung beginnt sofort am Endpunkt</b> (kontinuierliches
    Zeichnen von Linienzügen).</li>
<li><b>ESC</b> beendet das Zeichnen (bricht eine laufende Leitung ab).</li>
</ol>
<p>Leitungen lassen sich über das Dropdown <i>Linienfarbe</i> einfärben
(wirkt auch auf ausgewählte Leitungen).</p>

<h3>Leitungsenden anpassen (Griffpunkte)</h3>
<p>Leitung <b>auswählen</b> (Auswahlmodus, Klick auf die Leitung): an beiden
Enden erscheinen Griffpunkte. Griffpunkt ziehen verkürzt/verlängert die
Leitung bzw. setzt das Ende neu – mit Raster-Einrasten und <b>magnetischem
Andocken</b> am nächsten Bauteil-Anschluss.</p>

<h3>Bauteile bearbeiten</h3>
<ul>
<li><b>Verschieben:</b> im Auswahlmodus ziehen (rastet am Raster ein).</li>
<li><b>Drehen:</b> Taste <b>R</b> (auch während des Platzierens) oder
    Rechtsklick auf das Bauteil. Name und Wert ordnen sich dabei automatisch
    neu an: immer ausserhalb des Symbols, gegenüber dem Spannungsbogen.</li>
<li><b>Skalieren/Löschen:</b> Rechtsklick auf das Bauteil.</li>
<li><b>Werte beschriften</b> (Name, Spannung, Strom, Widerstand): Doppelklick
    auf das Bauteil oder direkt auf einen Beschriftungstext.</li>
<li><b>Beschriftung verschieben:</b> Bauteil auswählen – an jedem Text
erscheint ein kleiner <b>Griffpunkt</b>. Text am Griffpunkt (oder direkt) mit
gedrückter linker Maustaste ziehen – der Versatz bleibt beim Speichern
erhalten. Beim Drehen ordnen sich alle Beschriftungen neu an (ein alter
Versatz würde nach dem Drehen in die falsche Richtung zeigen). Solange das Bauteil <i>nicht</i> ausgewählt ist, fällt
der Klick durch den Text hindurch auf das Bauteil (auswählen/verschieben).</li>
<li><b>Auswahlrahmen:</b> im Auswahlmodus mit gedrückter linker Maustaste
    aufziehen; mehrere Elemente mit <b>Entf</b> löschen.</li>
</ul>

<h3>Messwerte angeben (Spannung &amp; Strom)</h3>
<ul>
<li><b>Spannungsbogen:</b> Palette → <i>Messwerte</i> → <i>Spannung</i>, dann auf ein
    Bauteil klicken. Ein blauer, leicht gebogener Bogen erscheint darüber;
    der Wert (z.&nbsp;B. 20 V, 15 mV, 10 kV) wird abgefragt.
    <b>Doppelklick</b> ändert ihn später, <b>Ziehen</b> verschiebt den Bogen,
    <b>Rechtsklick → „Richtung drehen"</b> spiegelt ihn (Messpfeil links/rechts).</li>
<li><b>Strompfeil:</b> <i>Messwerte</i> → <i>Strom</i>, dann auf eine Leitung klicken.
    Ein roter Pfeil wird in Leitungsrichtung aufgesetzt; der Wert
    (z.&nbsp;B. 20 A, 15 mA, 10 kA) wird abgefragt.
    <b>Doppelklick</b> ändert den Wert, <b>Rechtsklick → „Richtung drehen"</b>
    dreht den Pfeil um 180° (links↔rechts, oben↔unten).</li>
<li>Beide folgen ihrem Bauteil bzw. ihrer Leitung beim Verschieben und werden
    mitgelöscht. Sie werden beim Speichern gesichert und sind rückgängig machbar.</li>
</ul>

<h3>Bearbeiten &amp; Drucken (neu in 1.3)</h3>
<ul>
<li><b>Kopieren/Einfügen/Duplizieren:</b> Ctrl+C / Ctrl+V / Ctrl+D — an Polen
    angedockte Leitungen und Messwerte werden mitkopiert.</li>
<li><b>Feinverschiebung:</b> Pfeiltasten = 1 px, Shift+Pfeiltasten = Rasterschritt.</li>
<li><b>Knotenpunkte</b> an Verzweigungen werden automatisch gezeichnet
    (Punkt = verbunden).</li>
<li><b>A4-Blatt:</b> Ansicht → <i>A4-Blattrahmen</i>; Schriftfeld (Titel, Name,
    Datum …) über Ansicht → <i>Schriftfeld bearbeiten…</i></li>
<li><b>Drucken:</b> Datei → <i>Drucken…</i> (Ctrl+P) passt die Zeichnung auf die Seite ein.</li>
<li><b>Sicherung:</b> ungespeicherte Änderungen markiert der <b>*</b> im Titel;
    alle 3 Minuten wird automatisch gesichert (Datei → <i>Absturzsicherung
    wiederherstellen…</i>).</li>
</ul>

<h3>Funktionsschema-Simulation</h3>
<ul>
<li><b>Aufbau:</b> Schiene <i>L</i> oben und <i>N</i> unten setzen, Strompfade
    dazwischen zeichnen (Schalter, Taster, Spulen, Kontakte, Lampen, Motoren).</li>
<li><b>▶ Simulation</b> starten (Toolbar) — Schalter/Taster per Klick bedienen:
    Lampen leuchten, Motoren laufen (mit Richtungspfeil), der Strompfad wird rot
    hervorgehoben. <b>ESC</b> oder <b>■ Stop</b> beendet, <b>⟲</b> setzt zurück.</li>
<li><b>Relais:</b> Kontakte gehören zur Spule mit demselben Namen — Spulen
    heißen automatisch K1, K2 …, Zeitrelais KT1 …; ein neuer Kontakt gehört
    automatisch zum ersten Relais. <b>Rechtsklick auf den Kontakt →
    „Relais zuweisen“</b> wählt ein anderes Relais.</li>
<li><b>Kontakt-Spiegel (platzierbar):</b> Palette-Button <i>Kontaktspiegel</i> →
    ins Blatt klicken. Das Element zeigt alle Kontakte EINES Relais (Art,
    Position, Stellung — live während der Simulation, Spulenzustand im Kopf).
    Rechtsklick: <i>Relais zuweisen</i>, Doppelklick: Name ändern. Der
    <b>Toolbar-Button 🪞</b> öffnet zusätzlich die Gesamtübersicht als Dialog.</li>
<li><b>Symbole zeigen die Ruhelage</b> (stromlos / nicht betätigt):
    <i>Schliesser</i> ruht offen (Hebel abgehoben), <i>Öffner</i> ruht
    geschlossen (Hebel liegt auf) — beim Betätigen kehrt sich das um.</li>
<li><b>Schienen L+/M:</b> Schiene auswählen — am rechten Ende erscheint ein
    <b>Griffpunkt</b> zum Verlängern/Verkürzen (rastet aufs Raster).</li>
<li><b>Leitungswerkzeug bleibt aktiv:</b> ESC oder Rechtsklick beendet nur die
    laufende Leitung — der nächste Linksklick setzt sofort die nächste.</li>
<li><b>Zeitrelais:</b> Spule <i>Zeitrelais</i> + verzögerte Kontakte; Verzögerung
    am Platzhalter (z. B. «2 s») einstellen, Kontakte schalten verzögert.</li>
<li><b>Messgeräte:</b> Volt-/Amperemeter zeigen in klassischen Schaltungen
    (Batterie + Widerstände) reale Werte, wenn berechenbar — sonst «—».</li>
<li><b>Richtung des Motors:</b> Platzhalter <i>direction</i> = rechts/links
    (Doppelklick auf den Motor).</li>
</ul>

<h3>Ansicht</h3>
<ul>
<li><b>Zoomen:</b> Mausrad oder Buttons in der Toolbar.</li>
<li><b>Ausschnitt verschieben:</b> mittlere Maustaste ziehen.</li>
<li><b>Raster ein/aus:</b> Checkbox <i>Raster anzeigen</i> in der Toolbar.</li>
</ul>

<h3>Speichern &amp; Export</h3>
<ul>
<li><b>Speichern/Öffnen (Ctrl+S / Ctrl+O):</b> Schaltung als JSON-Datei.</li>
<li><b>PNG-Export:</b> exportiert den aktuell sichtbaren Ausschnitt.</li>
<li><b>SVG-Export:</b> exportiert die gesamte Zeichnungsfläche als Vektorgrafik.</li>
</ul>

<h3>Rückgängig</h3>
<p><b>Ctrl+Z</b> macht die letzte Aktion rückgängig, <b>Ctrl+Y</b> stellt sie
wieder her (Platzieren, Verschieben, Drehen, Leitungsenden, Löschen u.&nbsp;v.&nbsp;m.).</p>

<h3>Eigene Symbole erstellen</h3>
<p><b>Werkzeuge → Symbol-Editor…</b>: Symbole mit Linien, Kreisen und
Platzhaltern auf feinem Raster zeichnen. Mit dem Werkzeug
<b>Anschluss (Trennpunkt)</b> zwei Punkte setzen – sie legen fest, wo in der
Schaltung Leitungen getrennt und angedockt werden (violette Punkte).
Speichern als <i>&lt;name&gt;.symbol.json</i>; beim Schließen des Editors
erscheint das neue Symbol in der Palette.</p>

<h3>Vorhandenes Symbol bearbeiten</h3>
<p><b>Rechtsklick auf ein platziertes Bauteil → „Symbol bearbeiten…"</b> öffnet
den Symbol-Editor direkt mit diesem Symbol. Nach dem Speichern wird das
geänderte Symbol <i>überall</i> aktualisiert – in der Bauteil-Palette und bei
allen bereits platzierten Instanzen. Position, Drehung und Beschriftung der
platzierten Bauteile bleiben dabei erhalten.</p>
<p>Das gleiche Menü gibt es per <b>Rechtsklick auf einen Symbol-Button in der
linken Palette</b>.</p>

<h3>Palette anpassen</h3>
<p>Die Symbol-Buttons der linken Palette lassen sich <b>mit der Maus ziehen</b>
und innerhalb ihrer Gruppe neu einsortieren. Die Reihenfolge bleibt dauerhaft
gespeichert.</p>

<h3>Betriebsmittel-Kennzeichnung</h3>
<p>Neue Bauteile werden automatisch nummeriert – mit der kleinsten freien
Nummer ihres Kennbuchstabens nach <b>DIN EN 81346-2</b>:</p>
<table cellpadding="3">
<tr><td><b>G</b></td><td>Batterie (Energie erzeugen)</td></tr>
<tr><td><b>R</b></td><td>Widerstand, Diode, Spule (begrenzen) – gemeinsamer Zähler</td></tr>
<tr><td><b>C</b></td><td>Kondensator (speichern)</td></tr>
<tr><td><b>E</b></td><td>Lampe (Licht bereitstellen)</td></tr>
<tr><td><b>P</b></td><td>LED, Volt- und Amperemeter (Information darstellen)</td></tr>
<tr><td><b>F</b> / <b>M</b> / <b>S</b></td><td>Sicherung / Motor / Schalter und Taster</td></tr>
</table>
<p>Kopien erhalten eine freie Nummer. <i>Bearbeiten → Alle neu nummerieren</i>
vergibt die Nummern lückenlos in Leserichtung; <i>Bearbeiten → Automatisch
nummerieren</i> schaltet die Funktion ab. Eigene Namen (z.&nbsp;B. «Rv»)
bleiben unangetastet.</p>

<h3>Tastenkürzel</h3>
<table cellpadding="4">
<tr><td><b>ESC</b></td><td>Auswahlmodus (bricht Werkzeug/Leitung ab)</td></tr>
<tr><td><b>F1</b></td><td>Diese Anleitung</td></tr>
<tr><td><b>Ctrl+Z / Ctrl+Y</b></td><td>Rückgängig / Wiederherstellen</td></tr>
<tr><td><b>Ctrl+N / O / S</b></td><td>Neu / Öffnen / Speichern</td></tr>
<tr><td><b>R</b></td><td>Auswahl bzw. Vorschau um 90° drehen</td></tr>
<tr><td><b>Ctrl+A</b></td><td>Alles auswählen</td></tr>
<tr><td><b>Entf</b></td><td>Auswahl löschen</td></tr>
<tr><td><b>Ctrl+Plus / Ctrl+Minus</b></td><td>Vergrössern / Verkleinern (oder Mausrad)</td></tr>
<tr><td><b>Ctrl+0 / Pos1</b></td><td>100 % / Alles einpassen</td></tr>
</table>
"""


class GuideDialog(QDialog):
    """Scrollbare Kurz-Anleitung mit den wichtigsten Bedienpunkten."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Anleitung – SchaltungsZeichner")
        self.resize(640, 560)

        layout = QVBoxLayout(self)

        browser = QTextBrowser()
        browser.setHtml(GUIDE_HTML)
        browser.setOpenExternalLinks(True)
        layout.addWidget(browser)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("Schließen")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
