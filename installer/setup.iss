; SchaltungsZeichner - Inno Setup-Skript
; Baut eine einzelne Setup.exe (Aufruf ueber make_release.py bzw. ISCC.exe).
;
; Eigenschaften:
; - Installation pro Benutzer nach %LOCALAPPDATA%\Programs\SchaltungsZeichner
;   (PrivilegesRequired=lowest -> keine Admin-Rechte noetig)
; - GPL-Lizenzseite (LICENSE) im Assistenten
; - Symbole landen NEBEN der EXE unter {app}\symbols (persistent editierbar);
;   bei Updates werden nur FEHLENDE Symbol-Dateien ergaenzt - bestehende
;   (vom Nutzer geaenderte) bleiben unberuehrt (onlyifdoesntexist)
; - Deinstaller mit Eintrag in "Apps & Features"

#define MyAppName "SchaltungsZeichner FS"
#define MyAppVersion "1.4-FS"
#define MyAppPublisher "fentrax"
#define MyAppExeName "SchaltungsZeichner-FS.exe"
#define MyAppGuid "{B7C1D9A2-4E5F-4C6B-9A3D-1E2F3A4B5C6D}"

[Setup]
AppId={{#MyAppGuid}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\release
OutputBaseFilename=SchaltungsZeichner-Setup
SetupIconFile=..\assets\favicon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=..\LICENSE

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzliche Symbole:"; Flags: unchecked

[Files]
; Hauptprogramm
Source: "..\dist\SchaltungsZeichner\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; Laufzeitdaten OHNE den eingebetteten symbols-Ordner (der wandert nach {app}\symbols)
Source: "..\dist\SchaltungsZeichner\_internal\*"; DestDir: "{app}\_internal"; Excludes: "symbols"; Flags: ignoreversion recursesubdirs createallsubdirs
; Symbol-Bibliothek sichtbar und persistent neben der EXE:
; bei Updates nur fehlende Dateien ergaenzen, Nutzer-Aenderungen bleiben.
Source: "..\dist\SchaltungsZeichner\_internal\symbols\*"; DestDir: "{app}\symbols"; Flags: ignoreversion onlyifdoesntexist recursesubdirs createallsubdirs
; Beispieldateien (bei Updates nicht ueberschreiben, falls der Nutzer sie geaendert hat)
Source: "..\examples\*"; DestDir: "{app}\examples"; Flags: ignoreversion onlyifdoesntexist
; Lizenz mitgeben (GPL)
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Comment: "Schaltpläne zeichnen"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; Dateiendung .sz registrieren (Doppelklick oeffnet die Schaltung);
; pro Benutzer (HKCU), keine Admin-Rechte noetig.
Root: HKCU; Subkey: "Software\Classes\.sz"; ValueType: string; ValueName: ""; ValueData: "SchaltungsZeichner.sz"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\SchaltungsZeichner.sz"; ValueType: string; ValueName: ""; ValueData: "SchaltungsZeichner-Schaltung"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SchaltungsZeichner.sz\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SchaltungsZeichner.sz\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{#MyAppName} jetzt starten"; Flags: nowait postinstall skipifsilent
