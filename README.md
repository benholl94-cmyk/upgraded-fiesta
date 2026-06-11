# Lokale Entwicklerumgebung auf dem iPhone

Dieses Repository enthält eine sofort deploybare, deutschsprachige Plattform und ein vollständiges Setup für eine möglichst lokale Entwicklerumgebung auf dem iPhone.

- Plattform: [`index.html`](index.html)
- Hauptanleitung: [`docs/iphone-local-dev-setup.md`](docs/iphone-local-dev-setup.md)
- Schwerpunkt: autonome Setup-Pläne, Direct-Inject-Skripte, lokale Shell, Git-Workflow, Editor, Python/JavaScript, SSH, Backups und Wartung
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

1. Öffne `index.html` direkt im Browser oder deploye den Ordner unverändert auf einem statischen Hoster.
2. Wähle in der Plattform ein Profil: **Minimal lokal**, **Linux-nah** oder **Hybrid Remote**.
3. Kopiere den generierten **Direct-Inject**-Block in a-Shell, iSH oder deinen Remote-Host.
4. Installiere für den produktiven iPhone-Workflow **Working Copy**, **a-Shell** und **Textastic** oder **Code App**.
5. Klone dein Repository in Working Copy, ändere eine kleine Datei, prüfe den Diff, committe und pushe.

## Sofort-Deploy

```sh
python3 -m http.server 8000
# dann öffnen: http://localhost:8000
```

Für Hosting reicht das Hochladen der statischen Dateien `index.html`, `styles.css`, `app.js`, `manifest.webmanifest`, `service-worker.js`, `README.md` und `docs/`. Es gibt keinen Build-Schritt und keine Server-Konfiguration.

## Was dieses Setup konkret abdeckt

- Lokale Dateistruktur unter `Developer/` für Repositories, Experimente, Exporte und Backups.
- Git-Identität, Branch-Workflow und sicherer Push/Pull-Ablauf.
- Copy-and-paste-Kommandos für a-Shell, iSH, Python, JavaScript, SSH und lokale Webserver.
- Entscheidungshilfe, wann lokal auf dem iPhone gearbeitet wird und wann ein Remote-Host besser ist.
