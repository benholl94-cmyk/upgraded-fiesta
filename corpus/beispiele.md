# Korpus — Auszuege

Erzeugt von `scripts/hugin_corpus.py`. Nicht von Hand aendern: der naechste Bau ueberschreibt die Datei.

## begruendung — 254 Faelle

**scripts/release_notes.py:scripts/release_notes.py** · `scripts/release_notes.py`

```
release_notes.py -- die Release-Notiz wird aus dem Manifest gerechnet.

## Warum nicht von Hand geschrieben

Eine Release-Notiz ist die Stelle, an der ein Projekt behauptet, was es kann.
Von Hand geschrieben ist sie eine Erinnerung an den Zustand zum Zeitpunkt des
Schreibens — und veraltet ab dem naechsten Bau, ohne dass jemand es merkt.
Genau diese Sorte Drift hat hier schon die Krate-Tabelle in `CLAUDE.md`
erwischt (*"intentional placeholders"*, waehrend die Kraten laengst echt
waren) und die Zeile *"31 Dateien getrackt trotz .gitignore"*, die lange nach
dem Aufraeumen noch dastand.

Diese N …
```

**tests/test_meta_guards.py:test_guard_catches_a_command_running_without** · `tests/test_meta_guards.py`

```
Defekt: `Command.braucht` wird geleert.

Dann läuft ein Chat-Befehl im Laufzeit-Image wieder los, dem `crates/`
oder `tests/` fehlt — und antwortet mit einem Traceback, einem
Schein-VIOLATION oder einer leeren, grün wirkenden Testsuite.
```

## commit — 400 Faelle

**Update visible monitoring report** · `sha:003ab8c`

```
Update visible monitoring report
```

**Update visible monitoring report** · `sha:0052306`

```
Update visible monitoring report
```

## doku — 147 Faelle

**Architecture: rest of the Rust workspace** · `CLAUDE.md`

```
Architecture: rest of the Rust workspace

**This section was measured, not remembered** (2026-07-25). An earlier revision called most of these crates "intentional placeholders"; that had drifted from reality and is corrected below. `scripts/munin_supervisor.py` re-checks these claims on every run (`doc-drift` rule) — if you change a crate, the supervisor will tell you this table is stale before anyone reads it wrong.

| Crate | `pub fn` | Tests | Reality |
|---|---|---|---|
| `hm-gateway` | 0¹ | 7 + 4 | Real. The only HTTP surface. The extra 4 are `tests/wire_contract.rs`, which drives the com …
```

