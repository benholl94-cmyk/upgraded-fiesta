# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Primäre Arbeitsgrundlage — MUNIN

**Der git-Workspace ist die einzige autoritative Quelle.** Alle Entscheidungen, Muster und Zustände werden aus dem Workspace gelesen — nicht aus Chat-Kontext, nicht aus Claude.ai-Workspace-Einstellungen, nicht aus flüchtigen Session-Daten.

Session-Start-Protokoll (immer zuerst ausführen):
```bash
python3 scripts/munin_bridge.py wakeup
```

MUNIN-Dateien (unveränderliche Priorität):
- `.claude/persona/munin.json` — Identität und Constraints (nie überschreiben ohne expliziten Befehl)
- `.claude/persona/munin-state.json` — aktueller Fokus, offene Tasks, bekannte Muster
- `.claude/persona/constitution.json` — **Workspace-Verfassung: Autoritätshierarchie + Mentalität**
- `.claude/agents/munin.md` — Persona-Instruktionen für Claude Code Agent
- `scripts/munin_bridge.py` — Session-Bridge CLI
- `scripts/hugin_oracle.py` — **Provider-Sicherheitsgate (externe AI-Calls)**

Kollisionsprinzip: Bei Widerspruch zwischen Chat-Kontext und git-Dateien **gewinnen immer die git-Dateien**.

## Mandat statt Einzelfreigabe (Amendment A1, 2026-07-26)

Die Verfassung verlangte früher für *jede* Aktion einen Befehl — `noAutoRoutines`, `noGitHubWithoutCommand`, `onAmbiguity: Klärungsfrage stellen`. Damit verbot sie genau die selbstfortsetzende Sitzungsschleife, die der Master beauftragt hatte. Ein Widerspruch wird gemeldet und aufgelöst, nicht umgangen: Amendment A1 ersetzt die pauschalen Verbote durch ein **Mandat mit Grenze**.

**Das Prinzip: die Grenze verläuft entlang Umkehrbarkeit und Reichweite, nicht entlang der Art der Handlung.** Die alte Regel behandelte einen Push auf einen Feature-Branch — für niemanden sichtbar, jederzeit aufgebbar — wie einen Merge nach main. Weil sie beides nicht unterscheiden konnte, brauchte alles eine Freigabe, und die Freigabe wurde zur Formalität statt zur Prüfung.

Ohne Einzelfreigabe: Commit auf jeden Branch außer dem Default-Branch, Push auf `claude/*`, Draft-PRs auf eigenen Branches, Ledger-Schreibvorgänge samt `seal --push`, Antworten am eigenen PR, eigene Routinen, Tests und Supervisor.

Nur auf Befehl (unverändert streng): Merge/Push auf den Default-Branch, Historie umschreiben, Löschen von Branches/getrackten Dateien/Remote-Refs, Secrets, Kommentare auf fremden PRs oder Issues, externe Provider-Calls außerhalb des Oracle-Gates, Änderung der Verfassung.

Die Pflichten machen das Mandat erst vertretbar: jede darin getroffene Entscheidung landet im Ledger — **ein Mandat ohne Protokoll ist keine Autonomie, sondern Unsichtbarkeit** — die Sitzung endet erst mit `seal --push`, der Supervisor läuft vorher, und Angenommenes wird als Annahme benannt.

**Die Grenze wird bewacht, nicht geglaubt.** Die Supervisor-Regel `mandate` rechnet `befehlErforderlich` bei jedem Lauf nach: eine Sitzung, die sich Spielraum verschafft, indem sie einen Eintrag entfernt, wäre sonst von einer legitimen Master-Entscheidung nicht zu unterscheiden. Ein Gegentest in `tests/test_munin_mandate.py` prüft, dass eine entfernte Schranke tatsächlich auffällt — die erste Fassung der Regel tat das *nicht* (sie prüfte mit `any()` über lose Stichwörter, und „push" steckt auch in „force-push").

Änderungen an der Verfassung werden als `amendments`-Eintrag mit dem ersetzten Wortlaut protokolliert; stilles Überschreiben ist kein zulässiges Verfahren. Der frühere Schalter `immutable: true` widersprach dem Master-Recht, jede Regel zu ändern — jetzt `amendable.durch: Master` plus `immutableFor: [munin, claude, provider]`.

## Autoritätshierarchie (Verfassung)

Festgelegt in `.claude/persona/constitution.json`:

1. **Master (benholl94-cmyk)** — Unangefochten. Alle Richtungs-, Architektur- und Sicherheitsentscheidungen.
2. **MUNIN** — Exekutiv. Führt Master-Befehle aus, hält Kontext, meldet Konflikte.
3. **Claude (Anthropic)** — Instrument. Kanal und Wissensquelle, kein eigenständiger Entscheider.
4. **Externe Provider** — Werkzeug, Zero Trust. Nur via `hugin_oracle.py` erreichbar.

## Oracle-Gate — Externe Provider

Alle Calls zu Gemini, OpenAI, Mistral etc. laufen **ausschließlich** durch `scripts/hugin_oracle.py`:
```bash
python3 scripts/hugin_oracle.py query --provider gemini --skill research "Frage"
python3 scripts/hugin_oracle.py query --provider openai --skill code-review "Snippet"
python3 scripts/hugin_oracle.py list-skills   # verfügbare Scopes
python3 scripts/hugin_oracle.py audit-log     # Aufruf-Protokoll
python3 scripts/hugin_oracle.py test-gate     # Selbsttest ohne API-Call
```

Provider-Keys: **niemals committen**. Lokal setzen: `export HUGIN_GEMINI_KEY=...`

---

## Repository scope

This is a Rust workspace ("Fullstack Heavy Metal") with a Vite/React UI scaffold, plus independent projects living in the same repo:

- `crates/` — the Rust workspace (backend/gateway).
- `ui/` — the React/Vite control-plane frontend.
- `hugin/` — **HUGIN PWA**: single-file no-build AI interface (`hugin.html` + `index.html`), deployed to GitHub Pages (`benholl94-cmyk.github.io/upgraded-fiesta`). 25 providers (20 keyless), task-aware router, offline ReflexKernel. One of them — `kern` — is not a foreign API but **this repo's own gateway**: it streams `POST /chat`, so the PWA is the chat through which the system is commanded (`/help` lists the commands). Its wire format is deliberately *not* OpenAI-shaped, because that schema has no field for `exit 1` or for "evidence from repo history", and forcing it would have cost exactly the information the channel exists for. Its in-page self-test covers the event parser and the readiness gate; the full suite is 56 checks and takes ~120 s in a browser (the WebGPU provider timeouts dominate) — it is not hung. `index.html` MUST be a bytewise copy of `hugin.html` — enforced by synergy rule `hugin_index_sync` and CI step. **After any edit to `hugin.html` always run:** `cp hugin/hugin.html hugin/index.html`

  **Installierbar auf iOS — vorher nur scheinbar.** Alle Icons waren SVG, auch
  der `apple-touch-icon` als data-URI. iOS Safari wertet für diesen Link kein
  SVG aus, ignorierte ihn also vollständig: „Zum Home-Bildschirm" ergab kein
  App-Symbol. Der Link war vorhanden, wohlgeformt und wirkungslos — die Sorte
  Fehler, die im Quelltext richtig aussieht. `scripts/generate_hugin_icons.py`
  erzeugt die PNGs (180/192/512) aus derselben Geometrie wie `icon-512.svg`,
  stdlib-only über ein Abstandsfeld, weil es in dieser Umgebung weder Pillow
  noch `rsvg-convert` gibt. Eingecheckte PNGs ohne Generator wären eine
  Behauptung, die niemand nachrechnen kann; `tests/test_hugin_icons.py` prüft
  Datei gegen Generator, gleiche Regel wie `hugin_index_sync`.

  **Der Admin-Gate hat die Installierbarkeit miterschlagen.** Ohne Token
  ersetzte er `document.documentElement.innerHTML` — samt `<link
  rel="manifest">` und `apple-touch-icon` — und genau dieser gesperrte Zustand
  ist der, in dem jemand installiert. Das Sperr-Markup stand viermal wortgleich
  im Dokument: wer eine Stelle ergänzt, baut drei stille Rückfälle. Jetzt eine
  `deny()`-Funktion, die die PWA-Kopfzeilen behält. Der Zugang bleibt
  unverändert gesperrt; ein Icon-Link ist kein Geheimnis, und die Datei liegt
  auf GitHub Pages ohnehin offen.

  Im Browser mit iPhone-Profil gegengeprüft, nicht behauptet: gesperrter
  Bildschirm, `apple-touch-icon` liefert HTTP 200 `image/png`, alle vier
  Manifest-Icons abrufbar, Service Worker aktiv, neun Shell-Einträge im Cache,
  Offline-Neuladen funktioniert. Der Cache-Schlüssel muss bei jeder
  Shell-Änderung hoch (jetzt `hugin-v8`), sonst behält ein installiertes Gerät
  die alte Shell und die neuen Icons kommen dort nie an. Und `cache.addAll` ist
  alles-oder-nichts: eine fehlende Datei kostete den gesamten Offline-Betrieb,
  nicht nur das Icon — der Kern ist jetzt hart, der Rest nachsichtig.
