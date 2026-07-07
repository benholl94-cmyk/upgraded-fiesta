# Lokale Entwicklerumgebung auf dem iPhone

> Imported from PR #16 (a standalone static site with no shared history with the
> rest of this repository) into this isolated directory. Fully self-contained:
> its own `package.json`, `validate.py`/`test-validate.py`, no dependency on
> anything in `crates/`, `ui/`, or the repo root. Run its checks from inside this
> directory (`cd iphone-dev-platform && npm test`), not from the repo root.

Dieses Verzeichnis enthält eine sofort deploybare, deutschsprachige Plattform und ein vollständiges Setup für eine möglichst lokale Entwicklerumgebung auf dem iPhone.

- Plattform: [`index.html`](index.html)
- Hauptanleitung: [`docs/iphone-local-dev-setup.md`](docs/iphone-local-dev-setup.md)
- Schwerpunkt: sichere Schnellzugriffe, autonome Setup-Pläne, Direct-Inject-Skripte, lokale Shell, Git-Workflow, Editor, Python/JavaScript, SSH, Backups und Wartung
- Stand der geprüften App-/Tool-Informationen: 2026-06-11

## Kurzempfehlung

Für die meisten iPhone-Workflows ist die stabilste Kombination:

1. **Working Copy** für Git-Repositories, Commits, Branches und Push/Pull.
2. **Textastic** oder **Code App** als Code-Editor.
3. **a-Shell** für schnelle lokale Skripte, Python, JavaScript und Unix-Werkzeuge.
4. **iSH** als Alpine-Linux-ähnliche Umgebung, wenn du `apk`, Linux-Pakete oder eine klassische Shell brauchst.
5. **Blink Shell** oder ein anderer SSH/Mosh-Client optional für Remote-Builds, falls lokale iOS-Grenzen erreicht werden.

Die Details inklusive Installationsbefehlen, Verzeichnisstruktur, Git-Konfiguration, Testbefehlen und Fehlerbehebung stehen in der vollständigen Anleitung.

## Schnellstart in 15 Minuten

1. Starte lokal `npm run serve` oder deploye den Ordner unverändert auf einem statischen Hoster; `index.html` kann für die UI auch direkt geöffnet werden, der QA-Scanner benötigt aber Zugriff auf `docs/`.
2. Wähle in der Plattform ein Profil: **Minimal lokal**, **Linux-nah** oder **Hybrid Remote**.
3. Kopiere den generierten **Direct-Inject**-Block in a-Shell, iSH oder deinen Remote-Host.
4. Installiere für den produktiven iPhone-Workflow **Working Copy**, **a-Shell** und **Textastic** oder **Code App**.
5. Klone dein Repository in Working Copy, ändere eine kleine Datei, prüfe den Diff, committe und pushe.

## Sichere Zugänge

Die Plattform bündelt die wichtigsten Bereiche auf einer eigenen Schnellzugriffsfläche:

- **Guide** für Planung und Details.
- **Autopilot** für profilbasierte Setup-Schritte.
- **Direct-Inject** für lokal erzeugte, lesbare Copy/Paste-Blöcke.
- **QA-Scanner** für unklare Artefakte und riskante Muster.
- **Requests & Updates** für vollständige Änderungsanfragen mit Update-Plan und Abnahmecheck.
- **Deploy** für statisches Hosting ohne Build-Schritt.

Direct-Inject-Blöcke werden nicht automatisch ausgeführt, nutzen bereinigte Projektnamen und schreiben standardmäßig nur unter `~/Developer/scratch/`. Request-Pakete bleiben ebenfalls lokal im Browser, enthalten Sicherheitsgrenzen, Update-Schritte und reproduzierbare Abnahmekommandos.

## Init und lokale Prüfung

Das Projekt benötigt keine Paketinstallation. Die Initialprüfung nutzt nur Python und Node, falls Node verfügbar ist:

```sh
npm run init
npm test
```

`npm run init` validiert die statischen Dateien, die wichtigsten Zugänge, das Manifest und die Guide-Struktur. `npm test` ergänzt Syntaxprüfungen für `app.js` und `service-worker.js`.

## Sofort-Deploy

```sh
npm run serve
# dann öffnen: http://localhost:8000
```

Alternativ funktioniert weiterhin:

```sh
python3 -m http.server 8000
```

Für Hosting reicht das Hochladen der statischen Dateien `index.html`, `styles.css`, `app.js`, `manifest.webmanifest`, `service-worker.js`, `README.md`, `package.json`, `scripts/` und `docs/`. Es gibt keinen Build-Schritt und keine Server-Konfiguration.

## Was dieses Setup konkret abdeckt

- Lokale Dateistruktur unter `Developer/` für Repositories, Experimente, Exporte und Backups.
- Git-Identität, Branch-Workflow und sicherer Push/Pull-Ablauf.
- Copy-and-paste-Kommandos für a-Shell, iSH, Python, JavaScript, SSH und lokale Webserver.
- Entscheidungshilfe, wann lokal auf dem iPhone gearbeitet wird und wann ein Remote-Host besser ist.
