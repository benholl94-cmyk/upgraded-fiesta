# HUGIN · Companion-HUD × OpenClaw-Bridge

> **Welt-einzigartiges Anwendungsprofil:** Der transparente KI-Begleiter über dem
> iOS-Homescreen-Wallpaper, ferngesteuert über einen persönlichen Werkzeug-Agenten
> auf einem Host — eine Smartphone-PWA, die direkt mit dem reproduzierbaren System
> dieses Repos verbunden ist und über Race-Mode-Terminal gleichzeitig mehrere
> AI-Anbieter befragt.

**Status:** Dokumentation (kein Auto-Build, kein Auto-Push). Verfasst 2026-07-28
auf Grundlage der im Repo gemessenen Funktionalität und der Workspace-Verfassung
(`/workspaces/upgraded-fiesta/.claude/persona/constitution.json`).
**Beads:** Initialisierung der Beads-Datenbank derzeit blockiert
(`issue_prefix` config fehlt im laufenden Dolt-Server) — Eintrag wird nachgeholt,
sobald der Master den bestehenden Systemzustand aufgelöst hat.

---

## 1 · Vision und Einzigartigkeit

HUGIN ist im Repo bereits Realität. Was hier beschrieben wird, ist keine neue
Software, sondern das **Anwendungsprofil**, in dem die vorhandenen Bausteine
gemeinsam etwas ergeben, das kein einzelnes anderes Werkzeug leistet:

| Baustein (im Repo gemessen) | Welt-Einzigartigkeits-Beitrag |
|---|---|
| `hugin/hugin.html` (117 KB, single file) + `hugin/sw.js` + `hugin/manifest.json` | PWA, die als transparenter HUD über dem iOS-Homescreen liegt. `hugin.html:161` lässt das Wallpaper durch die Scan-Line-Maske bluten; `hugin.html:652` zeigt das nur vor Installation sichtbare Overlay-Hint. Kein anderer AI-Chat macht das. |
| `PROVIDERS` mit 24 registrierten Providern (`hugin.html:930 ff.`) + `TASK_AFFINITY`-Routing (`hugin.html:1714 ff.`) | Selbstlernender Provider-Router mit EMA-Scores. Reasoning geht zu DeepSeek-R1, Code zu Featherless, Multilingual zu HF-Router — automatisch. |
| `TERMSHELL` Multi-Provider Parallel Shell (`hugin.html:2325 ff.`) mit `race`/`run`/`best`/`tasks` (`hugin.html:2656 ff.`) | Eine Frage geht parallel an **alle** bereiten Provider; jede Antwort erscheint simultan im eigenen Pane; der schnellste gewinnt (`Promise.any` in `cmdRace`). Kein anderes Consumer-AI-Tool zeigt live den direkten Anbietervergleich. |
| `ReflexKernel` (`hugin.html:1381 ff.`) — Calculator, Unit-Converter, Date/Time, Encoding, FNV-1a | Wenn alles ausfällt, antwortet HUGIN trotzdem — offline, ohne Key, ohne Netz. |
| WebGPU-Llama (`hugin.html:1317 ff.`, `hugin.html:1361`) | Echtes Sprachmodell auf dem Gerät. Safari 26+ / iOS 26 / Chrome mit WebGPU. Nach erstem Laden dauerhaft offline. |
| FNV-1a-Siegel + Dual-Slot A/B (`hugin.html:764–810`) | Selbstheilende Schlüssel-Persistenz. Bei Korruption eines Slots restauriert der andere, dann wird der defekte Slot neu geschrieben. |
| SHA-256 Admin-Gate (`hugin.html:38 ff.`) mit `deny()`-Fail-Closed | Falsches Token → Lite-Version mit erhaltener PWA-Installierbarkeit. Manipulierter Storage wird gelöscht. |
| `hugin/hugin-openclaw-setup.sh` (POSIX, idempotent) | In 3 Schritten vom Host/VPS zum persönlichen Werkzeug-Agenten mit echtem Datei-/Web-/Speicher-/Cron-Zugriff — kostenlos via Cerebras free tier (1 M Token/Tag, kein Kreditkartenzwang). |
| `crates/hm-gateway` (Async-TCP-HTTP-Server, einziger Auth-Punkt) + 14 weitere Crates | Reproduzierbares System dahinter: Memory (FTS/Vector/Hybrid/Episodic), Channels (Telegram/Discord/Slack/WhatsApp), Tools (exec/browser/web/media), Cron, Sessions, Plugins, Vector-ANN. |