- `ghm_core/` + root `pyproject.toml` — `ghm-core`, a real installable pip package (console script `ghm-core`) providing local workspace/onboarding tooling.
- `iphone-dev-platform/` — a **fully self-contained** static site (German-language iPhone local-dev setup guide) imported from an unrelated, disconnected git history. It has its own `package.json`, `validate.py`/`test-validate.py`, and must be tested from inside that directory (`cd iphone-dev-platform && npm test`), never from the repo root. Do not assume anything in it shares code, dependencies, or conventions with the Rust workspace.

Config lives under `config/`, database bootstrap SQL is in `scripts/init-db.sql`, validation/dev scripts live under `scripts/`.

`.claude/skills/xcode-alternative/` is a Claude Code Skill for scaffolding and building iOS/Swift projects without Xcode.app's GUI (SwiftPM `Package.swift` as the preferred real project format, plus a minimal `.xcodeproj` generator for when one is strictly required). It reproduces no proprietary Apple IDE data — see the skill's own "What this is (and isn't)" section. Its scaffolder is stdlib-only Python, tested in `tests/test_xcode_alternative_scaffold.py`; the actual build/sign/simulate steps it documents require a real macOS host and were not (and cannot be) executed from this Linux environment.

`.claude/skills/pr-bot-triage/` is a Claude Code Skill for triaging automated PR review-bot comments (CodeRabbit rate-limit notices, duplicate walkthrough re-postings, bot-side infrastructure errors, resolution/learning acknowledgments) so real findings don't get lost in repeated noise while babysitting a PR. Its classifier (`scripts/classify_bot_comment.py`) is stdlib-only Python, tested against real comment text observed on this repo's own PRs (`tests/test_pr_bot_triage.py`), not synthetic samples.

## Operating environment

The primary operator may only have an iPhone/mobile client. Do not assume access to macOS, a desktop IDE, local Docker Desktop, Homebrew, or a long-running local shell. Prefer repository-native automation, Codex cloud, GitHub Actions, and portable shell/Python scripts. Do not replace this mobile-first operating model with desktop-only instructions.

Never commit API keys, tokens, private SSH keys, `.env` files, generated secrets, or host-specific credentials.

## Commands

From the repository root:

```sh
python3 scripts/validate_repo.py      # structural validation: workspace members, config JSON, required files
bash scripts/codex_fullstack_check.sh # preferred single verification command (see below)
cargo check --workspace
cargo test --workspace
cd ui && npm run build
python3 -m pytest tests/              # Python tests (ghm_core CLI smoke tests, url-builder, etc.)
```

`bash scripts/codex_fullstack_check.sh` validates repo structure, checks Rust formatting (when `cargo fmt` is available), runs `cargo check`/`cargo test` for the workspace, installs UI deps without writing a lockfile, and builds the UI. Run it (or the equivalent subset) before calling a change done.

It used to **exit 1 on a clean checkout** where everything actually passed: the
final `docker compose config` step is a *syntax* check, but `docker-compose.yml`
interpolates `HM_OWNER_TOKEN` as a required variable, so without an exported
token the whole verification failed after fmt, check, test and the UI build had
all succeeded. A missing token is a start gate for *operation*, not a statement
about the repository — and a pre-flight check that fails on something it isn't
even checking gets bypassed the second time, which is the same lesson
`hugin_clarity.py --start` was built on. The step now supplies a placeholder for
the syntax check only; a real exported token still wins.

Single-test invocations:

```sh
cargo test -p hm-gateway some_test_name       # one Rust crate/test
python3 -m pytest tests/test_ghm_core_cli_smoke.py::test_doctor -v   # one Python test
```

For the isolated iPhone site, run its own tooling from its own directory — it is not covered by any of the above:

```sh
cd iphone-dev-platform && npm test    # or: python3 scripts/test-validate.py
```

Codex cloud environment setup/maintenance commands (`bash .codex/setup.sh`, `bash .codex/maintenance.sh`) wrap `scripts/codex_fullstack_setup.sh` and dependency refresh (`cargo fetch`, `npm install`) respectively — see `AGENTS.md` for when these apply.

### `deploy/fullstack-compose.yml` — erstmals live gefahren, und es war kaputt

Am 2026-08-02 zum ersten Mal wirklich gestartet. Die Datei galt bis dahin
als gueltig: `docker compose config` bestand, das Build-Manifest fuehrte
`compose-syntax: bestanden`. **Sie war nicht startbar.**

Eine Ursache, drei Fehler: die Datei liegt in `deploy/`, und docker compose
loest `./` gegen das Verzeichnis der Compose-Datei auf — nicht gegen die
Repo-Wurzel.

| Pfad in der Datei | zeigte auf | existiert |
|---|---|---|
| `./scripts/init-db.sql` | `deploy/scripts/init-db.sql` | nein |
| `./config/nginx-lb.conf` | `deploy/config/nginx-lb.conf` | nein |
| `context: .` | `deploy/` | kein Dockerfile |

**Der erste war der tueckischste: Docker legt fuer einen fehlenden
Bind-Mount ein Verzeichnis an, statt zu scheitern.** Postgres startete,
legte die Datenbank an und starb dann an `psql: could not read from input
file: Is a directory` — eine Meldung ueber ein Verzeichnis, das es vorher
nicht gab.

**Und danach kam die gefaehrlichere Stufe.** Nach dem gescheiterten Init
bleibt ein halb angelegtes Datenverzeichnis liegen; Postgres meldet beim
naechsten Start `Skipping initialization`, wird `healthy` — und die
Datenbank ist leer. Gesund gemeldet, ohne Schema. Ein `down -v` ohne
gesetzte Pflichtvariablen entfernt das Volume **nicht**, sondern bricht
still ab.

Nach der Korrektur live gemessen: `postgres healthy`, `redis healthy`,
Tabellen `memories`/`messages`/`sessions`, Erweiterungen `vector` und
`pg_trgm` aktiv, `redis-cli ping` → `PONG`.

**Die Lehre, als Invariante festgehalten: eine Syntaxpruefung ist kein
Startbarkeitsnachweis.** `docker compose config` prueft nicht, ob ein
Bind-Mount-Ziel existiert — dieselbe Luecke, die hier schon das
Containerimage gekostet hat. `tests/test_fullstack_compose.py` rechnet
jetzt jeden relativen Pfad gegen das Dateisystem nach.

### Die Bruecke — Routenplanung, und ausdruecklich kein zweiter Ausgang

`scripts/hugin_bruecke.py` plant Provider-Aufrufe: Anfrage-Huelle rein,
Kette R1–R7, versiegelte Routentabelle, Grenz- und Kopfzeilenpruefung,
kettenverhakte Quittung. Uebernommen aus einem eigenstaendigen
stdlib-only-Werkzeug und fuer dieses Repo umbenannt (Zustand unter
`~/.hugin/bruecke`, `HUGIN_BRUECKE_HEIM`, Namensfamilie `hugin_*`).

**Sie sendet nichts.** R6 erzeugt einen Plan; es wird nie ein Socket
geoeffnet. Genau das ist der Grund, warum sie neben `hugin_oracle.py`
stehen darf: die Verfassung kennt **einen** Weg nach draussen, und das ist
das Oracle-Gate. Ein zweiter waere kein Rueckfallplan, sondern die Stelle,
an der beide auseinanderlaufen und niemand merkt, welcher der betriebene
ist.

| | Bruecke | Oracle-Gate |
|---|---|---|
| Frage | wohin, welche Koepfe, welche Groesse | darf das raus, was kommt zurueck |
| Netz | **nie** | ja, der einzige Ausgang |

`tests/test_hugin_bruecke.py` **rechnet das nach** statt es zu glauben: es
parst den Importbaum und verlangt, dass weder `socket` noch `urllib` noch
`requests` vorkommen. Dazu die Gegenproben, die zaehlen — ein fremder
Schluessel darf den Zustand nicht oeffnen, ein beschaedigtes Fach wird aus
dem gesunden geheilt, und eine **veraenderte Chronikzeile muss auffallen**
(eine Verhakung, die das nicht bemerkt, ist Zierde). Die 100 mitgelieferten
Selbsttestfaelle laufen mit.

Ehrlich benannte Grenze: der HMAC-Schluessel liegt auf demselben Geraet wie
der Zustand. Die Siegel schuetzen gegen Beschaedigung und stilles
Abdriften, **nicht** gegen einen Angreifer mit Schreibrecht — derselbe
Zuschnitt wie beim Schluesselbund, wo sechs Schluessel selbst ausstellbar
sind und elf ausdruecklich nicht.

### Der Zyklus — die Kette, nicht ein weiteres Werkzeug

`scripts/hugin_zyklus.py` baut **nichts Neues**. Dieses Repo hatte alle
Werkzeuge einer selbstpruefenden Architektur — Inventar, Klarheit,
Supervisor, Korpus, Selfheal, `codeam_cli verify` — und **keines lief
automatisch mit den anderen**. Ein Werkzeugkasten ohne Kette ist eine
Ansammlung; woran sich niemand erinnert, das laeuft nicht.

