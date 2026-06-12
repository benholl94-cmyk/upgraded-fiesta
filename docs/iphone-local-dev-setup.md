# Vollständiges Setup: lokale Entwicklerumgebung auf dem iPhone

Stand: 2026-06-12

Diese Anleitung richtet eine praxistaugliche Entwicklerumgebung direkt auf dem iPhone ein. Sie priorisiert lokale Arbeit, benennt aber klar, wo iOS Grenzen setzt und wann ein Remote-Host sinnvoller ist.

## 1. Zielbild

Nach dem Setup kannst du auf dem iPhone:

- Git-Repositories klonen, bearbeiten, committen, branchen und pushen.
- Python-, JavaScript-, Shell- und Markdown-Dateien lokal bearbeiten.
- Kleine Skripte lokal ausführen.
- SSH-Schlüssel verwalten und dich mit Servern verbinden.
- Projektdateien zwischen Editor, Terminal und Git-Client austauschen.
- Backups und Wiederherstellung sauber planen.

## 2. Realistische Grenzen von iOS

Ein iPhone ersetzt keinen vollwertigen Linux- oder macOS-Rechner für alle Projekte:

- Hintergrundprozesse werden durch iOS begrenzt; lange Builds oder lokale Server können beendet werden.
- Container, Docker, Kernel-Module und viele native Toolchains laufen nicht lokal wie auf Linux.
- App-Sandboxing trennt Dateisysteme; App-übergreifendes Arbeiten erfolgt über Dateien-App, Dokumentanbieter oder explizite Freigaben.
- Große Node-, Rust-, Java-, Swift- oder C/C++-Builds sind meist besser auf einem Remote-Server, Mac mini, Codespace oder CI-System aufgehoben.

Deshalb nutzt dieses Setup eine lokale Basis und ergänzt optional Remote-Zugriff.

## 3. Empfohlene App-Rollen

| Rolle | Empfehlung | Zweck | Quelle |
| --- | --- | --- | --- |
| Git | Working Copy | Repositories, Branches, Commits, Push/Pull, Konfliktlösung | https://workingcopyapp.com/ |
| Lokales Terminal | a-Shell | Lokale Unix-Befehle, Python, JavaScript, C/C++, `curl`, `vim`, Dateiwerkzeuge | https://apps.apple.com/us/app/a-shell/id1473805438 |
| Linux-ähnliche Shell | iSH | Alpine-Linux-Umgebung mit `apk`-Paketen | https://github.com/ish-app |
| Code-Editor | Textastic | Starker iPhone/iPad-Code-Editor, externe Working-Copy-Ordner, SFTP/SSH | https://www.textasticapp.com/ |
| All-in-one-Editor | Code App | Monaco-basierter Editor, lokale Dateien, Terminal, Git, `pip`/`npm` | https://apps.apple.com/us/app/code-app/id1512938504 |
| Remote-Terminal optional | Blink Shell | SSH/Mosh für stabile Remote-Sessions | https://blink.sh/ |

Du musst nicht alle Apps installieren. Für ein schlankes Setup reichen Working Copy, a-Shell und ein Editor.

## 4. Basisinstallation auf dem iPhone

### 4.1 iOS vorbereiten

1. Aktualisiere iOS über **Einstellungen → Allgemein → Softwareupdate**.
2. Aktiviere iCloud Drive, wenn du Dokumente zwischen Apps sichern möchtest.
3. Installiere eine Passwortverwaltung mit SSH-Key-/Token-Ablage, z. B. iCloud-Schlüsselbund, 1Password oder Bitwarden.
4. Verwende nach Möglichkeit eine externe Tastatur. Terminal- und Git-Arbeit wird dadurch deutlich schneller.

### 4.2 Apps installieren

Installiere mindestens:

- Working Copy
- a-Shell
- Textastic oder Code App

Optional:

- iSH, wenn du eine Linux-ähnliche Umgebung möchtest.
- Blink Shell, wenn du regelmäßig per SSH/Mosh auf Server gehst.

## 5. Verzeichnisstruktur

Lege in der Dateien-App unter **Auf meinem iPhone** eine klare Struktur an:

```text
Developer/
  repos/
  scratch/
  keys/
  exports/
  backups/
```

Empfehlung:

- `repos/`: aktive Git-Repositories.
- `scratch/`: Experimente und Einmal-Skripte.
- `keys/`: nur wenn deine App diesen Speicherort verschlüsselt oder sicher anbietet; private Keys nicht unverschlüsselt herumkopieren.
- `exports/`: ZIPs, Logs, Artefakte.
- `backups/`: manuelle Sicherungen wichtiger Dateien.

