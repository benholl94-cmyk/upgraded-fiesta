# Vollständiges Setup: lokale Entwicklerumgebung auf dem iPhone

Stand der Repository-Prüfung: 2026-06-12. Live-Zeitstempel, Tool-Versionen und lokale Diagnosedaten werden nicht statisch dokumentiert, sondern durch `scripts/iphone_local_dev_bootstrap.sh` und `scripts/validate_repository.sh` zur Laufzeit aus dem jeweiligen System gelesen.

## 1. Zielbild

Nach dem Setup kann ein iPhone als mobile Entwicklungsstation eingesetzt werden für:

- Git-Repositories klonen, prüfen, bearbeiten, committen, branchen und pushen.
- Markdown-, Shell-, Python- und JavaScript-Dateien lokal bearbeiten.
- Kleine Skripte lokal ausführen und reproduzierbar testen.
- SSH-Zugänge sicher nutzen und Remote-Builds starten.
- Lokale Webserver auf `127.0.0.1` starten.
- Dateien zwischen Git-Client, Editor, Terminal und Dateien-App kontrolliert austauschen.
- Backups und Wiederherstellung mit klarer Ordnerstruktur planen.

## 2. Realistische Grenzen von iOS

Ein iPhone ist für mobile Änderungen, Dokumentation, kleine Skripte und Remote-Steuerung sehr gut geeignet. Es ersetzt für große Projekte keinen vollwertigen Linux- oder macOS-Rechner.

- iOS begrenzt Hintergrundprozesse; lange Builds und Watch-Prozesse können beendet werden.
- Docker, Kernel-Module, Systemdienste und viele native Toolchains laufen nicht wie auf Linux.
- App-Sandboxing trennt Dateisysteme; Austausch erfolgt über Dateien-App, Dokumentanbieter, WebDAV, Git oder explizite Freigaben.
- Große Node-, Rust-, Java-, Swift- oder C/C++-Builds gehören auf einen Mac, Linux-Server, Codespace, CI-Runner oder Homelab-Host.

## 3. Geprüfte App-Rollen

| Rolle | Empfehlung | Produktionsnutzen | Offizielle Quelle |
| --- | --- | --- | --- |
| Git | Working Copy | Repositories, Branches, Commits, Push/Pull, Konfliktlösung, Dateien-App-Integration | https://apps.apple.com/us/app/working-copy-git-client/id896694807 |
| Lokales Terminal | a-Shell | Lokale Unix-Befehle, Python, JavaScript, C/C++, `curl`, `vim`, Dateiwerkzeuge | https://apps.apple.com/us/app/a-shell/id1473805438 |
| Linux-ähnliche Shell | iSH | Alpine-Linux-Umgebung mit `apk`-Paketen | https://github.com/ish-app/ish |
| Code-Editor | Textastic | Code-Editor für iPhone/iPad, externe Working-Copy-Ordner, SFTP/SSH | https://apps.apple.com/us/app/textastic-code-editor/id1049254261 |
| All-in-one-Editor | Code App | Monaco-basierter Editor, lokale Dateien, Terminal, Git, `pip` und `npm` | https://apps.apple.com/us/app/code-app/id1512938504 |
| Remote-Terminal | Blink Shell | SSH/Mosh für stabile Remote-Sessions | https://blink.sh/ |

Minimal stabil: Working Copy, a-Shell und Textastic. Code App kann Textastic und Terminal teilweise bündeln. iSH ist sinnvoll, wenn Linux-Paketverwaltung gebraucht wird.

## 4. Repository-Skripte

### 4.1 Qualität prüfen

Vom Repository-Stamm ausführen:

```sh
scripts/validate_repository.sh
```

Die Prüfung deckt ab:

- Pflichtdateien vorhanden und nicht leer.
- Keine offenen Arbeitsmarker für unfertige Inhalte.
- Shell-Syntax aller Skripte gültig.
- Skripte sind ausführbar.
- Lokale Markdown-Links zeigen auf vorhandene Dateien.
- `git diff --check` meldet keine Whitespace-Fehler.
- Start- und Endzeit werden als UTC-Zeitstempel ausgegeben.

### 4.2 iPhone-Shell vorbereiten

Zuerst ohne Änderungen prüfen:

```sh
scripts/iphone_local_dev_bootstrap.sh --dry-run
```

Dann anwenden:

```sh
scripts/iphone_local_dev_bootstrap.sh
```

Das Skript erstellt unter `~/Developer` diese Ordner:

```text
Developer/
  repos/
  scratch/
  keys/
  exports/
  backups/
  logs/
```

Zusätzlich schreibt es `~/.iphone-local-dev-profile`. Diese Datei wird mit folgendem Befehl in die App-Shell geladen:

```sh
. "$HOME/.iphone-local-dev-profile"
```

Für Git-Identität können Werte vor dem Start gesetzt werden; ohne diese Variablen verändert das Skript keine persönliche Identität:

```sh
export GIT_AUTHOR_NAME="$(id -un 2>/dev/null || printf '%s' mobile)"
export GIT_AUTHOR_EMAIL="$(id -un 2>/dev/null || printf '%s' mobile)@users.noreply.github.com"
scripts/iphone_local_dev_bootstrap.sh
```


### 4.3 Vollständiges Live-Repository-Audit

Für eine aktuelle Inventarisierung jedes Ordners und jeder Datei im Checkout:

```sh
scripts/repository_audit_report.sh --format markdown
```

Maschinenlesbare Ausgabe für CI, Archivierung oder spätere Diff-Prüfungen:

```sh
scripts/repository_audit_report.sh --format json --output /tmp/upgraded-fiesta-audit.json
```

Der Audit-Report liest alle Daten live aus dem aktuellen Dateisystem und Git-Checkout. Er enthält UTC-Start- und Endzeit, Git-Branch, Git-HEAD, Arbeitsbaumstatus, Tool-Versionen, Ordnerliste, Dateiliste, SHA-256-Hashes, Dateigrößen, Zeilenzahlen, Änderungszeiten, Shell-Syntaxstatus, lokale Markdown-Link-Befunde und Inhaltslücken-Befunde.

## 5. Basisinstallation auf dem iPhone

1. iOS über **Einstellungen → Allgemein → Softwareupdate** aktualisieren.
2. iCloud Drive aktivieren, wenn Dokumente zwischen Apps gesichert werden sollen.
3. Passwortverwaltung aktivieren, beispielsweise iCloud-Schlüsselbund, 1Password oder Bitwarden.
4. Externe Tastatur koppeln, wenn regelmäßig Terminal- oder Git-Arbeit geplant ist.
5. Working Copy installieren und mit der Git-Plattform verbinden.
6. a-Shell installieren und `python3 --version`, `node --version`, `curl --version` prüfen.
7. Textastic oder Code App installieren und mit dem Working-Copy-Repository testen.
8. Optional iSH installieren, falls Linux-Pakete über `apk` benötigt werden.
9. Optional Blink Shell installieren, falls Remote-Sessions länger laufen müssen.

## 6. Git mit Working Copy

### 6.1 Konto verbinden

1. Working Copy öffnen.
2. GitHub, GitLab, Bitbucket oder einen eigenen Git-Server verbinden.
3. OAuth, Passkey, SSH-Key oder Personal Access Token mit minimalen Rechten nutzen.
4. Repository klonen.
5. Pro-Features nur dort aktivieren, wo sie für Push, Dateifreigaben oder Automatisierung notwendig sind.

### 6.2 Git-Identität setzen

In Working Copy pro Repository oder global setzen:

- Name: derselbe Name, der auch auf der Git-Plattform angezeigt werden soll.
- Email: GitHub-Noreply-Adresse oder eine dedizierte Commit-Adresse.

In iSH oder einer klassischen Shell:

```sh
git config --global user.name "$GIT_AUTHOR_NAME"
git config --global user.email "$GIT_AUTHOR_EMAIL"
git config --global init.defaultBranch main
git config --global pull.ff only
```

### 6.3 Standard-Workflow

1. `Fetch` oder `Pull` ausführen.
2. Branch erstellen, beispielsweise mit Datum und Zweck im Namen.
3. Dateien im Editor bearbeiten.
4. Diff in Working Copy prüfen.
5. Kleine, logisch abgeschlossene Commits erstellen.
6. Branch pushen.
7. Pull Request auf der Git-Plattform öffnen.

## 7. a-Shell

### 7.1 Erste Prüfung

```sh
pwd
help -l
python3 --version
node --version
clang --version
curl --version
```

### 7.2 Profil laden

Nach dem Bootstrap:

```sh
. "$HOME/.iphone-local-dev-profile"
printf '%s\n' "$DEV_URL"
```

### 7.3 Python-Test

```sh
mkdir -p "$IPHONE_DEV_HOME/scratch/hello-python"
cd "$IPHONE_DEV_HOME/scratch/hello-python"
printf 'print("Hallo vom iPhone")\n' > hello.py
python3 hello.py
```

### 7.4 JavaScript-Test

```sh
mkdir -p "$IPHONE_DEV_HOME/scratch/hello-js"
cd "$IPHONE_DEV_HOME/scratch/hello-js"
printf 'console.log("Hallo vom iPhone")\n' > hello.js
node hello.js
```

Wenn `node` nicht verfügbar ist, JavaScript in Code App oder auf einem Remote-Host ausführen.