**Phase 2 — Cloud-portable deployment (prove "standalone", not "one host** · `docs/xcloud-platform-plan.md`

```
Phase 2 — Cloud-portable deployment (prove "standalone", not "one host")

**Goal**: the same `hm-gateway` binary + systemd unit from Phase 0 runs
unmodified on at least two different hosting substrates, proving it's not
accidentally coupled to this dev sandbox.

**What shipped this round — worked, only sub-workstep 2**: the
`Dockerfile`'s runtime stage now installs `python3` and copies `config/`,
`plugins/`, and the `hm-tool-exec` binary alongside `hm-gateway`, closing the
previously-documented packaging gap. **Live-verified, not just inspected**:
this sandbox has no Docker daemon by default,  …
```

## ledger-entscheidung — 16 Faelle

**Verfassungslockerung A1: Mandatsgrenze verlaeuft entlang Umkehrbarkeit** · `.claude/continuity/ledger.json`

```
Verfassungslockerung A1: Mandatsgrenze verlaeuft entlang Umkehrbarkeit und Reichweite, nicht entlang der Art der Handlung. Verworfene Alternative: die Verbote ersatzlos streichen — das haette die Pruefung dort mitentfernt, wo sie etwas bedeutet (Default-Branch, Historie, Loeschen, Secrets). Gelockert wurde nur, was umkehrbar und ohne Aussenwirkung ist.
```

**Toter Baum self_space_workspace_ (449 Dateien) und die Waise superviso** · `.claude/continuity/ledger.json`

```
Toter Baum self_space_workspace_ (449 Dateien) und die Waise supervisor_agent.production.py (1404 Zeilen) auf Master-Befehl entfernt. Gefahr war nicht die Groesse, sondern die Spiegelkopie des Repos darin: 56 der 244 Dateien waren VERALTETE Fassungen echter Dateien, u.a. .github/workflows/rust-ci.yml. Vor dem Loeschen byteweise verglichen — 110 identisch, 56 veraltet, 1 nur im Spiegel (leere main.yml, im echten Baum bewusst geloescht). Nichts Einzigartiges verloren.
```

## ledger-invariante — 22 Faelle

**Ungepusht heisst nicht vorhanden. Ein Commit lebt nur solange sein Con** · `.claude/continuity/ledger.json`

```
Ungepusht heisst nicht vorhanden. Ein Commit lebt nur solange sein Container lebt — so ging 29b701c verloren. Jede Sitzung endet mit 'seal --push', sonst ist sie nicht beendet.
```

**Ein Prompt, der wiederkehrend feuert, darf keinen Zustand enthalten, d** · `.claude/continuity/ledger.json`

```
Ein Prompt, der wiederkehrend feuert, darf keinen Zustand enthalten, der altern kann: kein Branchname, kein Projektstand, keine offenen Punkte. Alles davon kommt aus dem Ledger. Der Prompt beschreibt nur das Verfahren.
```

## ledger-sackgasse — 21 Faelle

**Die Mandatswache mit any() ueber lose Stichwoerter zu bauen scheitert:** · `.claude/continuity/ledger.json`

```
Die Mandatswache mit any() ueber lose Stichwoerter zu bauen scheitert: MANDATE_BAR pruefte ('merge','push','default-branch'), und weil 'push' auch in 'force-push' steckt, blieb eine entfernte Default-Branch-Schranke unbemerkt. Nur der Gegentest hat es aufgedeckt, nicht das Lesen. Richtig ist all() ueber unterscheidende Stichwoerter.
```

**MCP-'requires approval' laesst sich NICHT ueber .claude/settings.json ** · `.claude/continuity/ledger.json`

```
MCP-'requires approval' laesst sich NICHT ueber .claude/settings.json permissions.allow aufloesen — jedenfalls nicht in einer laufenden CCR-Remote-Sitzung. Nach Eintrag beider Serveraliasse blieb update_trigger weiterhin abgelehnt. Gegenprobe, die es beweist: munin_continuity.py lief die ganze Zeit OHNE Allowlist-Eintrag, die Bash-Allowlist gatet hier also gar nicht. MCP-Approval kommt aus der Session-Policy des Harness, nicht aus den Projekt-Settings. Vermutung, ungeprueft: nur per Neustart oder gar nicht aus dem Repo steuerbar.
```

## rustdoc — 72 Faelle

**Fügt einen Vektor ein oder ersetzt einen bestehenden Eintrag gleicher ** · `crates/hm-vector/src/lib.rs`

```
Fügt einen Vektor ein oder ersetzt einen bestehenden Eintrag gleicher ID
(Upsert). `vector` muss L2-normiert sein — vorzugsweise via `embed()`.

Diese Vorbedingung ist eine Bitte an den Aufrufer, keine Garantie:
`insert` nimmt rohe `f32` entgegen. Deshalb vergleichen alle
Sortierungen im Index mit `total_cmp` statt `partial_cmp().unwrap()`.
`partial_cmp` liefert bei NaN `None`, und das `unwrap()` darauf hätte
die Anfrage mit einer Panik beendet — im Request-Pfad von
`/memory/search`, wo der Aufrufer nur eine abgebrochene Verbindung
sieht. `total_cmp` ist eine totale Ordnung über alle `f32` und …
```

**Writes atomically: a temporary file in the same directory, flushed and** · `crates/hm-storage/src/lib.rs`

```
Writes atomically: a temporary file in the same directory, flushed and
fsync'd, then `rename`d over the target.

`fs::write` truncates first and writes after, so a crash, `SIGKILL`,
OOM kill or full disk in between leaves a **half-written file** — valid
as bytes, invalid as JSON. That is not theoretical here: `MemoryStore`
persists on every `remember()`, and `hm-agent` records a memory entry
for every dispatched task, so this window is entered constantly.

Reproduced before the fix: truncating the memory state to 4000 of 7348
bytes made the gateway start normally, report zero records, and dest …
```