Working Copy verwaltet Repositories intern sehr gut. Öffne sie im Editor möglichst als externe Ordner, statt dieselben Dateien mehrfach zu kopieren.

## 6. Git mit Working Copy einrichten

### 6.1 Konto verbinden

1. Öffne Working Copy.
2. Verbinde GitHub, GitLab, Bitbucket oder deinen eigenen Git-Server.
3. Richte Authentifizierung über OAuth oder Personal Access Token ein.
4. Klone dein Repository.

### 6.2 Git-Identität setzen

Setze in Working Copy pro Repository oder global:

```text
Name: Dein Name
Email: deine-commit-email@example.com
```

Wenn du GitHub nutzt, verwende bei Bedarf die GitHub-`noreply`-Adresse, damit deine private E-Mail verborgen bleibt.

### 6.3 Standard-Workflow

1. `Pull` oder `Fetch` ausführen.
2. Branch erstellen, z. B. `feature/iphone-setup`.
3. Dateien im Editor bearbeiten.
4. Zurück in Working Copy Änderungen prüfen.
5. Sinnvolle Commit-Nachricht schreiben.
6. Push ausführen.
7. Pull Request im Browser oder über deine Git-Plattform öffnen.

## 7. a-Shell einrichten

### 7.1 Erste Prüfung

Öffne a-Shell und führe aus:

```sh
pwd
help -l
python3 --version
node --version
clang --version
```

Nicht jedes Projekt braucht alle Tools. Prüfe zuerst, was lokal schon vorhanden ist.

### 7.2 Arbeitsordner öffnen

In a-Shell kannst du über die iOS-Dateiauswahl Projektordner verfügbar machen. Lege anschließend einen Arbeitsordner an:

```sh
mkdir -p ~/Developer/scratch
cd ~/Developer/scratch
```

### 7.3 Nützliche Shell-Konfiguration

Erstelle eine kleine Profil-Datei:

```sh
cat > ~/.profile <<'PROFILE'
export EDITOR=vim
alias ll='ls -la'
alias py='python3'
alias serve='python3 -m http.server 8000'
PROFILE
```

Lade sie neu:

```sh
. ~/.profile
```

### 7.4 Python-Projekt testen

```sh
mkdir -p ~/Developer/scratch/hello-python
cd ~/Developer/scratch/hello-python
cat > hello.py <<'PY'
print("Hallo vom iPhone")
PY
python3 hello.py
```

### 7.5 JavaScript-Projekt testen

```sh
mkdir -p ~/Developer/scratch/hello-js
cd ~/Developer/scratch/hello-js
cat > hello.js <<'JS'
console.log("Hallo vom iPhone")
JS
node hello.js
```

Wenn `node` in deiner Installation nicht verfügbar ist, nutze Code App für JavaScript-Experimente oder weiche auf iSH/Remote aus.

## 8. iSH einrichten

Nutze iSH, wenn du eine Alpine-Linux-ähnliche Umgebung brauchst.

### 8.1 Pakete aktualisieren

```sh
apk update
apk upgrade
```

### 8.2 Basiswerkzeuge installieren

```sh
apk add git openssh curl wget nano vim python3 py3-pip nodejs npm make
```

Je nach iSH-/Alpine-Stand können Paketnamen oder Versionen abweichen. Wenn ein Paket nicht gefunden wird, suche mit:

```sh
apk search <name>
```

### 8.3 Git konfigurieren

```sh
git config --global user.name "Dein Name"
git config --global user.email "deine-commit-email@example.com"
git config --global init.defaultBranch main
git config --global pull.rebase false
```

### 8.4 SSH-Key erzeugen

```sh
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 -C "iphone-dev"
cat ~/.ssh/id_ed25519.pub
```

Kopiere den öffentlichen Schlüssel in GitHub/GitLab/Bitbucket oder auf deinen Server. Teile niemals `id_ed25519`, sondern nur `id_ed25519.pub`.

### 8.5 SSH-Verbindung testen

Für GitHub:

```sh
ssh -T git@github.com
```

Für einen eigenen Server:

```sh
ssh user@example.com
```

## 9. Editor-Workflow

### 9.1 Textastic mit Working Copy

1. Klone das Repository in Working Copy.
2. Öffne Textastic.
3. Füge den Working-Copy-Repository-Ordner als externen Ordner hinzu.
4. Bearbeite Dateien in Textastic.
5. Wechsle zu Working Copy, prüfe den Diff und committe.

### 9.2 Code App als All-in-one-Option