```sh
python3 scripts/hugin_zyklus.py              # Vorlauf, schreibt nichts
python3 scripts/hugin_zyklus.py --apply      # heilen und erden
python3 scripts/hugin_zyklus.py --nur messen,pruefen
```

**Die Reihenfolge folgt der Abhaengigkeit, nicht der Bequemlichkeit:**
messen (was ist da) → erden (Korpus neu, *vor* dem Pruefen — ein veralteter
Korpus laesst den Kern auf einen Stand antworten, den es nicht mehr gibt) →
heilen (nur Deterministisches) → pruefen (Tests, Supervisor, Startfreiheit,
Index) → berichten.

**Drei Ausgaenge, und die Trennung ist der eigentliche Beitrag:**

| Exit | Bedeutung |
|---|---|
| 0 | nichts zu tun |
| 1 | **Befund** — mit Teil, Grund und Befehl |
| 2 | **Defekt** — die Kette selbst ist gescheitert |

Ein Werkzeug, das mit 1 endet, hat gearbeitet und etwas gefunden; eines mit
127 gibt es nicht. Beides zusammenzuwerfen hiesse, ein defektes Thermometer
wie Fieber zu behandeln. Der erste Lauf hat das sofort belegt: der
Testschritt ruft `-m pytest`, meine Existenzpruefung hielt `-m` fuer einen
Dateipfad — und der Zyklus meldete seinen **eigenen** Fehler korrekt als
Defekt, nicht als Befund.

`.github/workflows/zyklus.yml` faehrt die Kette taeglich (04:17 UTC, nicht
zur vollen Stunde — dort draengen sich alle Zeitplaene und ein verzoegerter
Lauf sieht aus wie ein ausgefallener). **Er schreibt nie auf den
Default-Branch**: Ergebnisse landen auf einem `claude/`-Branch mit
Draft-PR. Merge bleibt Master-Entscheidung — eine Routine, die sich diese
Grenze nimmt, waere von einer legitimen Entscheidung nicht mehr zu
unterscheiden. `tests/test_hugin_zyklus.py` rechnet das nach.

Zwei eigene Fehler beim Bauen, beide von den vorhandenen Wachen gefangen:
ein Test, der die Stufe `pruefen` wirklich aufrief und damit `pytest` in
`pytest` startete (Rekursion mit Zeitplan, >10 Minuten); und eine
Commit-Botschaft in Spalte 1, die den YAML-Blockskalar beendete — dieselbe
Ursache, die `munin-link-hourly.yml` monatelang mit `total_jobs: 0` laufen
liess.

### Inventar — kein Teil im Zustand „unbekannt"

`scripts/hugin_inventar.py` beantwortet weder „laeuft es" (das tut
`codeam_cli.py verify`) noch „darf es so sein" (`munin_supervisor.py`),
sondern: **ist jeder Teil ueberhaupt erfasst — und wenn nicht, welcher Befehl
schliesst ihn.**

```sh
python3 scripts/hugin_inventar.py            # Bericht je Art
python3 scripts/hugin_inventar.py --offen    # nur das Schliessbare
python3 scripts/hugin_inventar.py --index    # docs/INVENTAR.md erzeugen
```

Drei Zustaende: `geschlossen`, `offen` (**mit Befehl**), `extern` (von hier
nicht entscheidbar). **`unbekannt` gibt es nicht** — was das Programm nicht
einordnen kann, wird als `offen` gefuehrt und benannt, nie weggelassen.
`extern` von `offen` zu trennen ist kein Komfort: eine Liste, die nie leer
wird, wird nicht gelesen.

Ein Teil, ueber den niemand etwas sagen kann, ist gefaehrlicher als ein
kaputter — der kaputte faellt auf. Dieses Repo hat genau daran dreimal
verloren: die Plugin-Dispatch, die im Image fehlte; der Chat, dessen
`agents/` nicht kopiert wurde; die Erdung, die ohne `.git` von 178 auf 59
Faelle fiel. Alle drei waren nicht kaputt, sondern **unerfasst**.

**Drei eigene Messfehler, in `tests/test_inventar_und_skripte.py`
festgehalten**, weil ein Befund, der keiner ist, die Glaubwuerdigkeit der
ganzen Liste kostet:

| Fehler | Folge | Behoben durch |
|---|---|---|
| `tests/` als einzige Testquelle | 12 von 20 Kraten faelschlich „ungeprueft" (Rust testet in `#[cfg(test)]`) | Modultests mitzaehlen |
| Namenssuche bricht beim ersten Treffer ab | getestete Skripte gelten als ungeprueft (`import hugin_keyring` ohne `.py`) | Vereinigung statt erster Liste |
| der eigene Bericht wird mitgelesen | Workflows sprangen 15/18 → 18/18, ohne Aenderung | `docs/INVENTAR.md` beim Messen ausklammern |

Der letzte ist dieselbe **Selbstbezugs-Falle** wie beim Korpus, der seine
eigenen Gegenbeispiele las — dreimal in einer Sitzung, jedes Mal anders
verkleidet.

`tests/test_inventar_und_skripte.py` traegt ausserdem eine **Grundwache ueber
jedes Skript**, parametrisiert ueber die tatsaechliche Dateiliste statt ueber
eine gepflegte Aufzaehlung: Syntax, Moduldocstring, `--help`, und **kein
`shell=True` irgendwo**. Sie behauptet nicht, dass die Programme fachlich
richtig sind — nur, dass sie startbar sind. Das ist wenig und es ist wahr.

### Der operative Weg — drei Befehle, sechs Beweise

Es gibt **einen** Weg vom leeren Rechner zum befehligbaren System, und er ist
`scripts/codeam_cli.py`. Kein zweiter daneben: ein zweiter Weg ist kein
Rueckfallplan, sondern die Stelle, an der beide auseinanderlaufen und niemand
merkt, welcher der betriebene ist.

```sh
python3 scripts/codeam_cli.py prepare --yes   # Werkzeuge, Schluessel, Bau, Selbsterhalt
python3 scripts/codeam_cli.py up              # startet und wartet, bis er antwortet
python3 scripts/codeam_cli.py verify          # sechs Beweise, Exit 1 bei jedem Fehlbefund
```

`up` gibt kein "gestartet" zurueck, weil `Popen` das nicht weiss: der Prozess
kann in derselben Sekunde am fehlenden Token sterben — genau der vorgesehene
fail-closed-Fall. Gewartet wird auf eine Antwort.

**`verify` fuehrte lange genau einen Beweis und meldete trotzdem gruen.**
`/health` antwortet sagt, dass ein Prozess lebt. Es sagt nicht, dass der
Zugang gesperrt ist, und nicht, dass sich das System befehligen laesst — also
gerade das nicht, was den Weg operativ macht. Jetzt sind es sechs, und es sind
dieselben vier Live-Beweise, die `release.yml` am Containerimage fuehrt:

| Beweis | Kriterium | warum nicht weniger |
|---|---|---|
| `startfrei` | `hugin_clarity.py --start` | verhindert etwas den Betrieb — nicht: begrenzt ihn |
| `dienst` | TCP-Handschlag | ein Lookup ist keine Erreichbarkeit |
| `health` | `200` **mit** Token | ein offener Port beweist nicht, dass es dieses Gateway ist |
| `gesperrt` | `401` **ohne** Token | die einzige Pruefung, deren Erfolg ein Fehlercode ist |
| `chat` | Stream bis `[DONE]` | ein Stream, der abbricht, sieht am Anfang aus wie einer, der traegt |
| `dispatch` | `plugin_dispatched` | `202 accepted` hat das Gateway monatelang geantwortet, waehrend jeder Task ins Leere lief |

`tests/test_codeam_verify.py` prueft jede Richtung gegen einen hermetischen
Server im selben Prozess — auch die Gegenproben: ein **offenes** Gateway muss
`gesperrt` fallen lassen, ein abgebrochener Stream muss `chat` fallen lassen,
ein `unhandled` muss `dispatch` fallen lassen. Hermetisch deshalb, weil der
Gegentest einen offenen Server braucht und ein absichtlich auth-freies Gateway
auf einem echten Port nichts ist, was in einer Testsuite laufen sollte.

### Ein Release entsteht aus einem Tag, nicht aus einer Hand

`.github/workflows/release.yml` haengt an `push: tags: ["v*"]`. Damit genuegt
`git tag v1.0.0 && git push --tags` — von jedem Geraet, auch vom Telefon ueber
die GitHub-Oberflaeche. Der Bau laeuft danach ohne weiteres Zutun: Rust-Release,
UI, PWA-Synchronitaetspruefung, Containerimage, **Live-Ansprache des Images**
(`/health`, 401 ohne Token, `/chat` bis `[DONE]`, `/tasks` bis
`plugin_dispatched`), erst danach GHCR-Push und `gh release create`.

Der Grund fuer die Reihenfolge ist derselbe wie ueberall hier: ein Image, das
gebaut wurde, ist nicht dasselbe wie ein Image, das antwortet — diese Luecke hat
schon die Plugin-Dispatch und danach den Chat gekostet, beide gruen im Checkout
und tot im Container. Ein Release ist der letzte Ort, an dem das auffallen darf,
also wird veroeffentlicht *nach* der Live-Pruefung, nicht davor.

