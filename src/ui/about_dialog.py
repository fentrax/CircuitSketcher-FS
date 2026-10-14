"""
Über-Dialog – Professionelle Info-Seite mit Logo und Kontaktmöglichkeit.

Logo und E-Mail sind hier zentral konfiguriert:
- SUPPORT_EMAIL : Adresse für „Fragen und Anregungen" (mailto-Link)
- LOGO_FILENAME : Dateiname im assets/-Ordner (z. B. logo.png)

Das Logo wird (falls vorhanden) auf LOGO_DISPLAY_WIDTH verkleinert und
oberhalb des Texts zentriert. Fehlt die Datei, erscheint der Dialog ohne
Logo – auch in der eingefrorenen EXE (Pfadauflösung wie bei symbols/).
"""
import sys
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

# ----------------------------------------------------------------------
# Konfiguration
# ----------------------------------------------------------------------
ORG_NAME = "fentrax"
REPO_URL = "https://github.com/fentrax/CircuitSketcher-FS"
ISSUES_URL = "https://github.com/fentrax/CircuitSketcher-FS/issues"
LOGO_FILENAME = "logo.png"  # gesucht unter <App-Basis>/assets/logo.png
LOGO_DISPLAY_WIDTH = 360  # Anzeige-Breite in Pixeln

COPYRIGHT_LINE = "© 2026 fentrax"
APP_VERSION = "Version 1.5-FS"
APP_DESCRIPTION = (
    "Erstellen Sie einfache Schaltpläne für Prüfungsaufgaben, Tests und\n"
    "Unterrichtsmaterial – schnell, übersichtlich und normgerecht."
)
LICENSE_NAME = "GNU General Public License v3"
LICENSE_URL = "https://www.gnu.org/licenses/gpl-3.0.html"
SOURCE_OFFER_TEXT = (
    "Diese Software ist lizenziert unter der GNU General Public License v3.\n"
    "Der vollständige Quellcode ist öffentlich auf GitHub verfügbar."
)


def _app_base_dir() -> Path:
    """Basisverzeichnis der Anwendung (PyInstaller-frozen-safe)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


class AboutDialog(QDialog):
    """Über-Dialog mit Logo, Versionsinfo und GitHub-Kontakt."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Über SchaltungsZeichner")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Logo (zentriert, auf Anzeigebreite skaliert; ohne Datei übersprungen)
        logo_pixmap = self._load_logo()
        if logo_pixmap is not None:
            logo_label = QLabel()
            logo_label.setPixmap(logo_pixmap)
            logo_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(logo_label)

        # Titel und Beschreibung
        title = QLabel("<b>SchaltungsZeichner</b>")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 16px;")
        layout.addWidget(title)

        version = QLabel(APP_VERSION)
        version.setAlignment(Qt.AlignCenter)
        version.setStyleSheet("color: #666;")
        layout.addWidget(version)

        description = QLabel(APP_DESCRIPTION)
        description.setAlignment(Qt.AlignCenter)
        description.setWordWrap(True)
        layout.addWidget(description)

        layout.addWidget(self._separator())

        # Kontaktbereich: Fragen, Fehler und Anregungen über GitHub
        contact_title = QLabel("Fragen, Probleme und Anregungen")
        contact_title.setStyleSheet("font-weight: bold;")
        layout.addWidget(contact_title)

        issue_layout = QHBoxLayout()
        issue_prompt = QLabel("Auf GitHub melden:")
        self.issue_label = QLabel(f'<a href="{ISSUES_URL}">Issues · {ORG_NAME}</a>')
        self.issue_label.setOpenExternalLinks(True)
        self.issue_label.setStyleSheet("color: #0a58ca;")
        issue_layout.addWidget(issue_prompt)
        issue_layout.addWidget(self.issue_label, stretch=1)
        layout.addLayout(issue_layout)

        layout.addWidget(self._separator())

        # Lizenzbereich (GPL v3, Quellcode-Angebot)
        license_title = QLabel("Lizenz")
        license_title.setStyleSheet("font-weight: bold;")
        layout.addWidget(license_title)

        license_text = QLabel(SOURCE_OFFER_TEXT)
        license_text.setWordWrap(True)
        layout.addWidget(license_text)

        license_link_layout = QHBoxLayout()
        license_link = QLabel(f'<a href="{LICENSE_URL}">{LICENSE_NAME}</a>')
        license_link.setOpenExternalLinks(True)
        license_link.setStyleSheet("color: #0a58ca;")
        license_link_layout.addWidget(license_link)
        license_link_layout.addStretch()
        source_link = QLabel(f'<a href="{REPO_URL}">Quellcode auf GitHub</a>')
        source_link.setOpenExternalLinks(True)
        source_link.setStyleSheet("color: #0a58ca;")
        license_link_layout.addWidget(source_link)
        license_link_layout.addStretch()
        layout.addLayout(license_link_layout)

        layout.addWidget(self._separator())

        footer = QLabel(f"{COPYRIGHT_LINE} · Erstellt mit PyQt5")
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet("color: #999; font-size: 11px;")
        layout.addWidget(footer)

        # Schließen-Button
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        close_button = QPushButton("Schließen")
        close_button.setDefault(True)
        close_button.clicked.connect(self.accept)
        button_layout.addWidget(close_button)
        layout.addLayout(button_layout)

    @staticmethod
    def _separator():
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #ddd; background-color: #ddd; max-height: 1px;")
        return line

    @staticmethod
    def _load_logo():
        """Logo laden und auf Anzeigebreite skalieren; None falls nicht vorhanden."""
        logo_path = _app_base_dir() / "assets" / LOGO_FILENAME
        if not logo_path.exists():
            return None
        pixmap = QPixmap(str(logo_path))
        if pixmap.isNull():
            return None
        if pixmap.width() > LOGO_DISPLAY_WIDTH:
            pixmap = pixmap.scaledToWidth(
                LOGO_DISPLAY_WIDTH, Qt.SmoothTransformation
            )
        return pixmap