Code App eignet sich, wenn du Editor, Terminal, Git und einfache Paketmanager in einer App bevorzugst.

Empfohlener Start:

1. Neues lokales Projekt anlegen.
2. Eine `README.md` und eine kleine Testdatei erstellen.
3. Git aktivieren oder mit einem bestehenden Repository verbinden.
4. `pip`/`npm` nur für kleine Projekte nutzen und große Abhängigkeiten vermeiden.

## 10. Lokale Web-Entwicklung

### 10.1 Sinnvolle Localhost-Variablen

Lege für lokale Webprojekte wiederverwendbare Umgebungsvariablen an. So musst du Ports, Hostnamen und Proxy-Ausnahmen nicht in jedem Projekt neu tippen.

Für a-Shell oder iSH:

```sh
cat >> ~/.profile <<'PROFILE'
# Lokale Entwicklung
export DEV_HOST=127.0.0.1
export DEV_BIND=127.0.0.1
export DEV_PORT=8000
export DEV_ALT_PORT=3000
export DEV_URL="http://${DEV_HOST}:${DEV_PORT}"
export LOCALHOST_URL="$DEV_URL"

# Proxy-Ausnahmen: lokale Ziele sollen nie über Firmen-/VPN-Proxys laufen.
export NO_PROXY="localhost,127.0.0.1,::1,*.local"
export no_proxy="$NO_PROXY"

# Häufig genutzte Tool-Defaults
export PYTHONUNBUFFERED=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export npm_config_audit=false
export npm_config_fund=false
PROFILE
. ~/.profile
```

Wenn du ein Projekt aus dem lokalen Netzwerk erreichen musst, ändere bewusst nur die Bind-Adresse:

```sh
export DEV_BIND=0.0.0.0
python3 -m http.server "$DEV_PORT" --bind "$DEV_BIND"
```

Nutze `127.0.0.1` für private Tests auf demselben iPhone. Nutze `0.0.0.0` nur, wenn andere Geräte im gleichen Netzwerk zugreifen sollen und du dem Netzwerk vertraust.

Typische Variablen:

| Variable | Beispiel | Zweck |
| --- | --- | --- |
| `DEV_HOST` | `127.0.0.1` | Hostname oder IP, die du im Browser öffnest. |
| `DEV_BIND` | `127.0.0.1` oder `0.0.0.0` | Adresse, auf der ein Server lauscht. |
| `DEV_PORT` | `8000` | Standardport für kleine lokale Server. |
| `DEV_ALT_PORT` | `3000` | Alternativport für Node-/Frontend-Projekte. |
| `DEV_URL` | `http://127.0.0.1:8000` | Kopierbare Basis-URL. |
| `NO_PROXY`/`no_proxy` | `localhost,127.0.0.1,::1,*.local` | Verhindert Proxy-Nutzung für lokale Adressen. |
| `HTTP_PROXY`/`HTTPS_PROXY` | `http://proxy.example:8080` | Nur setzen, wenn dein Netzwerk zwingend einen Proxy verlangt. |
| `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` | `/path/ca.pem` | Eigene CA-Zertifikate für Python/Requests. |
| `CURL_CA_BUNDLE`/`GIT_SSL_CAINFO` | `/path/ca.pem` | Eigene CA-Zertifikate für curl/Git. |

### 10.2 Lokalen Server starten

Für statische Seiten oder kleine Python-Server:

```sh
cd /pfad/zu/deinem/projekt
python3 -m http.server "$DEV_PORT" --bind "$DEV_BIND"
```

Öffne anschließend im iPhone-Browser:

```text
http://localhost:8000
http://127.0.0.1:8000
```

Hinweise:

- iOS kann lokale Server stoppen, wenn die App im Hintergrund ist.
- Für Frameworks mit Watch-Modus, Hot Reload oder langen Builds ist ein Remote-Server oft stabiler.
- Wenn `localhost` nicht funktioniert, teste `http://127.0.0.1:8000` und prüfe, ob der Server wirklich noch läuft.
- Wenn ein Port belegt ist, erhöhe `DEV_PORT`, z. B. auf `8001`, `8080` oder `3000`.

### 10.3 Netzwerkdiagnose für Localhost

```sh
printf '%s\n' "$DEV_URL"
curl -I "$DEV_URL"
python3 -m http.server "$DEV_PORT" --bind "$DEV_BIND"
```

Fehlersuche:

- `Connection refused`: Der Server läuft nicht oder lauscht auf einem anderen Port.
- `Timeout`: Netzwerk, VPN, Firewall oder iOS-Hintergrundverhalten blockiert den Zugriff.
- `404`: Der Server läuft, aber der Pfad oder Arbeitsordner ist falsch.
- `SSL certificate problem`: Du nutzt HTTPS mit einem selbstsignierten Zertifikat; verwende lokal zunächst HTTP oder installiere bewusst eine passende lokale CA.