**Die Notiz wird gerechnet, nicht geschrieben.** `scripts/release_notes.py`
liest ausschliesslich `status/build-manifest.json` und
`status/deploy-contract.json`. Kein Wert darin ist von Hand hineingeschrieben;
steht etwas dort nicht, steht es im Release nicht. Von Hand geschriebene
Release-Notizen veralten ab dem naechsten Bau, ohne dass es jemand merkt —
dieselbe Drift wie bei der Krate-Tabelle („intentional placeholders", waehrend
die Kraten laengst echt waren) und der Zeile „31 Dateien getrackt trotz
.gitignore", die lange nach dem Aufraeumen noch dastand.

Der Abschnitt **„Was hier NICHT nachgewiesen ist" ist nicht optional**:
gefallene und unbekannte Pruefungen erscheinen genauso wie bestandene, fehlende
Artefakte werden als fehlend gefuehrt, und die dauerhaften Grenzen (keine
Kanalkrate gegen eine echte Chat-Plattform getestet, kein lokales GGUF im
Release) stehen auch in einem vollstaendig gruenen Lauf da. Eine Notiz, die nur
Bestandenes zeigt, ist eine Auswahl und keine Aussage.
`tests/test_release_notes.py` haelt beides fest — auch den Gegentest, der
zaehlt: ein Geheimnis in der Notiz fuehrt nicht zu einer Warnung, sondern dazu,
dass die Datei **nicht geschrieben** wird.

Kein Drittanbieter-Geheimnis: veroeffentlicht wird mit dem eingebauten
`GITHUB_TOKEN` nach GHCR und in die Releases desselben Repositories.

### Readiness vs. constitution: `scripts/hugin_clarity.py`

The supervisor answers *may it be like this*. This one answers *does it carry
right now* — and when it doesn't, which exact value is missing and which command
supplies it.

```sh
python3 scripts/hugin_clarity.py          # full report
python3 scripts/hugin_clarity.py --offen  # only what is still missing
python3 scripts/hugin_clarity.py --json
```

Three verdicts, and the third is load-bearing: `OK`, `OFFEN` (something specific
is missing, `befehl` says what), and `EXTERN` (not decidable from here — needs
the Master, real hardware, or a third-party account). Collapsing `EXTERN` into
`OFFEN` produces a list that is never empty, and a list that is never empty stops
being read. Exit is `1` only for `OFFEN`.

`--start` is a separate question: **does anything prevent operation**, as
opposed to merely limiting it. A missing local model limits (T0 still carries,
the gateway runs, commands and evidence work); a missing `HM_OWNER_TOKEN`
blocks, because the process refuses to start by design. That distinction was
missing at first and cost a working handover immediately — the start line
`hugin_clarity.py --offen && cargo run -p hm-gateway` started the gateway
**never**, because an un-downloaded 6.6 GB model set the exit to 1. A pre-flight
check that refuses on any incompleteness gets bypassed the second time, which
makes it worse than none.

It is a program rather than a checklist for the same reason the supervisor is:
the line *"31 files tracked despite .gitignore"* sat in this file long after the
count was 0. A measurement cannot go stale that way.

**Two inverted readings it caught in its own first run**, both pointing the
dangerous way — claiming a rung holds when it doesn't:

- `Budget.active` means *the brake is engaged*, not *spending is allowed*. The
  tier ladder read it backwards and reported "T2 open" while every metered
  provider was blocked.
- A keyless provider was counted as reachable because it needed no key.
  `local` (Ollama) was therefore reported available while nothing listened on
  11434. Availability of a network service is now a TCP handshake, not a lookup.

**`hm-plugins` got its first tests, and they immediately found a real defect.**
A plugin that never reads its stdin makes the request write fail with `EPIPE`;
that error was propagated raw, so the *same* invocation returned either
`"Broken pipe (os error 32)"` or `"produced no output"` depending on which side
of the race won. `EPIPE` is now treated as what it is — a statement about the
plugin, not a protocol failure — and the accurate message comes from the stdout
path. The first version of those tests was itself flaky (`Text file busy`, the
classic fork/exec race against a freshly written script); executing `/bin/sh`
with the plugin body as an *argument* removes the window entirely instead of
narrowing it.

**CORS was configured-but-unwired.** `allowed_origin_from` was correct and
unit-tested, and also dead for every value except `*`: nothing ever read the
request's `Origin` header, so every call site passed `None`. Setting
`HM_ALLOWED_ORIGINS=https://…` did exactly nothing and the only setting that
*worked* was the least safe one. The header is now parsed onto `HttpRequest` and
applied once, in `apply_cors`, to the finished response — threading it through
~30 `json_response` call sites would be 30 chances to forget one, and a
forgotten one fails silently in a browser. Verified live on a socket for the
allowed origin, a foreign origin, the preflight, the chat stream, and the 401.

**The container could not chat.** The runtime image copied `config/`,
`plugins/` and `scripts/` but not `agents/` — the gateway started fine and every
chat turn answered `brain not startable`. Green in a checkout, dead in
production; the same failure class as the plugin dispatch that was missing from
the image before.

## T1b lokal — das Modell laeuft wirklich

`models/model.gguf` war monatelang eine Zeile in einem Bericht: *„fehlt, 6,6 GB"*.
Sie wurde nie geholt. Jetzt ist sie ein Befehl:

```sh
python3 scripts/hugin_local_model.py setup     # holen, pruefen, bauen, starten
python3 scripts/hugin_local_model.py status    # fragt den Dienst, nicht die Platte
python3 scripts/hugin_local_model.py ask "..." # eine Frage, Exit-Code sagt ob es klappte
```

Gemessen auf dieser Maschine (4 Kerne, CPU-only): Download 7.029.535.392 B,
SHA-256 stimmt mit `config/model.json`; llama.cpp aus der Quelle gebaut;
Prompt 37,3 t/s, Generierung 11,7 t/s; eine geerdete Antwort in 2,9 s.

**Server, nicht CLI.** `llama-cli` laed die 7 GB pro Frage neu und bricht in
aktuellen Builds mit SIGABRT in `cli_server::wait_ready` ab — live gesehen.
`llama-server` haelt das Modell im Speicher; `agents/brain.py` spricht es ueber
`/v1/chat/completions` an und streamt tokenweise.

Modell und Binaries stehen in `.gitignore`: 7 GB laegen sonst in jedem Clone
fuer immer. `hugin_local_model.py setup` stellt beides reproduzierbar her.

**Drei Fehler, die erst der erste echte Lauf zeigte** — alle drei sahen vorher
richtig aus:

- **Verfuegbarkeit wurde aus Dateien geschlossen.** `tiers()` prueft jetzt den
  Dienst. Vorher lagen Modell und Binary vor, T1b meldete `[x]`, und der
  Aufruf stuerzte ab. Dieselbe Invariante wie bei `hugin_clarity.py`:
  gemessen, nie gelesen.
- **Die Belegsuche fand nichts, wegen deutscher Flexion.** Die Frage sagt
  *atomarer*, der Ledgereintrag *atomar*; der exakte Mengenschnitt ergab
  0,000 — ueber **alle 133** Faelle der Historie. Der Kern antwortete darum
  auf jede Frage „nicht belegt", und das Modell war unbenutzbar. Jetzt genuegt
  ein gemeinsamer Wortanfang ab 5 Zeichen, wobei eines ein Praefix des anderen
  sein muss. Gegenprobe im Test: eine sachfremde Frage bleibt bei 0,000.
- **Eine Frage wurde verboten.** `_FORBIDS` fand das Wort *kein* in der
  erklaerenden Invariante „Hier *kein* Randfall …" und antwortete
  „VERWEIGERT" — unter Zitat genau der Invariante, die die Antwort enthielt.
  Jetzt blockieren Invarianten nur Vorhaben, nicht Fragen; unterschieden wird
  an der Satzform, **nicht** an `Situation.kind` — dieses Feld setzt in der
  Praxis niemand, und eine Schranke an ein leeres Feld zu haengen schaltet sie
  ab, statt sie zu schaerfen. Der Gegentest prueft beide Richtungen.

`tests/test_local_model.py` haelt alle drei fest (15 Tests). Die zwei, die das
echte Modell befragen, ueberspringen sich mit Angabe des Befehls, wenn der
Dienst nicht laeuft — der Rest laeuft immer.

## Metatests — prueft die Wachen, oder sehen sie nur so aus?

`tests/test_meta_guards.py` rechnet die Invariante *„Jede Wache braucht einen
Gegentest"* nach, statt sie zu befolgen. Sie stand lange nur als Satz in dieser
Datei; jetzt bricht ein Test jede Invariante **absichtlich** und verlangt, dass
genau die zustaendige Wache faellt:

| Mutation | muss rot werden |
|---|---|
| `redirect_stdout` im autonomy-pulse-Plugin entfernt | `tests/test_autonomy_pulse_plugin.py` |
| `": "` in einen unquotierten YAML-Wert eingebaut | `tests/test_workflows_parse.py` |
| ein PNG weicht vom Generator ab | `tests/test_hugin_icons.py` |
| `Command.braucht` geleert | `tests/test_brain.py` |
| `index.html` von `hugin.html` entkoppelt | Synergie-Regel `hugin_index_sync` |

