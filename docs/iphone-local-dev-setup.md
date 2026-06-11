# Vollständiges Setup: lokale Entwicklerumgebung auf dem iPhone

Stand: 2026-06-11

Diese Anleitung richtet eine praxistaugliche Entwicklerumgebung direkt auf dem iPhone ein. Sie priorisiert lokale Arbeit, benennt aber klar, wo iOS Grenzen setzt und wann ein Remote-Host sinnvoller ist. Zusätzlich enthält dieses Repository eine statische Plattform (`index.html`), die ohne Build-Schritt deployt werden kann, Setup-Pläne autonom erzeugt und problematische Stellen wie Scan- oder Bildartefakte sichtbar prüft.

Die App-Empfehlungen wurden am 2026-06-11 gegen die offiziellen Projekt- und App-Seiten gegengeprüft. Trotzdem solltest du vor dem Kauf kostenpflichtiger Apps im App Store prüfen, ob Preis, Funktionsumfang und Systemanforderungen für dein iPhone noch passen.

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

### 3.1 Welches Profil soll ich wählen?

| Profil | Installiere | Geeignet für | Nicht ideal für |
| --- | --- | --- | --- |
| Minimal lokal | Working Copy, a-Shell, Textastic oder Code App | Markdown, kleine Skripte, Konfigurationen, Git-Patches | Große Build-Systeme |
| Linux-nah lokal | Working Copy, iSH, Editor | Alpine-Pakete, klassische Shell-Werkzeuge, SSH/Git im Terminal | Performance-kritische Builds |
| Hybrid professionell | Working Copy, Editor, Blink Shell, Remote-Server | Web-Apps, Docker, Datenbanken, lange Tests, CI-nahe Arbeit | Offline-Arbeit ohne Server |

Wenn du unsicher bist, starte mit **Minimal lokal**. Ergänze iSH erst, wenn du wirklich `apk`-Pakete oder eine Linux-ähnliche Shell brauchst. Ergänze Blink/Remote erst, wenn lokale Builds zu langsam oder instabil werden.

## 4. 15-Minuten-Schnellstart

Dieser Schnellstart erzeugt einen funktionierenden End-to-End-Workflow, bevor du dich mit allen Details beschäftigst. Wenn du zuerst die autonome Plattform nutzen willst, öffne `index.html`, wähle ein Profil und kopiere den generierten Direct-Inject-Block.

1. Installiere Working Copy, a-Shell und Textastic oder Code App.
2. Öffne Working Copy und klone ein kleines Repository oder lege ein Test-Repository an.
3. Stelle in Working Copy deinen Git-Namen und deine Commit-E-Mail ein.
4. Öffne das Repository im Editor über die Dateien-App bzw. über die Working-Copy-Integration.
5. Erstelle oder ändere `README.md`.
6. Öffne a-Shell und teste die lokalen Werkzeuge:

```sh
pwd
python3 --version
node --version
```

7. Wechsle zurück zu Working Copy, prüfe den Diff, committe und pushe.
8. Wenn Schritt 7 klappt, ist der mobile Grundworkflow eingerichtet.

## 5. Basisinstallation auf dem iPhone

### 5.1 iOS vorbereiten

1. Aktualisiere iOS über **Einstellungen → Allgemein → Softwareupdate**.
2. Aktiviere iCloud Drive, wenn du Dokumente zwischen Apps sichern möchtest.
3. Installiere eine Passwortverwaltung mit SSH-Key-/Token-Ablage, z. B. iCloud-Schlüsselbund, 1Password oder Bitwarden.
4. Verwende nach Möglichkeit eine externe Tastatur. Terminal- und Git-Arbeit wird dadurch deutlich schneller.

### 5.2 Apps installieren

Installiere mindestens:

- Working Copy
- a-Shell
- Textastic oder Code App

Optional:

- iSH, wenn du eine Linux-ähnliche Umgebung möchtest.
- Blink Shell, wenn du regelmäßig per SSH/Mosh auf Server gehst.

## 6. Verzeichnisstruktur

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

### 6.1 Lokale Projektvorlage

Für neue lokale Experimente kannst du in a-Shell folgende Vorlage verwenden:

```sh
mkdir -p ~/Developer/{repos,scratch,exports,backups}
mkdir -p ~/Developer/scratch/iphone-dev-check
cd ~/Developer/scratch/iphone-dev-check
cat > README.md <<'MD'
# iPhone Dev Check

Dieses Projekt prüft, ob Editor, Terminal und Git-Workflow funktionieren.
MD
cat > hello.py <<'PY'
print("iPhone-Setup funktioniert")
PY
python3 hello.py
```

Wenn du später ein echtes Git-Repository daraus machen willst, importiere den Ordner in Working Copy oder erstelle das Repository direkt dort.

## 7. Git mit Working Copy einrichten

### 7.1 Konto verbinden

1. Öffne Working Copy.
2. Verbinde GitHub, GitLab, Bitbucket oder deinen eigenen Git-Server.
3. Richte Authentifizierung über OAuth oder Personal Access Token ein.
4. Klone dein Repository.

### 7.2 Git-Identität setzen

Setze in Working Copy pro Repository oder global:

```text
Name: Dein Name
Email: deine-commit-email@beispiel.invalid
```

Wenn du GitHub nutzt, verwende bei Bedarf die GitHub-`noreply`-Adresse, damit deine private E-Mail verborgen bleibt.

### 7.3 Standard-Workflow

1. `Pull` oder `Fetch` ausführen.
2. Branch erstellen, z. B. `feature/iphone-setup`.
3. Dateien im Editor bearbeiten.
4. Zurück in Working Copy Änderungen prüfen.
5. Sinnvolle Commit-Nachricht schreiben.
6. Push ausführen.
7. Pull Request im Browser oder über deine Git-Plattform öffnen.

### 7.4 Abnahmeprüfung für Git

Vor dem ersten echten Feature solltest du einmal bewusst einen ungefährlichen Test-Commit durchführen:

1. Erstelle einen Branch wie `test/iphone-workflow`.
2. Ändere nur eine Markdown-Datei.
3. Prüfe in Working Copy den vollständigen Diff.
4. Committe mit einer klaren Nachricht, z. B. `Test iPhone Git workflow`.
5. Pushe den Branch und öffne ihn auf deiner Git-Plattform.
6. Lösche den Test-Branch wieder, wenn alles funktioniert.

Diese Prüfung stellt sicher, dass Authentifizierung, Dateifreigabe, Editor und Remote-Rechte zusammenpassen.

## 8. a-Shell einrichten

### 8.1 Erste Prüfung

Öffne a-Shell und führe aus:

```sh
pwd
help -l
python3 --version
node --version
clang --version
```

Nicht jedes Projekt braucht alle Tools. Prüfe zuerst, was lokal schon vorhanden ist.

### 8.2 Arbeitsordner öffnen

In a-Shell kannst du über die iOS-Dateiauswahl Projektordner verfügbar machen. Lege anschließend einen Arbeitsordner an:

```sh
mkdir -p ~/Developer/scratch
cd ~/Developer/scratch
```

### 8.3 Nützliche Shell-Konfiguration

Erstelle eine kleine Profil-Datei:

```sh
cat > ~/.profile <<'PROFILE'
export EDITOR=vim
alias ll='ls -la'
alias py='python3'
alias serve='python3 -m http.server 8000'
alias gs='git status'
PROFILE
```

Lade sie neu:

```sh
. ~/.profile
```

### 8.4 Python-Projekt testen

```sh
mkdir -p ~/Developer/scratch/hello-python
cd ~/Developer/scratch/hello-python
cat > hello.py <<'PY'
print("Hallo vom iPhone")
PY
python3 hello.py
```

### 8.5 JavaScript-Projekt testen

```sh
mkdir -p ~/Developer/scratch/hello-js
cd ~/Developer/scratch/hello-js
cat > hello.js <<'JS'
console.log("Hallo vom iPhone")
JS
node hello.js
```

Wenn `node` in deiner Installation nicht verfügbar ist, nutze Code App für JavaScript-Experimente oder weiche auf iSH/Remote aus.

### 8.6 Lokale Grenzen früh testen

Prüfe bei jedem neuen Projekt zuerst die kleinsten sinnvollen Befehle, bevor du viel Zeit in Abhängigkeiten investierst:

```sh
python3 -m py_compile hello.py
node --check hello.js
```

Wenn schon diese Basistests fehlen oder fehlschlagen, entscheide früh zwischen anderer App, iSH oder Remote-Host.

## 9. iSH einrichten

Nutze iSH, wenn du eine Alpine-Linux-ähnliche Umgebung brauchst.