## 11. Internet-Grundlagen und Online-Arbeit

Das Internet ist kein einzelner Dienst, sondern ein Verbund aus Netzen, Protokollen, Servern, Clients und Vertrauenssystemen. Für mobile Entwicklung reichen meist diese Bausteine:

- **IP-Adresse**: numerische Adresse eines Geräts oder Servers, z. B. `127.0.0.1` lokal oder eine öffentliche Server-IP.
- **DNS**: übersetzt Namen wie `example.com` in IP-Adressen.
- **HTTP/HTTPS**: Protokoll für Webseiten und APIs; HTTPS verschlüsselt und prüft Zertifikate.
- **URL**: vollständige Adresse wie `https://example.com/docs?lang=de`.
- **Port**: Dienstnummer wie `80` für HTTP, `443` für HTTPS, `22` für SSH oder `8000` für lokale Entwicklung.
- **TLS-Zertifikat**: beweist, dass du mit dem richtigen HTTPS-Server sprichst.
- **Cookies, Tokens und Sessions**: merken Anmeldung oder API-Zugriff; behandle sie wie Passwörter.
- **API**: maschinenlesbare Schnittstelle, oft JSON über HTTP.
- **CDN und Cache**: beschleunigen Inhalte, können aber veraltete Antworten liefern.

### 11.1 Verbindung prüfen

```sh
curl -I https://example.com
python3 - <<'PY'
import socket
print(socket.gethostbyname('example.com'))
PY
```

Wenn `curl` scheitert:

1. Prüfe WLAN/Mobilfunk und VPN.
2. Öffne dieselbe URL im Browser.
3. Teste DNS mit einem einfachen Host wie `example.com`.
4. Prüfe Datum/Uhrzeit; falsche Uhrzeiten brechen HTTPS-Zertifikatsprüfungen.
5. Deaktiviere testweise Proxy-Variablen, wenn lokale oder öffentliche Ziele falsch geroutet werden.

### 11.2 Sicher herunterladen

```sh
curl -L -o datei.zip https://example.com/datei.zip
python3 -m zipfile -t datei.zip
```

Gute Praxis:

- Lade Tools möglichst von offiziellen Projektseiten, App Stores oder bekannten Paketquellen.
- Prüfe Checksums oder Signaturen, wenn ein Projekt sie anbietet.
- Führe unbekannte Shell-Skripte nicht blind mit `curl ... | sh` aus; erst speichern, lesen, dann ausführen.
- Trenne private Tokens, SSH-Keys und `.env`-Dateien strikt von öffentlichen Repositories.

### 11.3 APIs nutzen

Ein minimaler API-Test mit `curl`:

```sh
curl -s https://api.github.com/repos/git/git | python3 -m json.tool | head
```

Mit Token, ohne ihn in die Shell-History zu schreiben:

```sh
read -r API_TOKEN
curl -H "Authorization: Bearer $API_TOKEN" https://api.example.com/me
unset API_TOKEN
```

API-Regeln:

- Lies Statuscodes: `200` Erfolg, `201` erstellt, `301/302` Weiterleitung, `400` fehlerhafte Anfrage, `401` nicht angemeldet, `403` keine Rechte oder Rate-Limit, `404` nicht gefunden, `429` zu viele Anfragen, `500` Serverfehler.
- Verwende `GET` zum Lesen, `POST` zum Erstellen, `PUT/PATCH` zum Ändern und `DELETE` zum Löschen.
- Speichere Secrets in Passwortmanager, Keychain oder App-spezifischen Secret-Stores, nicht in Git.
- Baue Retries mit Wartezeit ein, aber respektiere Rate-Limits.

### 11.4 Web-Recherche und Quellenbewertung

Beim Arbeiten im Browser:

- Bevorzuge Primärquellen: offizielle Dokumentation, Spezifikationen, Release Notes, Maintainer-Repositories.
- Prüfe Datum, Version und Plattform; iOS-, App- und Paketmanager-Verhalten ändert sich.
- Vergleiche mindestens zwei Quellen, wenn eine Anleitung tief in Sicherheit, Geld, Medizin, Recht oder Infrastruktur eingreift.
- Kopiere Fehlermeldungen exakt, aber entferne Tokens, private URLs und personenbezogene Daten.
- Notiere funktionierende Befehle in `README.md`, `docs/` oder einem Projekt-Wiki.