**Zusammen ergibt das:** Ein Smartphone-Werkzeug, das den Besitzer befähigt,
jede AI-Frage einmal zu stellen und die Antworten aller relevanten Modelle
gleichzeitig zu sehen — und das auch dann noch funktioniert, wenn die
Internetverbindung oder die Cloud ausfällt, der Provider streikt oder der
Schlüssel korrupt wird. Die Brücke zum reproduzierbaren System ist OpenClaw:
ein Agent, der auf dem Gerät des Owners läuft und Werkzeuge hat, die eine
reine Chat-PWA niemals haben kann.

---

## 2 · Architektur

```
   iPhone (PWA, HUD über Homescreen)
 ┌─────────────────────────────────────────────────────────────┐
 │  hugin.html                                                 │
 │  ├── Admin-Gate (SHA-256, fail-closed)                       │
 │  ├── HUD-Frame (Scan-Line-Maske + iOS-Wallpaper-Bleed)       │
 │  ├── Chat-Modus (Provider-Router, EMA-Lernen)                │
 │  ├── TermShell-Modus (race · run · best · tasks)             │
 │  ├── Reflex-Kern (offline: rechnen · umwandeln · encoden)    │
 │  ├── WebGPU-Llama (offline LLM)                              │
 │  ├── Cache (versiegelt, max 60, offline abrufbar)            │
 │  └── Service Worker (Netz zuerst, nur eigene GETs)           │
 └─────────────────────────────────────────────────────────────┘
                │ HTTPS / Bearer
                ▼
   Host / VPS (OpenClaw-Gateway, Port 18789)
 ┌─────────────────────────────────────────────────────────────┐
 │  OpenClaw                                                    │
 │  ├── Eigener Agent (Modell: cerebras/llama-4-scout, free)    │
 │  ├── Werkzeuge: File · Web · Memory · Cron                   │
 │  ├── Bearer-Token (chmod 600, idempotent)                    │
 │  └── Bind: loopback | lan | tailnet (Default: loopback)      │
 └─────────────────────────────────────────────────────────────┘
                │
                ▼
   Provider-Pool (Keyless + Keyed, parallel anfragbar)
 ┌─────────────────────────────────────────────────────────────┐
 │  Pollinations · HuggingFace · OpenRouter · Featherless ·    │
 │  Chutes · GitHub Models · Cerebras · Groq · Google ·        │
 │  Mistral · Together · Cohere · xAI · HF-Router · OpenClaw   │
 └─────────────────────────────────────────────────────────────┘
                │
                ▼ (Fallback)
   Offline-Schichten
 ┌─────────────────────────────────────────────────────────────┐
 │  WebGPU-Llama (lokal, dauerhaft nach erstem Modell-Download) │
 │  Reflex-Kern (JavaScript, keine Dependencies)                │
 └─────────────────────────────────────────────────────────────┘
```

### 2.1 Datenflüsse