### 9.1 Pakete aktualisieren

```sh
apk update
apk upgrade
```

### 9.2 Basiswerkzeuge installieren

```sh
apk add git openssh curl wget nano vim python3 py3-pip nodejs npm make
```

Je nach iSH-/Alpine-Stand können Paketnamen oder Versionen abweichen. Wenn ein Paket nicht gefunden wird, suche mit:

```sh
apk search <name>
```

### 9.3 Git konfigurieren

```sh
git config --global user.name "Dein Name"
git config --global user.email "deine-commit-email@beispiel.invalid"
git config --global init.defaultBranch main
git config --global pull.rebase false
```

### 9.4 SSH-Key erzeugen

```sh
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 -C "iphone-dev"
cat ~/.ssh/id_ed25519.pub
```

Kopiere den öffentlichen Schlüssel in GitHub/GitLab/Bitbucket oder auf deinen Server. Teile niemals `id_ed25519`, sondern nur `id_ed25519.pub`.

### 9.5 SSH-Verbindung testen

Für GitHub:

```sh
ssh -T git@github.com
```

Für einen eigenen Server:

```sh
ssh user@server.invalid
```

## 10. Editor-Workflow

### 10.1 Textastic mit Working Copy

1. Klone das Repository in Working Copy.
2. Öffne Textastic.
3. Füge den Working-Copy-Repository-Ordner als externen Ordner hinzu.
4. Bearbeite Dateien in Textastic.
5. Wechsle zu Working Copy, prüfe den Diff und committe.

### 10.2 Code App als All-in-one-Option

Code App eignet sich, wenn du Editor, Terminal, Git und einfache Paketmanager in einer App bevorzugst.

Empfohlener Start:

1. Neues lokales Projekt anlegen.
2. Eine `README.md` und eine kleine Testdatei erstellen.
3. Git aktivieren oder mit einem bestehenden Repository verbinden.
4. `pip`/`npm` nur für kleine Projekte nutzen und große Abhängigkeiten vermeiden.

## 11. Lokale Web-Entwicklung

Für statische Seiten oder kleine Python-Server:

```sh
cd /pfad/zu/deinem/projekt
python3 -m http.server 8000
```

Öffne anschließend im iPhone-Browser:

```text
http://localhost:8000
```

Hinweise:

- iOS kann lokale Server stoppen, wenn die App im Hintergrund ist.
- Für Frameworks mit Watch-Modus, Hot Reload oder langen Builds ist ein Remote-Server oft stabiler.

## 12. Remote-Ergänzung für große Projekte

Wenn lokale Grenzen erreicht sind, nutze das iPhone als Client und baue auf einem Remote-System:

- Mac mini, MacBook, Linux-Server, VPS oder Homelab.
- SSH/Mosh mit Blink Shell oder a-Shell.
- Git bleibt die Synchronisationsquelle.
- Builds, Tests, Docker und Datenbanken laufen remote.

Beispiel-Workflow:

```sh
ssh dev@server.invalid
cd ~/projects/mein-projekt
git pull
npm test
```

### 12.1 Empfohlenes Remote-Grundsetup

Auf dem Remote-Host ist diese Basis für viele Web- und Skriptprojekte ausreichend:

```sh
mkdir -p ~/projects
cd ~/projects
git clone git@github.com:dein-name/dein-repo.git
cd dein-repo
```

Danach kannst du vom iPhone per SSH arbeiten, während Git weiterhin die gemeinsame Wahrheit zwischen iPhone, Server und Git-Plattform bleibt.

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

## 19. Finale Abnahme

Das Setup gilt als vollständig, wenn diese Punkte erledigt sind:

- Du kannst ein Repository in Working Copy klonen.
- Du kannst dieselben Dateien in deinem Editor öffnen und speichern.
- Du kannst in a-Shell oder iSH mindestens ein lokales Testskript ausführen.
- Du kannst einen Branch erstellen, committen und pushen.
- Du weißt, ob dein aktuelles Projekt lokal bleibt oder für Builds/Tests einen Remote-Host braucht.
- Es gibt eine Backup-Strategie für nicht gepushte Arbeit.
- Die statische Plattform startet ohne Build-Schritt und der QA-Scanner meldet keine ungeprüften Artefakte.

Damit hast du einen vollständigen, mobilen lokalen Entwicklungsworkflow auf dem iPhone.