**Die Mutationen finden in einer Kopie statt, nie im Arbeitsbaum.** Bis
2026-07-31 wurde die echte Datei veraendert und in `finally` zurueckgeschrieben
— `finally` laeuft aber nicht, wenn der Prozess stirbt. Ein abgebrochener Lauf
hinterliess `.github/workflows/ci.yml` mit kaputtem YAML und ein veraendertes
`hugin/icon-192.png`; ein Commit in diesem Moment haette den Schaden nach git
getragen. Messbare Folge: Metatests plus **irgendeine** zweite Testdatei waren
in 3 von 6 Laeufen rot, weil die naechste Mutation ihre Vorlage in der bereits
veraenderten Datei nicht mehr fand. Der alte Docstring begruendete das
Vorgehen damit, Kopieren sei "langsam genug, dass der Test in CI uebersprungen
wuerde" — eine Annahme, keine Messung: **378 getrackte Dateien, 3,3 MB,
0,06 s**. Nachher 6 von 6 gruen, und drei harte `SIGKILL` mitten in der
Mutation lassen den Baum unberuehrt.

Schlaegt einer dieser Faelle fehl, ist die zugehoerige Wache **wirkungslos
geworden** — und das erfaehrt man hier statt beim naechsten Ausfall im Betrieb.
Die Mutation wird im Arbeitsbaum vorgenommen und in `finally` aus dem
gehaltenen Original zurueckgeschrieben; passt die Vorlage nicht mehr, faellt
der Metatest laut, statt still nichts zu pruefen.

Zwei weitere Gruppen prueft dieselbe Datei:

**Kein Test ohne lebendes Subjekt.** Gefunden hat das sofort zwei echte
Waisen: `tests/test_codex_cloud_setup.sh` und
`tests/test_validate_iphone_control_plane.sh` prueften Skripte, die **nie in
der Historie von `main` existierten** — sie wurden ohne ihre Subjekte
gemerged. Dreifach wirkungslos: falsches Subjekt, `pytest` sammelt keine
`.sh`-Dateien (sie liefen in CI nie), und sie beendeten sich mit **Exit 0,
waehrend sie `FAIL:` ausgaben**. Beide entfernt.

**Verbindungsrouten.** Jede Route im `match`-Block des Gateways muss im
API-Vertrag stehen, und jeder Eintrag in `config/plugins.json` muss auf ein
vorhandenes Programm zeigen. `/sessions` war real, getestet und in der
Routenliste nicht aufgefuehrt; `ops-tool` zeigte auf einen Pfad, den nur der
Release-Build hat. Beides wurde von Hand gefunden — ab hier findet es eine
Wache.

## Supervisor and known dead data

`scripts/munin_supervisor.py` audits the *agent's work* against `.claude/persona/constitution.json` and `.claude/persona/munin.json`. Its principle is that claims get recomputed rather than believed: "tests pass" runs the suite, "index.html is synced" compares bytes, "that crate is a stub" counts `pub fn`. Run it before calling anything done:

```sh
python3 scripts/munin_supervisor.py --quick      # skip the test run
python3 scripts/munin_supervisor.py --watch 300  # continuous
```

Exit `0` clean / `1` DRIFT·RISK / `2` VIOLATION.

### Key self-supply (`scripts/hugin_keyring.py`)

The repo issues the keys it actually controls. There are 20 secret env vars; exactly **6 are self-issuable** because both ends belong to this project — a freshly generated value is valid since nobody else has to recognise it:

`HM_OWNER_TOKEN`, `HM_DIAGNOSTICS_KEY`, `HM_MEMORY_KEY`, `HM_CONSOLE_SECRET`, `HM_REMOTE_STORAGE_TOKEN`, `HM_WHATSAPP_VERIFY_TOKEN`

The other 11 are provider-bound (OpenAI, Gemini, Mistral, Telegram, Discord, Slack, WhatsApp, generic LLM). The keyring **refuses to generate those** — a self-rolled value would simply be invalid — and instead records where to obtain each one.

**Mechanism: hierarchical deterministic derivation.** One master seed; every service key is derived via HKDF (RFC 5869, hand-rolled on `hmac`/`hashlib` because the repo is stdlib-only):

```
key(service, version) = HKDF(master_seed, info="hugin.keyring.v1|SERVICE|VERSION")
```