### 11.5 Privatsphäre und Sicherheit im Internet

- Verwende unterschiedliche Passwörter und aktiviere 2FA/MFA.
- Bevorzuge Passkeys oder Hardware-Keys, wenn der Dienst sie unterstützt.
- Gib Apps nur notwendige Berechtigungen.
- Prüfe vor OAuth-Logins, welche Rechte eine App anfordert.
- Nutze VPN nur, wenn du dem Anbieter vertraust; ein VPN ersetzt kein HTTPS.
- Öffne keine unbekannten Profile, Zertifikate oder Konfigurationsdateien auf iOS, wenn du die Quelle nicht sicher kennst.

## 12. Remote-Ergänzung für große Projekte

Wenn lokale Grenzen erreicht sind, nutze das iPhone als Client und baue auf einem Remote-System:

- Mac mini, MacBook, Linux-Server, VPS oder Homelab.
- SSH/Mosh mit Blink Shell oder a-Shell.
- Git bleibt die Synchronisationsquelle.
- Builds, Tests, Docker und Datenbanken laufen remote.

Beispiel-Workflow:

```sh
ssh dev@example.com
cd ~/projects/mein-projekt
git pull
npm test
```

## 13. Sicherheit

- Aktiviere Face ID/Code und Geräteverschlüsselung.
- Verwende pro Dienst separate Tokens mit minimalen Rechten.
- Bevorzuge SSH-Keys mit Passphrase.
- Speichere Recovery-Codes außerhalb des iPhones.
- Entferne alte Tokens und Keys regelmäßig.
- Prüfe vor jedem Push den Diff.

## 14. Backup-Strategie

Mindestens eine dieser Strategien sollte aktiv sein:

1. Remote-Git-Repository als primäre Sicherung.
2. iCloud-Backup des iPhones.
3. Manuelle ZIP-Exports wichtiger Projekte nach `Developer/backups/`.
4. Regelmäßige Pushes nach kleinen Arbeitsschritten.

Für aktive Projekte gilt: Nicht committete Änderungen sind nicht zuverlässig gesichert.

## 15. Wartung

Wöchentlich:

```sh
git status
git fetch --all
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

## 16. Fehlerbehebung

### Git-Push schlägt fehl

- Prüfe Internetverbindung und VPN.
- Prüfe Token-/SSH-Key-Rechte.
- Führe zuerst Fetch/Pull aus.
- Löse Konflikte in Working Copy oder im Editor.

### Editor sieht Repository-Dateien nicht

- Repository-Ordner erneut über die Dateien-App freigeben.
- In Working Copy prüfen, ob der Ordner als externer Ordner verfügbar ist.
- Keine parallelen Kopien desselben Repositories bearbeiten.

### Paketinstallation in iSH schlägt fehl

```sh
apk update
apk search <paketname>
cat /etc/apk/repositories
```

Wenn die Repository-Konfiguration veraltet ist, verwende die von iSH empfohlene Paketquelle oder installiere iSH neu und migriere nur deine Projektdaten.

### Lokaler Server ist nicht erreichbar

- Prüfe, ob die Terminal-App im Vordergrund läuft.
- Prüfe Port und URL, z. B. `http://localhost:8000`.
- Starte den Server neu.

## 17. Minimal-Checkliste

- [ ] iOS aktualisiert.
- [ ] Working Copy installiert und Git-Konto verbunden.
- [ ] Editor installiert und mit Working Copy getestet.
- [ ] a-Shell installiert und `python3 --version` geprüft.
- [ ] Optional iSH installiert und `apk update` geprüft.
- [ ] SSH-Key oder Token eingerichtet.
- [ ] Test-Repository geklont.
- [ ] Localhost-Variablen gesetzt und `http://127.0.0.1:8000` getestet.
- [ ] Internet-/API-Grundlagen mit `curl -I https://example.com` geprüft.
- [ ] Teständerung committet und gepusht.
- [ ] Backup-Strategie festgelegt.

## 18. Empfohlene Startkonfiguration

Wenn du sofort loslegen willst:

1. Installiere Working Copy, Textastic und a-Shell.
2. Klone dein wichtigstes Repository in Working Copy.
3. Öffne es in Textastic als externen Ordner.
4. Teste in a-Shell:

```sh
python3 --version
node --version
```

5. Ändere eine Markdown-Datei.
6. Prüfe den Diff in Working Copy.
7. Committe mit einer kleinen, klaren Nachricht.
8. Pushe den Branch.

Damit hast du einen vollständigen, mobilen lokalen Entwicklungsworkflow auf dem iPhone.