## 8. iSH

### 8.1 Pakete aktualisieren

```sh
apk update
apk upgrade
```

### 8.2 Basiswerkzeuge installieren

```sh
apk add git openssh curl wget nano vim python3 py3-pip nodejs npm make
```

Wenn ein Paketname nicht vorhanden ist:

```sh
apk search python
apk search node
apk search git
cat /etc/apk/repositories
```

### 8.3 SSH-Key erzeugen

```sh
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
ssh-keygen -t ed25519 -C "$GIT_AUTHOR_EMAIL"
chmod 600 "$HOME/.ssh/id_ed25519"
chmod 644 "$HOME/.ssh/id_ed25519.pub"
cat "$HOME/.ssh/id_ed25519.pub"
```

Nur den öffentlichen Schlüssel aus `id_ed25519.pub` kopieren. Der private Schlüssel `id_ed25519` bleibt auf dem Gerät und wird nie verschickt.

### 8.4 SSH testen

Für GitHub:

```sh
ssh -T git@github.com
```

Für eigene Infrastruktur:

```sh
ssh "$REMOTE_USER@$REMOTE_HOST"
```

`REMOTE_USER` und `REMOTE_HOST` müssen bewusst in der aktuellen Shell gesetzt werden; das Repository speichert keine privaten Zugangsdaten.

## 9. Editor-Workflow

### 9.1 Textastic mit Working Copy

1. Repository in Working Copy klonen.
2. Textastic öffnen.
3. Working-Copy-Repository-Ordner als externen Ordner hinzufügen.
4. Dateien in Textastic bearbeiten.
5. Zurück in Working Copy Diff prüfen, committen und pushen.

### 9.2 Code App

Code App eignet sich, wenn Editor, Terminal, Git und kleine Paketmanager-Aufgaben in einer App bevorzugt werden.

Empfohlener Ablauf:

1. Lokalen Projektordner öffnen.
2. Repository verbinden oder Dateien aus Working Copy freigeben.
3. Kleine Tests direkt im eingebetteten Terminal ausführen.
4. Große Builds auf Remote-Host verschieben.

## 10. Lokale Web-Entwicklung

Das Bootstrap-Profil setzt diese produktiven Defaults:

| Variable | Wert | Zweck |
| --- | --- | --- |
| `DEV_HOST` | `127.0.0.1` | Adresse, die im Browser geöffnet wird. |
| `DEV_BIND` | `127.0.0.1` | Adresse, auf der der Server lauscht. |
| `DEV_PORT` | `8000` | Standardport für kleine lokale Server. |
| `DEV_ALT_PORT` | `3000` | Alternativport für Frontend-Projekte. |
| `DEV_URL` | `http://127.0.0.1:8000` | Kopierbare lokale Basis-URL. |
| `NO_PROXY` | lokale Hosts | Lokale Ziele umgehen Proxy und VPN-Sonderrouting. |

Server starten:

```sh
cd "$IPHONE_DEV_HOME/scratch"
python3 -m http.server "$DEV_PORT" --bind "$DEV_BIND"
```

Browser-URL:

```text
http://127.0.0.1:8000
```

Nur in vertrauenswürdigen lokalen Netzen auf allen Interfaces lauschen:

```sh
DEV_BIND=0.0.0.0 python3 -m http.server "$DEV_PORT" --bind 0.0.0.0
```

## 11. Netzwerkdiagnose

```sh
printf '%s\n' "$DEV_URL"
curl -I "$DEV_URL"
curl -I https://www.iana.org/
python3 - <<'PY'
import socket
print(socket.gethostbyname('www.iana.org'))
PY
```

Fehlerbilder:

- `Connection refused`: Server läuft nicht oder lauscht auf anderem Port.
- `Timeout`: VPN, Firewall, Mobilfunknetz oder iOS-Hintergrundverhalten blockiert.
- `404`: Server läuft, aber Arbeitsordner oder Pfad ist falsch.
- Zertifikatsfehler: Datum/Uhrzeit prüfen und eigene CA nur bewusst installieren.

## 12. Internet- und API-Grundlagen

- **IP-Adresse**: numerische Adresse eines Geräts oder Servers.
- **DNS**: übersetzt Namen in IP-Adressen.
- **HTTP/HTTPS**: Protokoll für Webseiten und APIs; HTTPS verschlüsselt und prüft Zertifikate.
- **Port**: Dienstnummer wie `22`, `80`, `443`, `8000` oder `3000`.
- **TLS-Zertifikat**: Vertrauensnachweis für HTTPS.
- **Token und Sessions**: wie Passwörter behandeln.
- **API**: maschinenlesbare Schnittstelle, oft JSON über HTTPS.

