# Lokale Entwicklerumgebung auf dem iPhone

Dieses Repository enthält eine vollständige, deutschsprachige und ausführbare Produktionsbasis für eine möglichst lokale Entwicklerumgebung auf dem iPhone.

- Hauptanleitung: [`docs/iphone-local-dev-setup.md`](docs/iphone-local-dev-setup.md)
- Ausführbares iPhone-Shell-Bootstrap: [`scripts/iphone_local_dev_bootstrap.sh`](scripts/iphone_local_dev_bootstrap.sh)
- Repository-Qualitätsprüfung: [`scripts/validate_repository.sh`](scripts/validate_repository.sh)
- Live-Inventar und Audit-Report: [`scripts/repository_audit_report.sh`](scripts/repository_audit_report.sh)
- Stand der geprüften Repository-Inhalte: 2026-06-12
- Live-Datum/Uhrzeit werden von den Skripten zur Laufzeit mit `date` ermittelt, damit keine statischen Messwerte als aktuelle Daten ausgegeben werden.

## Kurzempfehlung

Für die meisten iPhone-Workflows ist die stabilste Kombination:

1. **Working Copy** für Git-Repositories, Commits, Branches und Push/Pull.
2. **Textastic** oder **Code App** als Code-Editor.
3. **a-Shell** für schnelle lokale Skripte, Python, JavaScript und Unix-Werkzeuge.
4. **iSH** als Alpine-Linux-ähnliche Umgebung, wenn `apk`, Linux-Pakete oder eine klassische Shell gebraucht werden.
5. **Blink Shell** oder ein anderer SSH/Mosh-Client optional für Remote-Builds, falls lokale iOS-Grenzen erreicht werden.

## Produktionsskripte

```sh
scripts/validate_repository.sh
scripts/repository_audit_report.sh --format markdown
scripts/iphone_local_dev_bootstrap.sh --dry-run
scripts/iphone_local_dev_bootstrap.sh
```

`validate_repository.sh` prüft Pflichtdateien, leere Dateien, Shell-Syntax, ausführbare Bits, lokale Markdown-Links, Git-Whitespace, Audit-Erzeugbarkeit und offene Inhaltslücken-Marker. `repository_audit_report.sh` erzeugt zur Laufzeit ein vollständiges Live-Inventar aller Repository-Ordner und Dateien mit Hashes, Größen, Zeitstempeln und Qualitätsbefunden. `iphone_local_dev_bootstrap.sh` erstellt idempotent eine belastbare lokale Developer-Struktur und ein wiederverwendbares Shell-Profil für a-Shell oder iSH.