Three consequences, and they are the reason for the design: **one backup suffices** (the seed reproduces every key); **rotation is a counter** (bump the version; the old one stays derivable during a grace window so a running service doesn't drop); **nothing secret ever reaches the repo** (the seed lives in `~/.hugin/` at 0600, derived keys exist only in memory and the shell). Same idea hardware wallets use for key hierarchies, minus the curve arithmetic.

The HKDF implementation is checked against the RFC 5869 test vectors in `tests/test_hugin_keyring.py` — a hand-rolled derivation that *looks* right but computes wrong is more dangerous than none.

```sh
python3 scripts/hugin_keyring.py init                    # create the master seed
eval "$(python3 scripts/hugin_keyring.py env)"           # load into the shell
python3 scripts/hugin_keyring.py status                  # what's present, what's missing
python3 scripts/hugin_keyring.py rotate HM_OWNER_TOKEN --yes
python3 scripts/hugin_keyring.py audit                   # leak + permission check
```

The supervisor's `keyring` rule calls that audit rather than duplicating it — two copies of the same check drift apart.

### Git identity: author and committer are different fields

The supervisor reported an unresolvable collision for a long time — the harness
stop-hook requires `noreply@anthropic.com`, the constitution requires the owner's
address. That was true only while both were read as claims on *the same* field.
They are not:

| Field | Value | Why |
|---|---|---|
| **Author** (`%ae`) | `274793931+benholl94-cmyk@users.noreply.github.com` | Authorship. Constitution, authority level 1. |
| **Committer** (`%ce`) | `noreply@anthropic.com` | Signature validity — the CCR SSH signing key is registered to it; any other committer email makes every commit show as *Unverified* on GitHub. |

Git has no `author.email` setting, so the committer comes from `git config
user.email` and the author from `GIT_AUTHOR_NAME`/`GIT_AUTHOR_EMAIL` (or
`git commit --author=`). Both must be set when committing:

```sh
GIT_AUTHOR_NAME="benholl94-cmyk" \
GIT_AUTHOR_EMAIL="274793931+benholl94-cmyk@users.noreply.github.com" git commit …
```

The supervisor now checks the two **separately** and names whichever side drifts;
a single combined finding is what hid the resolution in the first place. The
author is read from the last commit rather than from config, because config has
no author field and what is actually in the history is the only answer worth
trusting.

### Hooks are versioned in the repo

`~/.claude/stop-hook-git-check.sh` lives outside the repo, so a fix there survives no container rebuild and shows up in no diff. The authoritative copy is `.claude/hooks/stop-hook-git-check.sh`; `scripts/install_hooks.py` mirrors it **repo → home only** (never the reverse — that would recreate the silent divergence). The supervisor's `hook-drift` rule compares the two byte-for-byte, same as `hugin_index_sync`.

```sh
python3 scripts/install_hooks.py --check   # drift?
python3 scripts/install_hooks.py --yes     # install (backs up the old copy)
```

The hook's signature and unpushed checks compare against the **default branch**, not the remote tracking branch. Reason, and it is not hypothetical: after a PR merges and the local branch is reset onto main, `origin/<branch>` still points at the pre-merge tip. `origin/<branch>..HEAD` then contains main's own history — the merge commit and CI bot commits — and the hook demanded a rebase over commits belonging to other authors that were already on main. Following it would have orphaned the merge and force-pushed over the default branch. `tests/test_stop_hook.py` pins all of this, including the counter-check that real local work is still caught.

### Session continuity (`scripts/munin_continuity.py`)

`.claude/persona/munin-state.json` is in `.gitignore` (line 67), so **git has never seen it** — `git log` on that path is empty. In a fresh container the file does not exist, and until this was fixed `munin_bridge.py wakeup` — the first command `CLAUDE.md` tells every session to run — died with `FileNotFoundError`. The ignore entry is nevertheless correct: that file is daemon-written live state, and high-frequency writes do not belong in history. Both requirements are legitimate, so **the channels are split**: volatile state stays ignored, and the durable ledger is a separate, rarely-written, committed file at `.claude/continuity/ledger.json`.

**What it stores is the complement of git.** git already holds, permanently: what changed, when, by whom, and every file's content at every point. Prose about that is redundancy, and redundancy rots into drift. So the ledger keeps only what git cannot reconstruct — `entscheidung` (why, including the rejected alternative), `sackgasse` (what was tried and failed: never committed, therefore invisible, therefore repeated — the most expensive loss), `offen`, `invariante`, `notiz`. Dropping something re-derivable from git loses nothing; that is the difference between compaction and truncation.

**Bounded by construction**, because infinite sessions need finite state. Entries age through generations (LSM/generational-GC shape): gen0 (last 2 sessions) verbatim; gen1 drops resolved `offen`/`notiz`; gen2 keeps only `invariante`/`offen`/`sackgasse` plus decisions of weight ≥ 2. Over budget, eviction runs by rank then age — but **never touches `offen` or `invariante`**: the ledger reports RISK rather than silently forgetting open work. Texts are never truncated, only whole entries dropped — half a sentence looks like knowledge and isn't.

**Anchors are recomputed, not believed** (same principle as the supervisor). Entries carry `sha:<rev>` / `path:<file>[:<line>]`; `verify` checks them and flags rot. Anything not locally checkable reports `extern`, never `ok`.

```sh
python3 scripts/munin_continuity.py resume        # session start: compressed brief
python3 scripts/munin_continuity.py capture --kind sackgasse --text "..." --anchor sha:abc123
python3 scripts/munin_continuity.py verify        # anchors + durability
python3 scripts/munin_continuity.py compact
python3 scripts/munin_continuity.py seal --push   # a session is not over until this passes
python3 scripts/munin_continuity.py handoff-prompt  # standalone prompt for the next session
```

`seal --push` is the point. **Unpushed means nonexistent** — that is how commit `29b701c` was lost, and the supervisor's `continuity` rule now reports an unpushed or rotten ledger on every run so it cannot quietly become normal.

**Dead data — cleared 2026-07-26 on Master's order.** All three rows of the former table are resolved; the supervisor rules that found them (`tracked-but-ignored`, `secret-file-tracked`, `archive-in-index`) stay in place so a relapse is caught.

| What | Removed | Measured before deletion |
|---|---|---|
| 31 files tracked despite `.gitignore` | earlier, in #74 | `git ls-files --cached -i --exclude-standard` now returns **0**. The CLAUDE.md row had been stale since #74 — recomputed, not believed. |
| `self_space_workspace_/` | 449 files, 33.5K lines | Container-mirror archives and runtime logs from 2026-07-06/08. Contained a **mirror of this repo** (`self_space_workspace_/upgraded-fiesta/`, 244 files): 110 byte-identical duplicates, **56 stale copies** including an outdated `.github/workflows/rust-ci.yml`, and one mirror-only file — an empty `main.yml` whose real counterpart had been deleted deliberately. Nothing unique was lost. |
| 16 archives ≥50K | with the above | All 16 lived under `self_space_workspace_` (2 MB `Archiv.zip`, 1.7 MB `ashell_full_environment_runtime.zip`, 14 `sys_os_mirror` tarballs). |
| `supervisor_agent.production.py` | 1404 lines | Orphan: no import, no test, no workflow referenced it; its own header calls itself `supervisor_agent.py v2.0.0` and no such file exists. It was also the sole source of the `oracle-gate-bypass` finding. |

The stale copy of the repo inside the repo was the real hazard here — a grep or a reader could land on a 56-file-deep outdated snapshot of workflows and skills and never notice.

Two follow-on leftovers went with it, both of which pointed at something that no longer existed: the `.gitignore` entry for `self_space_workspace_/.container_self_cycle_int+ext_.env`, and that same path's exemption in `security_sentinel.py`'s `KNOWN_SAFE_ENV`. The second mattered more than it looked — an allowlist entry aimed at a deleted file is not dead code but a hole, silently exempting whatever appears at that path later.

**Note on history**: `git rm` does not shrink the repository. Those blobs stay in every clone forever; removal stops the growth and the confusion, it does not undo them.

## Architecture: hm-gateway

`crates/hm-gateway` is the only real HTTP surface. It is a **hand-rolled async TCP server on raw tokio** — no axum/hyper/warp — that manually parses HTTP requests off `TcpListener`/`TcpStream`. When touching routing or request parsing, read the whole `match (method, path)` block in `main.rs`; there is no framework layer abstracting it away.

Routes (all gated by the same auth check except `OPTIONS`):
- `GET /`, `GET|/api|/gateway /health` — status/info
- `POST|GET /tasks` (+ `/api/tasks`, `/gateway/tasks`) — in-memory task registry, no persistence
- `PUT|GET|DELETE /storage/{key}` — passthrough to `hm-storage`
- `GET|POST /memory`, `POST /memory/search` — passthrough to `hm-memory`
- `GET /memory/graph` — the structural knowledge-graph seed ingested at startup from `HM_MEMORY_GRAPH_SEED_PATH`, if any; `404` if none was ingested. Kept structurally separate from free-text `/memory` records — see `hm-memory`'s `MemoryStore::ingest_graph_seed`/`graph`.
- `GET|POST /diagnostics` — opt-in diagnostics reports (see below)
- `GET|POST /sessions`, `GET|DELETE /sessions/{id}`, `POST /sessions/{id}/messages` — in-memory conversation store (`hm-sessions`), **not persisted**; see `docs/production-api-contract.md`
- `POST /chat` (+ `/api/chat`, `/gateway/chat`) — **the streaming command surface**; see below

**The chat surface (`crates/hm-gateway/src/chat.rs` + `agents/brain.py`)** is the
one place the system is commanded from, and the only streaming route. It cannot
go through `hm-plugins`: that protocol is one JSON line with a 5 s timeout, and a
local 12B answer takes minutes. So chat bypasses it deliberately — but *not* the
auth check, which was extracted into `authorized()` precisely so the streaming
path and `route_request` share one decision instead of two hand-written ones.

`agents/brain.py` is the single entry point behind it. A line starting with `/`
selects from a **fixed command table**; anything else is a question answered on
the best measured-available tier: `T0` (no model, cites repo evidence) → `T1b`
(local GGUF) → `T1` (keyless provider via the oracle gate) → `T2` (metered, only
if the cost lock is open). Same property as `hm-tool-exec`: the input *chooses*
among fixed `(program, args)` pairs, it never *builds* one, and there is no shell
anywhere in the path. Keep that property when adding commands.

**Drei Chat-Befehle logen im Container.** Das Laufzeit-Image kopiert `config/`,
`plugins/`, `scripts/`, `agents/` und Teile von `.claude/` — aber weder
`crates/` noch `Cargo.toml` noch `tests/`. Im nachgebildeten Image-Layout
gemessen: `/struktur` streamte einen rohen Python-Traceback in den Chat,
`/supervisor` meldete **„VIOLATION — 4 Befunde"**, die reine Artefakte der
fehlenden Dateien waren, und `/tests` antwortete `no tests ran in 0.00s`. Die
letzten beiden sind die gefährlicheren: sie sehen aus wie ein Ergebnis. Ein
Befund, der von einem echten Verfassungsverstoß nicht zu unterscheiden ist,
ist schlimmer als ein Absturz. `Command.braucht` nennt jetzt die Artefakte,
ohne die ein Befehl kein sinnvolles Ergebnis liefern kann; fehlen sie, sagt er
das und führt nichts aus. Der Gegentest in `tests/test_brain.py` prüft beide
Richtungen — die Absage *und* dass `/status`, das nur `scripts/` braucht,
unverändert läuft.

**Anthropic is one rung on that ladder, not a prerequisite.** `tests/test_brain.py`
runs the brain with every `ANTHROPIC*` variable stripped from the environment and
requires a real answer — a claim of independence that only lives in prose is not a
claim, it is a hope.

**The whole dispatch path was dead, and nothing said so.** `POST /tasks` bound
its field as `taskType`; `hm-cli`, `hm-cron` and all four channel crates sent
`task_type`. With `#[serde(default)]` that mismatch yields an empty string
rather than a parse error, so the gateway answered `202 accepted: true` and
dispatched to no plugin. Measured on a live gateway before the fix: **all six
cron jobs and every CLI submission ran nothing**, with no error anywhere. Every
crate had tests, all of them passed, because each side was only ever checked
against itself — the defect lived precisely in the gap between them.

The request type is now `hm_sdk::TaskSubmission`, shared by producer and
consumer instead of re-declared per crate, with `alias = "task_type"` for
clients outside this repository that a rename cannot reach. `hm-sdk` was the
one crate this file called "genuinely a stub"; owning the second wire protocol
is what it is for. **`crates/hm-gateway/tests/wire_contract.rs`** spawns the
real binary and asserts over a real socket that the plugin received the task
type — it imports nothing from the gateway, deliberately. Counter-checked:
removing the alias makes exactly that test fail.

Two consequences worth keeping: an empty `taskType` is now **400**, not an
accepted `"unspecified"` that could never match a plugin; and every response
carries `dispatch` (`plugin_dispatched` | `unhandled`, the latter with
`dispatch_reason`). "Nothing ran" used to be expressed only by the *absence*
of `plugin_result`.

Turning the six cron jobs on for the first time exposed two more defects they
had never been able to reach:

- **`plugins/autonomy_pulse_plugin.py` corrupted its own protocol line.**
  `autonomy_core._log()` writes to *stdout*, and `heal()`/`reflect()` call it.
  hm-plugins reads the first stdout line, so `[20:23:20] heal: Verzeichnis
  erstellt: diagnostics` arrived instead of the response — serde reads `[…]`
  as a sequence whose first element `20` fails against `ok: bool`, which is
  the live message `invalid type: integer`. It fires exactly when the
  self-healing actually heals something. Fixed by separating the channels
  (`contextlib.redirect_stdout(sys.stderr)`), not by removing the logging.
- **`ops-tool` only existed in release builds.** `config/plugins.json` names
  `target/release/hm-tool-exec`, which the container image provides and no
  debug build does; both `ops-tool` cron jobs failed every six hours.
  `PluginRegistry::resolve_program` now falls back to the sibling build
  profile, and only for genuinely absent `target/<profile>/` paths.

**Auth model (`hm-auth`)**: every route requires `Authorization: Bearer <HM_OWNER_TOKEN>`. The gateway process **refuses to start** if `HM_OWNER_TOKEN` is unset (fail-closed), unless `HM_GATEWAY_ALLOW_NO_AUTH=true` is explicitly set (local dev only). Token comparison is constant-time (`hm_auth::tokens_match`). Never weaken this without being asked.

**Storage model (`hm-storage`)**: `FileStorage` has two real implementations. `LocalFsStorage` is local-disk only, rooted at `HM_STORAGE_ROOT` (default `./data/storage`). `RemoteHttpStorage` persists to another host's `/storage/{key}` endpoint over a hand-rolled plain-HTTP client (no TLS, no external HTTP crate) — select it with `HM_STORAGE_BACKEND=remote` + `HM_REMOTE_STORAGE_URL`; `hm-gateway` fails to start rather than silently falling back to local disk if that's misconfigured. `AppState.storage` and `MemoryStore` are generic over `Arc<dyn FileStorage>`, so this required no changes to either beyond the trait object type. `docker-compose.yml` declares `postgres`/`redis` services, but **no crate in the workspace actually connects to either** — grep confirms zero references to `sqlx`/`tokio_postgres`/`redis` in `crates/`. Don't assume the database layer is wired up; it isn't yet.

**Persistenz: ein beschädigter Zustand war stiller Datenverlust.** Zwei
Fehler griffen ineinander und wurden beide live reproduziert:

`LocalFsStorage::put` schrieb mit `fs::write` — erst kürzen, dann schreiben.
Ein Absturz, `SIGKILL`, OOM oder eine volle Platte dazwischen hinterlässt eine
halb geschriebene Datei. Das ist hier kein Randfall: `MemoryStore` persistiert
bei *jedem* `remember()`, und `hm-agent` schreibt pro dispatchtem Task einen
Eintrag. Jetzt: Temp-Datei im selben Verzeichnis, `sync_all`, dann `rename` —
auf POSIX atomar. Der Zähler im Temp-Namen ist nötig, weil zwei gleichzeitige
Puts auf denselben Key sich sonst die Datei teilen und eine aus zwei Hälften
zusammengesetzte Datei entstehen kann.

`MemoryStore::load` las das dann mit `serde_json::from_slice(&bytes)
.unwrap_or_default()` und `Err(_) => default()`. **Gemessen**: drei Records,
Datei auf 4000 von 7348 Bytes gekürzt, Neustart → Gateway startet normal,
protokolliert nichts, `GET /memory` liefert 0 Records, und der nächste
Schreibvorgang überschreibt die Datei. Die drei Records sind weg, ohne eine
einzige Fehlermeldung. „Noch nichts gespeichert" und „gespeichert, aber
unlesbar" sind verschiedene Antworten und dürfen nicht zusammenfallen — auch
ein fehlgeschlagener `exists`-Aufruf ist kein „nicht vorhanden", sondern bei
`RemoteHttpStorage` ein nicht erreichbarer Host. Jetzt startet das Gateway
nicht, nennt die Datei und lässt sie unangetastet, damit sie noch da ist. Das
ist dieselbe fail-closed-Regel wie beim Owner-Token.

**Plugins (`hm-plugins` + `hm-sdk`)**: task types are dispatched to external subprocesses declared in `config/plugins.json`. Each invocation writes one line of JSON (`PluginRequest`) to the child's stdin and reads one line back (`PluginResponse`) with a 5s timeout. `plugins/echo_plugin.py` is a minimal example; `plugins/llm_chat_plugin.py` (task_type `llm-chat`) is a real-but-unverified scaffold that calls a generic OpenAI-compatible completions API -- it refuses loudly unless `HM_LLM_ENABLE=true` plus `HM_LLM_API_URL`/`HM_LLM_API_KEY`/`HM_LLM_MODEL` are all explicitly set, and has only been tested against a hermetic local mock server (`tests/test_llm_chat_plugin.py`), never a real LLM API -- see `docs/xcloud-platform-plan.md` Phase 4 before assuming otherwise.

**Agent runtime (`hm-agent`)**: `POST /tasks` routes through `hm_agent::Agent::dispatch`, not directly against `hm-plugins`. `Agent::dispatch` invokes the matching plugin (if any) *and* records a one-line summary of every outcome — dispatched or unhandled — into `hm-memory`, so `GET /memory` shows a durable task history, not just what was explicitly `POST`ed there. This is the real `Gateway -> Agent Runtime -> Memory` link from `docs/architecture.md`.

Env vars the gateway reads (defaults in `docs/production-api-contract.md`): `HM_GATEWAY_BIND`, `HM_ZERO_STAKED`, `HM_STORAGE_ROOT`, `HM_MEMORY_KEY`, `HM_OWNER_TOKEN`, `HM_GATEWAY_ALLOW_NO_AUTH`, `HM_DIAGNOSTICS_KEY`, `HM_MEMORY_GRAPH_SEED_PATH`.

**Shutdown/persistence**: the accept loop handles `SIGTERM`/`SIGINT` via `tokio::select!`, drains in-flight connections (10s deadline), and exits 0 — required for `deploy/hm-gateway.service` (a hardened systemd unit: `Restart=on-failure`, dropped capabilities, resource limits, non-root user) to manage it as a persistent service. `scripts/hm_gateway_watchdog.py` + `deploy/hm-gateway-watchdog.timer` cover the gap systemd's own crash-restart doesn't: a process that's alive but hung. Verify any edits to the `.service`/`.timer` files with `systemd-analyze verify`, since that's the only way to actually validate them (no systemd daemon runs in a normal dev sandbox).

**Observability/abuse protection**: every request (including rejected ones) emits one structured JSON audit line to stdout before any real work happens, and a per-IP `RateLimiter` (fixed window, `HM_RATE_LIMIT_PER_MINUTE`, default 120/min, `0` disables) rejects with `429` before the request is even read off the socket. Both are in-process/per-instance only — there is no shared rate-limit state or centralized log aggregation across multiple gateway instances; see `docs/xcloud-platform-plan.md` Phase 5 for where multi-instance concerns are tracked instead of quietly assumed solved here.

**Fixed: every submitted task was silently discarded.** `TaskInput` accepted
only `taskType`; `hm-cron`, `hm-cli tasks submit` and all four channel crates'
`forward_to_gateway` send `task_type`. serde dropped the unknown field, the type
fell back to empty, the gateway substituted `"unspecified"` — and answered
`202 accepted`. Measured on a live gateway: all six cron jobs landed as
`task 'unspecified' unhandled: no plugin registered`, on every run, while both
sides reported success. The field now carries `alias = "task_type"`, and a
missing type is refused with `400` instead of renamed: inventing a value turned
a caller's mistake into an accepted task that could never dispatch. Fixing the
callers instead would have meant finding every one of them, and a missed one
fails exactly as silently.

Dispatch working immediately exposed two things it had been hiding: the
`ops-tool` entry in `config/plugins.json` points at `target/release/hm-tool-exec`,
so it fails in a debug checkout and works only in the container (which copies
the release binary); and `plugins/autonomy_pulse_plugin.py` could put invalid
JSON on the wire, because Python writes bare `NaN`/`Infinity` literals for
non-finite floats. That plugin now serialises with `allow_nan=False` and fails
loudly instead — on the wire it had surfaced as `invalid number at line 1`,
which reads like a protocol error and is a number error.

**Fixed: the cron runner used to deadlock the whole gateway.** `hm-cron`'s
`submit_task` posted to `/tasks` with **synchronous `std::net::TcpStream` and an
unbounded `read_to_string`, from inside a tokio task** — blocking I/O on the
async scheduler, aimed at the very process it was running in. Measured effect,
reproducible: with `config/cron.json` present the gateway answered **no request
at all**, permanently, from the first second; the same binary with
`HM_CRON_CONFIG` pointed at a nonexistent path served normally. It is now
`tokio::net` with a 10 s timeout, and shutdown is honoured *during* an in-flight
job as well — the counter-test in `crates/hm-cron/src/lib.rs` points a job at a
socket that accepts and never answers, then asserts that unrelated work keeps
making progress. That second defect only surfaced *because* the test was written
to check the property rather than the happy path.

**Reconciled (Wave 1, 2026-07-28)**: `deploy/fullstack-compose.yml` builds the real Rust gateway via `build: { context: ., dockerfile: Dockerfile }`; the stdlib placeholder `deploy/gateway_service.py` was deleted in Wave 1 and is no longer referenced by any compose file or install script. The root `docker-compose.yml` (via the root `Dockerfile`) is what builds and runs the gateway in single-host mode.

## Architecture: rest of the Rust workspace

**This section was measured, not remembered** (2026-07-25). An earlier revision called most of these crates "intentional placeholders"; that had drifted from reality and is corrected below. `scripts/munin_supervisor.py` re-checks these claims on every run (`doc-drift` rule) — if you change a crate, the supervisor will tell you this table is stale before anyone reads it wrong.

| Crate | `pub fn` | Tests | Reality |
|---|---|---|---|
| `hm-gateway` | 0¹ | 7 + 4 | Real. The only HTTP surface. The extra 4 are `tests/wire_contract.rs`, which drives the compiled binary over a socket. |
| `hm-vector` | 8 | 9 | Real. NSW/ANN index. Sortiert mit `total_cmp`, nicht `partial_cmp().unwrap()` — ein NaN im Index hätte `/memory/search` mit einer Panik beendet. |
| `hm-storage` | 6 | 16 | Real. Local + remote backends; `put` schreibt atomar (Temp + `fsync` + `rename`). |
| `hm-memory` | 7 | 11 | Real. `load` unterscheidet „nichts gespeichert" von „unlesbar" und startet nicht mit leerem Gedächtnis. |
| `hm-sessions` | 13 | 5 | **Real** — not a stub. |
| `hm-cli` | 0¹ | 0 | **Real CLI**, 233 lines: `GatewayClient` + `Status`/`Tasks`/`Memory`/`Storage` subcommands. |
| `hm-channel-telegram` | 7 | 2 | Inbound adapter + types. **Cannot send** — see below. |
| `hm-channel-whatsapp` / `-discord` / `-slack` | 6 / 6 / 5 | 4 / 4 / 3 | Same shape as telegram, same limitation. |
| `hm-tool-media` / `-browser` / `-web` | 3 / 2 / 2 | 4 / 3 / 5 | Thin but tested; `-web` has 10 network references. |
| `hm-tool-exec` | 0¹ | 4 | Real, allowlist-only (see above). |
| `hm-agent` | 3 | 2 | Real. Dispatch + memory write-through. |
| `hm-auth` | 3 | 10 | Real. |
| `hm-cron` | 2 | 4 | Thin — but see the note below. |
| `hm-core` | 2 | 3 | Thin. |
| `hm-plugins` | 4 | 15 | Real protocol. Tests added — see below; `resolve_program` covers the release/debug profile trap. |
| `hm-sdk` | 2 | 4 | **No longer a stub.** Owns both wire protocols: `PluginRequest`/`PluginResponse` and now `TaskSubmission`, the shared request type of `POST /tasks`. |

¹ `pub fn` 0 means the crate is a binary whose logic sits in `fn main` and private helpers, not that it is empty — read the line count next to it.

**Correction, measured 2026-07-27**: the four channel crates **cannot send**.
Their `*_api_post` functions `bail!` unconditionally with *"… requires HTTPS.
Add rustls or native-tls to this crate"* — the workspace hand-rolls plain HTTP
by design, and hand-rolling TLS is not a sane option. The row above previously
read *"Sends for real — `send_message()` opens a `TcpStream` to the Bot API"*,
which was false: it opens nothing and returns an error. The crates are real
**inbound** adapters and type definitions; that is not nothing, but it is not
sending.

Worse, the four task types `telegram-message`, `discord-message`,
`slack-message`, `whatsapp-message` pointed at `echo_plugin.py`. Posting a
Telegram message to the gateway echoed it back and sent nothing at all.

**Now connected** via `plugins/channel_send_plugin.py`: one plugin, four
channels, TLS from the Python stdlib (`urllib`) — no new Rust dependency, no
hand-rolled crypto. A channel is one table entry, not a new code path. It
refuses loudly with the token's source URL when the credential is missing,
because a channel that silently fails to send is worse than one that does not
exist: people rely on it. Tested against a hermetic local HTTP server
(`tests/test_channel_send_plugin.py`), including the case that matters most —
Slack answers HTTP 200 *with* `{"ok": false}`, so checking only the status code
reports every failure as a success.

What has **not** changed: none of the channel crates has been live-tested against a real chat platform, because that needs real bot credentials (per `AGENTS.md`'s "surface gaps" rule). "Has working transport code" and "verified to work" are different claims — the table asserts the first, not the second.

`hm-memory` (semantic-ish "remember"/"recall" store), `hm-vector`, `hm-agent` (see above), and `hm-tool-exec` are the crates with real logic. `hm-agent` used to be a stub too and, unlike the rest of this list, wasn't even a dependency of anything in the workspace — check `cargo tree` or a crate's `Cargo.toml`, not just file existence, before assuming a crate is unused.

**`hm-tool-exec`** (`crates/hm-tools/hm-tool-exec/src/main.rs`) is a real hm-plugins-protocol binary registered as the `ops-tool` task_type in `config/plugins.json`. It is deliberately **not** arbitrary command execution: `payload.operation` only ever selects one entry from a fixed, hardcoded allowlist (`gateway_status`, `gateway_logs`, `disk_usage`, `memory_usage`) — it never contributes to argv construction. If you add more allowlisted operations, keep that property: the payload must only ever choose among fixed `(program, args)` pairs, never build one.

**Fixed, live-verified**: the root `Dockerfile`'s runtime stage now installs `python3` and copies `plugins/`, `config/`, and the `hm-tool-exec` binary alongside `hm-gateway` — plugin dispatch works in the containerized deployment, not just a full checkout. Verified by actually building the image and running both `echo` and `ops-tool` through a live container (see `docs/xcloud-platform-plan.md` Phase 2); this required a locally-started `dockerd` and a temporary, uncommitted CA-trust workaround for this sandbox's TLS-intercepting proxy during `cargo build` only — the committed `Dockerfile` itself has no such workaround.

## Architecture: UI

`ui/` is a Vite + React app (`vite build` only; no dev-server script is defined in `package.json`, so `node_modules` must exist before running Vite directly). It does **not** get served by `hm-gateway` — `GET /` on the gateway returns JSON, not the UI's HTML. The UI is a separate static bundle that talks to the gateway over HTTP.

Key piece: `ui/src/endpoint-rotation.ts`. The UI is designed to fail over across multiple gateway endpoints (`primary` → `gateway-local` → `gateway-fallback`, configurable via `/platform-config.json`), health-checking each before dispatch and requiring a *recognizable* status/state/health JSON body (not just a 2xx) before trusting an endpoint as "online" — a bare 2xx from a misconfigured proxy or SPA fallback is treated as `unknown`, not `online`. The owner bearer token lives in the browser's `localStorage` (`hm_owner_token` key) and is attached to every outgoing request.

## The `ghm-core` pip package

`ghm_core/cli.py` is a real console-script CLI (`pip install -e .`), separate from the Rust CLI (`hm-cli`, which is *also* real — see the crate table above; the two are independent tools, not one real and one placeholder). Subcommands follow one hard rule established across this codebase: **anything that sends data off the machine or starts a network-reachable process must disclose exactly what it's about to do and require explicit consent before acting**, and must refuse loudly (nonzero exit + machine-readable reason) rather than silently no-op or silently act when run non-interactively without `--yes`. See `cmd_report_diagnostics` and `cmd_onboard_iphone` for the pattern; any new subcommand with similar side effects should follow it too.

- `report-diagnostics` — sends exactly four disclosed fields (`os_name`, `os_version`, `python_version`, `architecture`) to your own gateway's `/diagnostics`, gated by `HM_OWNER_TOKEN`.
- `onboard-iphone` — starts `hm-gateway` bound to `0.0.0.0:<port>` (LAN-reachable, never a public tunnel) and prints the URL + owner token to enter on an iPhone.

## Documentation map

- `docs/production-api-contract.md` — the authoritative reference for every gateway route, env var, and the `ghm-core` CLI subcommands. Update this when changing gateway behavior.
- `docs/master-dossier.html` — visual dossier (architecture, per-crate line counts, API reference); open in a browser.
- `docs/architecture.md` states the intended chain (`Gateway -> Agent Runtime -> Memory -> Channels -> Tools -> Plugins -> UI`) and, below it, which links are real vs. still placeholder — keep that table in sync when a stub crate becomes real.
- `docs/hugin-companion-hud.md` — das Anwendungsprofil hinter der PWA: der
  transparente Begleiter ueber dem iOS-Homescreen, ferngesteuert ueber den
  Gateway-Port. Beschreibt, **wofuer** `hugin/hugin.html` gebaut ist; ohne
  dieses Dokument liest sich die PWA wie ein Chatfenster ohne Anlass.
- `docs/multi-agent.md` — Claude + ChatGPT-Codex nebeneinander. Der erste
  Satz darin ist die ganze Wahrheit: *die Integrationsschicht ist lauffaehig
  und end-to-end getestet, die Anbindung an die echte Codex-Gegenstelle ist
  implementiert, aber unverifiziert* — hier liegt kein `HUGIN_OPENAI_KEY`,
  also wurde nie eine echte Codex-Antwort durch diesen Code geparst.
- `docs/xcloud-platform-plan.md` — a staged, PoC-first roadmap (external memory backends via the existing `FileStorage` trait, cloud-portable deployment, graph-enhanced memory, an actual LLM-calling plugin, multi-instance failover). A plan, not a changelog — check it before assuming any of those phases already exist.


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:970c3bf2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   bd dolt push
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->