Sicherer API-Aufruf ohne Token in Dateien:

```sh
IFS= read -r API_TOKEN
curl -fsS -H "Authorization: Bearer $API_TOKEN" https://api.github.com/user
unset API_TOKEN
```

Statuscodes beachten: `200` Erfolg, `201` erstellt, `400` fehlerhafte Anfrage, `401` nicht angemeldet, `403` keine Rechte oder Rate-Limit, `404` nicht gefunden, `429` zu viele Anfragen, `500` Serverfehler.

## 13. Remote-Ergänzung für große Projekte

Wenn lokale Grenzen erreicht sind:

- Mac mini, MacBook, Linux-Server, VPS, Codespace oder CI-Runner verwenden.
- SSH/Mosh mit Blink Shell, a-Shell oder iSH nutzen.
- Git als Synchronisationsquelle behalten.
- Builds, Tests, Docker, Datenbanken und lange Prozesse remote ausführen.

Remote-Workflow mit bewusst gesetzten Zielvariablen:

```sh
ssh "$REMOTE_USER@$REMOTE_HOST"
cd "$REMOTE_PROJECT_DIR"
git pull --ff-only
npm test
```

## 14. Sicherheit

- Face ID oder starken Gerätecode aktivieren.
- Pro Dienst separate Tokens mit minimalen Rechten verwenden.
- SSH-Keys mit Passphrase schützen.
- Recovery-Codes außerhalb des iPhones speichern.
- Alte Tokens und Keys regelmäßig entfernen.
- Vor jedem Push Diff prüfen.
- Private Keys, `.env`-Dateien, Sessions und Tokens nie in Git speichern.
- OAuth-Berechtigungen vor Zustimmung lesen.
- VPN nur verwenden, wenn Anbieter und Profil vertrauenswürdig sind.

## 15. Backup-Strategie

Mindestens eine Sicherung muss aktiv sein:

1. Remote-Git-Repository als primäre Sicherung.
2. iCloud-Backup des iPhones.
3. Manuelle ZIP-Exports wichtiger Projekte nach `~/Developer/backups`.
4. Regelmäßige Pushes nach kleinen Arbeitsschritten.

Regel: Nicht committete Änderungen sind nicht zuverlässig gesichert.

## 16. Wartung

Wöchentlich:

```sh
git status
git fetch --all --prune
scripts/validate_repository.sh
```

In iSH:

```sh
apk update
apk upgrade
```

Monatlich:

- Alte Branches löschen.
- Nicht benötigte Klone entfernen.
- Tokens und SSH-Keys prüfen.
- Backups testweise öffnen.
- App-Updates prüfen.
- Remote-Build-Hosts patchen.

## 17. Fehlerbehebung

### Git-Push schlägt fehl

- Internetverbindung und VPN prüfen.
- Token-, OAuth- oder SSH-Key-Rechte prüfen.
- `Fetch` ausführen und Konflikte lösen.
- Sicherstellen, dass Branch und Remote korrekt sind.

### Editor sieht Repository-Dateien nicht

- Repository-Ordner erneut über die Dateien-App freigeben.
- In Working Copy prüfen, ob externe Ordnerfreigabe aktiv ist.
- Keine parallelen Kopien desselben Repositories bearbeiten.

### Paketinstallation in iSH schlägt fehl

```sh
apk update
apk search git
apk search python
cat /etc/apk/repositories
```

Wenn Repository-Konfigurationen veraltet sind, iSH-Empfehlungen zur Paketquelle befolgen oder iSH neu installieren und nur Projektdaten migrieren.

### Lokaler Server ist nicht erreichbar

- Terminal-App im Vordergrund halten.
- `DEV_PORT`, `DEV_BIND` und URL prüfen.
- Server neu starten.
- Browser mit `http://127.0.0.1:8000` statt `localhost` testen.

## 18. Abschluss-Checkliste

- [ ] iOS aktualisiert.
- [ ] Working Copy installiert und Git-Konto verbunden.
- [ ] Editor installiert und mit Working Copy getestet.
- [ ] a-Shell installiert und Tool-Versionen geprüft.
- [ ] Repository-Validierung erfolgreich ausgeführt.
- [ ] Bootstrap im Dry-Run geprüft.
- [ ] Bootstrap angewendet und Profil geladen.
- [ ] Optional iSH installiert und `apk update` geprüft.
- [ ] SSH-Key oder Token eingerichtet.
- [ ] Test-Repository geklont.
- [ ] Localhost mit `http://127.0.0.1:8000` getestet.
- [ ] Internetdiagnose mit `curl -I https://www.iana.org/` geprüft.
- [ ] Teständerung committet und gepusht.
- [ ] Backup-Strategie festgelegt.