| Fluss | Quelle → Ziel | Auth | Status |
|---|---|---|---|
| Chat | iPhone PWA → Pollinations (keyless) | n/a | aktiv |
| Chat | iPhone PWA → OpenAI (keyed) | Bearer-Key im Keyring | bei Key |
| Race | iPhone PWA → N Provider parallel | Bearer pro Provider | aktiv |
| Bridge | iPhone PWA → OpenClaw-Gateway | Bearer-Token (`~/.openclaw/hugin_gateway_token`) | optional |
| Cron | OpenClaw → OpenClaw Agent → OpenAI-Compat API | Bearer (Cerebras-Key) | optional |
| Storage | OpenClaw → lokal (`~/.openclaw/`) | Unix-Permissions 0700/0600 | lokal |

### 2.2 Was läuft wo

| Komponente | Host | Persistenz | Backup |
|---|---|---|---|
| PWA-Shell + Service Worker | iPhone | Cache (HUD-Frame) + iCloud-Backup | automatisch |
| Provider-Keys | iPhone (FNV-1a versiegelt, Dual-Slot A/B) | localStorage | iCloud-Backup |
| Admin-Token | iPhone (SHA-256 verglichen) | localStorage | iCloud-Backup |
| OpenClaw-Gateway-Token | Host (`~/.openclaw/hugin_gateway_token`) | chmod 600 | manuelle Strategie |
| Provider-Keys für OpenClaw-Agent | Host (`~/.openclaw/config`) | chmod 600 | manuelle Strategie |
| Antwort-Cache (versiegelt) | iPhone (max 60) | localStorage | iCloud-Backup |

---

## 3 · Installation in 3 Schritten

### Schritt 1 · OpenClaw auf einem Host/VPS einrichten

Voraussetzungen: Node.js (≥ 18) und ein erreichbarer Host/VPS, der laufen
kann, während das iPhone schläft. Für die kostenlose Stufe reicht ein
Cerebras-API-Key (1 M Token/Tag, kein Kreditkartenzwang) von
<https://cloud.cerebras.ai>.

```sh
# Auf dem Host (oder VPS, oder Raspberry-Pi mit always-on)
npm install -g openclaw

# Setup-Script ist idempotent — Token wird wiederverwendet,
# Modell und Werkzeuge werden nur gesetzt, wenn noch nicht da
CEREBRAS_API_KEY=csk-… sh hugin/hugin-openclaw-setup.sh
```

Das Script gibt am Ende die **Gateway-URL** und das **Bearer-Token** aus.
Standard-Bind ist `loopback`. Für iPhone-Zugriff sind drei Optionen
vorgesehen (in der Reihenfolge ihrer Sicherheit):

| Option | Bind | iPhone-Verbindung |
|---|---|---|
| **A — Tailscale** (empfohlen) | `tailnet` | `http://<tailnet-ip>:18789` direkt im selben VPN |
| **B — SSH-Tunnel** (fallback) | `loopback` | `ssh -N -L 18789:127.0.0.1:18789 user@host`, dann `http://127.0.0.1:18789` |
| **C — LAN** (nur Heimnetz) | `lan` | `http://<host-lan-ip>:18789`, gleiche Subnetz-Voraussetzung |

Klartext-URL mit Token ist nach Repo-Konvention
(`hugin.html:691` / `hugin.html:709`) **nur** für loopback / private Netze
/ VPN zulässig. Öffentliches Internet ohne TLS-Proxy ist ausgeschlossen.

### Schritt 2 · HUGIN-PWA auf dem iPhone installieren

1. HUGIN auf einen statisch erreichbaren Host deployen (GitHub Pages ist
   bereits Standard; siehe README-Hinweis: `benholl94-cmyk.github.io/upgraded-fiesta`).
2. Im iPhone-Safari öffnen: `https://<dein-host>/hugin.html`.
3. Teilen-Icon → **„Zum Home-Bildschirm"** → Name „HUGIN" bestätigen.
4. Icon auf dem Homescreen öffnen. Standalone-Modus aktiv.
5. Beim ersten Start zeigt die App unten den Hinweis `⬆ Zu Homescreen
   hinzufügen → Overlay aktiv` (`hugin.html:652`). Nach erfolgter Installation
   verschwindet der Hinweis automatisch (`isStandalone`-Check in
   `hugin.html:2308–2310`).

Die PWA läuft sofort **keyless**: Pollinations, HuggingFace und OpenRouter
liefern ohne Anmeldung Antworten. Der HUD-Frame legt sich über das Wallpaper
(`hugin.html:161` „In PWA standalone mode this lets iOS wallpaper bleed through
the scan-line mask").

### Schritt 3 · OpenClaw-Bridge in HUGIN eintragen

1. Im HUD auf ⚙ (Einstellungen) tippen.
2. Abschnitt **„OpenClaw — Arbeits-Engine"** (`hugin.html:704 ff.`).
3. URL eintragen (z. B. `http://<tailnet-ip>:18789` oder — bei aktivem
   SSH-Tunnel — `http://127.0.0.1:18789`).
4. Bearer-Token aus Schritt 1 einfügen.
5. Modell auf `openclaw/default` lassen (vom Setup-Script bereits gesetzt).
6. **„OpenClaw verbinden"** tippen.

Ab sofort priorisiert der Router (`hugin.html:1752 ff.`) OpenClaw automatisch
bei komplexen Aufgaben, weil OpenClaw als einziger Provider echte Werkzeuge
(File/Web/Memory/Cron) hat. Für einfache Aufgaben bleibt der lokale/fast-Pfad.

---

## 4 · Race-Mode und TermShell

Der **TERMSHELL** (`hugin.html:2325 ff.`) ist die welt-einzigartige
Komponente dieses Profils. Er ist über den Tab-Wechsel **CHAT ↔ SHELL**
(`hugin.html:1883 ff.`, `switchMode()` in `hugin.html:2328`) erreichbar und
akzeptiert folgende Befehle (`hugin.html:2640 ff.`):

| Befehl | Wirkung |
|---|---|
| `help` | Befehlsübersicht |
| `ls` | Alle registrierten Provider mit Bereitschafts-Status |
| `status` | System-Status (Bereit, keyed, EMA-Scores, Pane-Modus) |
| `ping <provider>` | Smoke-Test eines Providers (Echo „PONG" inkl. ms) |
| `race <prompt>` | An alle bereiten Provider parallel; schnellster gewinnt; alle Antworten sichtbar |
| `run [id…] <prompt>` | Nur die genannten Provider parallel |
| `best <prompt>` | Race + Erstantwort im Pane |
| `tasks <prompt>` | Parallele Aufgabe in den aktuellen Panes (1–4) |
| `history` | Befehlsverlauf |
| `clear` | Terminal leeren |
| `▪ ◫ ⊞ ⊟` | Pane-Modus (1, 2, 3, 4) über Toolbar-Buttons |
| `↑/↓` | Verlaufsnavigation |
| `Tab` | Befehls-Autovervollständigung |

### 4.1 Race-Beispiele

```text
HUGIN> race Erkläre Quantenverschränkung in 3 Sätzen

# Output (kompakt)
TASKS: 9 Provider arbeiten parallel…
✓ pollinations       — 1240ms — "Quantenverschränkung ist eine ..."
✓ groq               —  980ms — "Zwei Teilchen sind so korreliert ..."
✓ cerebras           — 1620ms — "Verschränkung bedeutet ..."
✓ openrouter_free    — 2810ms — "..."
✓ mistral            — 1450ms — "..."
✓ pollinations_r1    — 8900ms — "<Reasoning-Spur> Zwei Teilchen ..."
✓ hf_router          — 2200ms — "..."
✓ openclaw           — 3400ms — "<mit Werkzeug-Lookup> ..."
✓ github_models      — 1950ms — "..."
Gewinner: groq in 980ms
```

```text
HUGIN> best Was ist die Hauptstadt von Burkina Faso?

# Race + Erstantwort im aktiven Pane
best: 5 Provider laufen parallel
Erstantwort (pollinations, 1120ms): Ouagadougou
```

```text
HUGIN> tasks Erzeuge eine Python-Funktion, die Primzahlen bis n filtert

# 4 parallele Panes (tsPanes = 4)
TASKS: 4 Provider arbeiten parallel…
Pane 1 — pollinations: ...
Pane 2 — cerebras:    ...
Pane 3 — openclaw:    ...   ← kann zusätzlich File/Web/Cron nutzen
Pane 4 — github_models: ...
```

### 4.2 Auto-Routing (Chat-Modus)

Im normalen Chat-Modus klassifiziert der Router die Anfrage
(`hugin.html:1694 ff.`) und wählt die Provider-Kette passend zur Aufgabe:

| Aufgabe | Provider-Affinität (Reihenfolge) |
|---|---|
| Reasoning | `pollinations_r1` (DeepSeek-R1) → `openrouter_free` → `featherless` → `hf_free` |
| Code | `featherless` → `hf_free` → `pollinations` → `openrouter_free` |
| Multilingual | `hf_router` → `pollinations` → `featherless` → `openrouter_free` |
| Long-Context | `kluster` → `openrouter_free` → `cerebras` |
| Chat (Default) | `pollinations` → `hf_router` → `openrouter_free` → `featherless` |
| General | `github_models` → `pollinations` → `hf_router` → `openrouter_free` |

OpenClaw wird vorgezogen, wenn verfügbar (`hugin.html:1752 ff.`); das
WebGPU-Modell wird angehängt, wenn `STATE.localEnabled` gesetzt ist;
der Reflex-Kern ist immer Letzter im Fallback und nie aus der Kette
herausnehmbar — das ist der fail-closed-Garant.

### 4.3 EMA-Lernen

Nach jeder Antwort aktualisiert der Router einen exponentiell gewichteten
Score pro Provider (`STATE.providerScores` in `hugin.html`). Erfolg =
Antwort kam; Misserfolg = Timeout / Fehler. Die Gewichtung liegt am Code,
nicht an einer Cloud — sie ist Teil der PWA und überlebt einen
Provider-Wechsel. Wer HUGIN zwei Wochen nutzt, bekommt einen Router, der
seine Vorlieben kennt.

---

## 5 · Sicherheit (gemessen, nicht versprochen)

### 5.1 Wo Keys liegen

| Schlüssel | Liegt in | Verschlüsselung | Verlässt Gerät |
|---|---|---|---|
| Pollinations, HF, OpenRouter, Featherless, Chutes, Cerebras | nicht erforderlich (keyless) | — | — |
| Groq, Google, Mistral, Together, Cohere, xAI, OpenAI | iPhone localStorage, FNV-1a versiegelt, Dual-Slot A/B | Hash + Fallback-Slot | nur in Richtung des jeweiligen Anbieters |
| HUGIN-Kern (eigener Gateway) | iPhone localStorage, SHA-256-Hash-Vergleich beim Boot | Hash | nur an `HM_OWNER_TOKEN`-URL (loopback/VPN) |
| OpenClaw-Gateway-Token | Host (`~/.openclaw/hugin_gateway_token`), chmod 600 | Unix-Permissions | nur an Gateway-URL (loopback/lan/tailnet) |
| Cerebras-Key für OpenClaw-Agent | Host (`~/.openclaw/config` via `openclaw config set`) | Unix-Permissions | nur an Cerebras-API |

### 5.2 Forbidden Patterns

Im Repo gelten mindestens drei voneinander unabhängige Filter:

1. **`hugin_push.py`** (`scripts/hugin_push.py:18 ff.`) blockiert vor jedem
   Git-Push: `.env`, `.pem`, `.key`, `id_rsa`, `id_ed25519`,
   `credentials.json`, `secrets.*`, `token.txt`, `platform-status.json`.
2. **`hugin_oracle.py`** (`scripts/hugin_oracle.py:48 ff.`) hat pro
   Skill-Scope (`research`, `code-review`, `brainstorm`, `codex-patch`,
   `translate`) eigene `forbidden_patterns`. Der `codex-patch`-Scope ist
   bewusst enger als `code-review`: er blockt *Wertzuweisungen* und echte
   Key-Formen (`sk-…`, `ghp_…`, `AIza…`, `BEGIN PRIVATE KEY`), nicht
   Vokabular.
3. **`gitleaks.toml`** im Repo-Root erzwingt Secret-Scanning im CI.

### 5.3 Service Worker — strukturelle Regel

`hugin/sw.js` ist seit der letzten Revision **strukturell** statt namentlich:

```js
// Nur eigene GETs werden angefasst. Alles Fremde und jeder POST geht durch.
if (url.origin !== self.location.origin || e.request.method !== 'GET') {
  return;
}
```

Diese Regel kann nicht veralten — sie nennt keinen Provider-Namen. Frühere
Fassungen hatten eine Allowlist von 14 AI-Hosts; das eigene Gateway stand
nicht darin, also antwortete der Worker bei Gateway-Ausfall mit
`index.html`, wo der PWA-Code einen JSON-Strom erwartete. Der jetzige Code
löst das strukturell.

### 5.4 Admin-Gate

`hugin.html:38 ff.`:
- Token kommt als `?admin=<token>`-Query.
- SHA-256 wird verglichen gegen `ADMIN_SHA256`.
- Bei Erfolg: Token + Sealed-Flag in localStorage; URL wird auf
  `location.pathname` zurückgesetzt (kein Token-Leak in der History).
- Bei Misserfolg: `deny()` rendert eine Lite-Version mit erhaltener
  PWA-Installierbarkeit — Besucher sehen nicht das App-Markup.
- Manipulierter Storage wird aktiv gelöscht, dann `deny()`.

### 5.5 Mandatsgrenze (Workspace-Verfassung)

Die Verfassung (`.claude/persona/constitution.json`) legt fest, was
MUNIN/MUNIN-Profil darf und was nicht. Für die HUGIN-Companion-HUI-Bridge
relevant:

- **Im Mandat ohne Rückfrage**: HUD-PWA öffnen, OpenClaw-Bridge konfigurieren,
  Race-Mode nutzen, TermShell-Befehle ausführen, EMA-Lernen beobachten,
  Provider-Keys eintragen (lokal).
- **An der Mandatsgrenze, anhalten**: Push auf `main`, Verfassungs-Änderung,
  Historie umschreiben, Secrets committen, fremde PRs/Issues verwalten.

Für jeden hier dokumentierten Schritt gilt: **die Auslieferung (Build,
Deploy auf öffentlichen Host, Push auf Default-Branch) braucht eine
explizite Master-Freigabe.**

### 5.6 Runtime-Isolation

Laut `os-architecture-scan.json`:

- **Hypervisor**: Firecracker-MicroVM mit KVM (Full Virtualization).
- **Kernel**: 6.18.5, `nomodule` (kein LKM-Loading, kein dynamisches
  Treiberloading).
- **Init**: `/process_api --firecracker-init`, vsock-Port 2024,
  `--block-local-connections`.
- **Storage**: Root-Disk ext4, mehrere read-only SquashFS für Tools
  (`/opt/claude-code`, `/opt/env-runner`, `/mnt/skills/public`).
- **Capabilities**: fast alle, aber **keine `CAP_SYS_MODULE`**.

Anwendungscode läuft damit in einer dünnen VM; ein Escape wäre doppelt
abgesichert.

---

## 6 · Notfall- und Migrationspfade

| Szenario | Erkennungsmerkmal | Pfad |
|---|---|---|
| Alle Cloud-Provider ausgefallen | Race liefert nur Fehler, Status zeigt 0 bereit | WebGPU-Modell (falls aktiviert) oder Reflex-Kern liefert weiter; Cron-Aufgaben via OpenClaw laufen lokal auf dem Host weiter |
| Internet weg | PWA antwortet aus Cache, Service Worker liefert Shell aus `hugin-v8` | Reflex-Kern + WebGPU-Modell arbeiten offline; HUD bleibt benutzbar |
| OpenClaw-Host weg | Gateway-Ping in `status` rot; OpenClaw in `ls` als „nicht bereit" | Race fällt auf Cloud-Pool zurück; Cron-Aufgaben werden bei Host-Rückkehr nachgeholt (sofern OpenClaw das so konfiguriert hat) |
| Schlüssel korrupt | FNV-1a-Vergleich schlägt fehl | Dual-Slot B wird gelesen; falls B ok, Slot A neu geschrieben; falls beide defekt, Lite-Version fordert Re-Login |
| Admin-Token vergessen | `deny()`-Ansicht | neuen Token beim Master anfordern, Setup-Script liefert ihn (idempotent) |
| PWA veraltet installiert | alter Cache-Schlüssel `hugin-v8` im Service Worker | `activate`-Event räumt alle anderen Caches; beim nächsten Aufruf zählt das Netz (`hugin/sw.js` ab `install`) |
| Workspace-Verfassung widerspricht Anwendungswunsch | Mandatsgrenze erreicht | sofort melden, nicht selbst auflösen (`/workspaces/upgraded-fiesta/.claude/persona/constitution.json` § MUNIN.onConflict) |

---

## 7 · Glossar

| Begriff | Bedeutung |
|---|---|
| **HUGIN** | Die PWA in `hugin/hugin.html`. Single-File, kein Build. |
| **OpenClaw** | Externer Agent-Runtime auf Host/VPS, OpenAI-kompatibles Gateway auf Port 18789. |
| **HUD** | Heads-Up-Display — hier: der transparente PWA-Frame, der das iOS-Wallpaper durchscheinen lässt (`hugin.html:161`). |
| **Companion-HUD** | Dieses Anwendungsprofil: HUD, der auf den Owner „aufpasst" und gleichzeitig Fragen beantworten kann. |
| **TERMSHELL** | Multi-Provider Parallel Shell (`hugin.html:2325 ff.`). |
| **Race** | Befehl, der einen Prompt parallel an alle bereiten Provider schickt; schnellster gewinnt (`hugin.html:2656`). |
| **EMA** | Exponentially Moving Average; Lernmechanismus für Provider-Scores. |
| **FNV-1a** | Nicht-kryptographischer 32-bit-Hash; hier als Integritäts-Siegel für localStorage-Schlüssel. |
| **Dual-Slot A/B** | Zwei localStorage-Slots für denselben Schlüssel; bei Korruption übernimmt der intakte Slot und restauriert den anderen (`hugin.html:774 ff.`). |
| **Reflex-Kern** | Offline-Fallback-Antwortgeber in JavaScript: Calculator, Unit-Converter, Date/Time, Encoding, FNV-1a-Berechnung. Kein Netz, kein Key, kein WebGPU. |
| **WebGPU-Modell** | On-device-Sprachmodell (Llama-Derivat); nur in Safari 26+ / iOS 26 / Chrome mit WebGPU-Flag. |
| **Mandatsgrenze** | Workspace-Verfassung: was MUNIN/MUNIN-Profil eigenmächtig tun darf und was nicht. |
| **Master** | Workspace-Owner `benholl94-cmyk`; einzige Autorität für Architekturziele, Sicherheitsregeln, Push/Publish. |
| **HM_OWNER_TOKEN** | Bearer-Token des `hm-gateway`; `crates/hm-gateway` weigert sich ohne diesen zu starten. |

---

## 8 · Was diese Dokumentation nicht macht

- Sie installiert nichts. Sie beschreibt einen Pfad.
- Sie pusht nichts. Sie liegt als Datei in `docs/` und wartet auf
  Master-Sichtung.
- Sie ändert keine Verfassung. Sie zitiert sie nur.
- Sie ersetzt keine Provider-AGB. Cerebras-1M-Tokens/Tag-Free-Tier
  unterliegt den Bedingungen von cloud.cerebras.ai zum Zeitpunkt der
  Nutzung.

---

## 9 · Offene Punkte (für Beads / Master)

| Punkt | Warum offen | Empfohlene Klärung |
|---|---|---|
| Beads-Initialisierung | Dolt-Server läuft, aber `issue_prefix` config fehlt — `bd create` schlägt fehl | Master-Entscheid: bestehenden Dolt-Bestand migrieren oder neu initialisieren |
| Push auf Default-Branch | Verfassung verlangt Master-Freigabe für Push | nach Sichtung: `git push origin <branch>` durch Master |
| OpenClaw-Bridge als Router-Default | Aktuell wird OpenClaw nur angehängt, wenn verfügbar | offene Architekturentscheidung — soll der Router OpenClaw **immer** als erste Option wählen? |
| Cron-Brücke iPhone → OpenClaw | OpenClaw hat `cron add`, aber HUGIN hat keine Push-Brücke nach außen | Folgeprofil: „HUGIN Push-Forward", Benachrichtigung an iPhone wenn OpenClaw-Cron fehlschlägt |
| Multi-User-Bridge | Aktuell ist OpenClaw-Gateway-Token Single-User | Sicherheitsfrage — getrennte Tokens pro iPhone möglich? |

---

## 10 · Quellen im Repo (Beweis-Anker)

| Aussage | Datei : Zeile |
|---|---|
| HUD-Frame über iOS-Wallpaper | `hugin/hugin.html:161` |
| Install-Hint vor PWA-Installation | `hugin/hugin.html:652` |
| Standalone-Erkennung | `hugin/hugin.html:2308–2310` |
| Provider-Registrierung | `hugin/hugin.html:930` |
| TASK_AFFINITY (Routing) | `hugin/hugin.html:1714–1729` |
| OpenClaw-Vorzug im Router | `hugin/hugin.html:1752–1753` |
| EMA-Score-Update | `hugin/hugin.html` (Status, Pane-Logik) |
| TermShell-Engine | `hugin/hugin.html:2325 ff.` |
| Race-Befehl | `hugin/hugin.html:2656` |
| Reflex-Kern | `hugin/hugin.html:1381 ff.` |
| WebGPU-Provider | `hugin/hugin.html:1317 ff.`, `:1361` |
| FNV-1a-Siegel | `hugin/hugin.html:764` |
| Dual-Slot A/B | `hugin/hugin.html:774–810` |
| Admin-Gate | `hugin/hugin.html:38 ff.` |
| OpenClaw-Setup-Script | `hugin/hugin-openclaw-setup.sh` (gesamte Datei) |
| Service Worker Regel | `hugin/sw.js` (gesamte Datei) |
| Manifest | `hugin/manifest.json` |
| hugin_oracle Skill-Scopes | `scripts/hugin_oracle.py:48–88` |
| hugin_oracle codex-patch patterns | `scripts/hugin_oracle.py:79–88` |
| hugin_push Secret-Blockliste | `scripts/hugin_push.py:18–25` |
| Workspace-Verfassung | `.claude/persona/constitution.json` |
| Mandatsgrenze (MUNIN) | `.claude/persona/constitution.json` § 2_MUNIN |
| Master-Autorität | `.claude/persona/constitution.json` § 1_Master |
| Runtime-Isolation | `.claude/persona/os-architecture-scan.json` |
| hm-gateway Auth | `crates/hm-gateway/README.md`, `docs/production-api-contract.md` |
| Rust-Crates Übersicht | `Cargo.toml`, `crates/*` |

---

*Erstellt im Auftrag des Owners. Kein Push, kein Deploy ohne
Master-Freigabe.*