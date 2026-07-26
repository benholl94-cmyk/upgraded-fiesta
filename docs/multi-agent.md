# Multi-Agent-Architektur: Claude + ChatGPT-Codex

## Status in einem Satz

Die **Integrationsschicht ist lauffähig und end-to-end getestet**; die **Anbindung an die echte Codex-Gegenstelle ist implementiert, aber unverifiziert** — in dieser Umgebung liegt kein `HUGIN_OPENAI_KEY`, es wurde also nie eine echte Codex-Antwort durch diesen Code geparst.

| Bestandteil | Zustand |
|---|---|
| Protokoll (`AgentTask` / `AgentResult` / `AgentPatch`) | lauffähig, 46 Tests |
| Orchestrator, Ledger, Zustimmungspfad | lauffähig, end-to-end ausgeführt |
| Oracle-Gate-Verdrahtung (`codex-patch` Scope) | lauffähig, im Gate nachgewiesen |
| `OracleCodexAdapter` → OpenAI | **Code vollständig, Gegenstelle nie erreicht** |
| `CodexCliAdapter` → lokale `codex`-CLI | **Code vollständig, CLI nicht installiert** |

`python3 -m agents status` zeigt diesen Unterschied als Spalte `VERIFIZIERT` an. Der Verifikationsgrad steht als `VERIFIED`-Feld an der Adapterklasse, nicht nur in dieser Datei — er kann also nicht durch Doku-Drift verrutschen.

## Rollenschnitt

| | Claude | ChatGPT-Codex |
|---|---|---|
| Rolle | `orchestrator` | `executor` |
| Verantwortung | Orchestrierung, Review, Architektur, Sicherheitsprüfung | Code-Generierung, Aufgabenbearbeitung, Patch-Erstellung, strukturierte Rückmeldung |
| Entscheidet | *was* gefragt wird, *ob* ein Ergebnis angewendet wird, *welche Dateien* das Gerät verlassen | nichts — liefert Vorschläge |
| Schreibzugriff aufs Repo | über den Zustimmungspfad | **keiner** |

Codex-Patches sind Vorschläge, bis der Orchestrator sie anwendet. Das ist keine Höflichkeit, sondern die Umsetzung von `constitution.json` → `4_ExternalProviders`: *„WERKZEUG (kein Vertrauen)"*.

## Datenfluss

```
config/agents.json          Konfiguration  (welcher Agent, welcher Adapter)
        │
        ▼
Orchestrator.build_task()   explizite Dateiliste, kein Glob
        │                   → ledger: task.created
        ▼
Orchestrator.dispatch()     → ledger: task.dispatched (welche Dateien, wie viele Bytes)
        │
        ▼
AgentAdapter.execute()
        │
        ├── LoopbackAdapter        lokal, deterministisch, kein Netz
        └── OracleCodexAdapter ──► scripts/hugin_oracle.py ──► OpenAI
                                   (Sanitizing, Redaktion, Audit-Log)
        │
        ▼
parse_result()              JSON oder Fehler. Kein dritter Zustand.
        │                   → ledger: task.result, conflict.recorded
        ▼
Orchestrator.apply(consent) ohne Zustimmung: laute Verweigerung
                            → ledger: patch.applied | patch.rejected
```

## Warum über das Oracle-Gate statt direkt

Der direkte Weg zur OpenAI-API wäre kürzer und ist bewusst nicht gebaut. `CLAUDE.md` schreibt vor, dass **alle** externen Provider-Calls durch `scripts/hugin_oracle.py` laufen. Über das Gate greifen für Codex automatisch: Prompt-Sanitizing, Response-Redaktion, Längengrenzen und der Audit-Log. Ein zweiter Pfad daneben hätte diese Kontrollen umgangen.

Dafür war ein Eingriff in Bestandscode nötig — der einzige: der neue Skill-Scope **`codex-patch`**. Begründung: alle bestehenden Scopes verbieten Repo-Inhalt (`code-review`: *„kein Kontext aus Repo"*). Ein patch-erzeugender Agent muss aber Code sehen. Der neue Scope löst das eng:

- **Gesperrt** werden *Wertzuweisungen* und echte Key-Formen (`sk-…`, `ghp_…`, `AIza…`, PEM-Header), nicht Vokabular. Ein Blocken auf das bloße Wort `token` würde jede echte Aufgabe abweisen — Code enthält es legitim als Variablennamen.
- **Sichtbar** wird nur, was der Orchestrator einzeln benannt hat. Es gibt keinen Glob und kein „nimm das Repo".
- **Nachlesbar** ist jede gesendete Datei im Ledger (`task.dispatched` → `context_files`).

## Nutzung

```sh
python3 -m agents status                      # wer ist bereit, wer ist verifiziert

python3 -m agents run codex \                 # Aufgabe stellen
    --id fix-nsw-backscore --kind fix \
    --instruction "Behebe den Backscoring-Bug: i == new_idx muss vor dem push geprüft werden." \
    --file crates/hm-vector/src/lib.rs \
    --constraint "keine neuen Abhängigkeiten" \
    --out /tmp/ergebnis.json

python3 -m agents run codex ... --dry-run     # nur den Prompt zeigen, nichts senden
python3 -m agents apply /tmp/ergebnis.json --yes
python3 -m agents ledger --task fix-nsw-backscore
```

`run` wendet nie etwas an. Ohne `--yes` verweigert `apply` laut und schreibt `patch.rejected` ins Ledger — kein stilles No-Op.

## Codex scharfschalten

```sh
export HUGIN_OPENAI_KEY=...     # lokal setzen, niemals committen
python3 -m agents status        # codex muss auf BEREIT=ja springen
```

Alternativ die lokale CLI: `enabled: true` für `codex-local` in `config/agents.json`.

Beim ersten echten Lauf ist mit **Formatfehlern** zu rechnen: `parse_result()` lehnt alles ab, was nicht dem Schema entspricht, statt zu raten. Das ist Absicht — ein Parser, der kaputte Antworten repariert, verdeckt genau die Fälle, in denen der Agent die Aufgabe nicht verstanden hat. Der Rohtext steht in der `--out`-Datei unter `raw`.

## Verbleibende Integrationsgrenzen

1. **Keine echte Codex-Antwort verarbeitet.** Ohne Key wurde der Pfad `GATE.query → parse_result` nie mit echtem Modelloutput durchlaufen. Ob Codex das Schema zuverlässig einhält, ist damit unbekannt.
2. **Keine Diff-Patches.** `AgentPatch` überträgt den vollständigen Dateiinhalt, nicht ein Unified Diff. Robuster gegen Kontextdrift, aber teuer bei großen Dateien.
3. **Kein Rückkanal für Nachfragen.** Ein Durchlauf ist eine Runde. Mehrrundige Klärung zwischen den Agenten gibt es nicht.
4. **`codex-local` ungetestet** — keine `codex`-CLI in dieser Umgebung, deshalb standardmäßig deaktiviert.
5. **Kein automatischer Merge-Konflikt-Umgang.** Patches überschreiben; die Vorfassung landet als `.bak` neben der Datei und im Ledger.

## Ist Codex jetzt technisch im Repo verankert?

**Ja für die Schicht, nein für die Gegenstelle.** Konkret verankert sind: Konfigurationseintrag, Adapterklasse, Skill-Scope im Sicherheitsgate, Aufgaben- und Antwortformat, Ausführungsweg, Ledger, CI-Prüfung, 46 Tests. Ein Providerwechsel ist ein Eintrag in `config/agents.json`.

Nicht verankert ist ein **bewiesener Durchlauf mit echtem Codex** — das braucht einen Key und eine erste reale Antwort. Bis dahin ist es korrekt, von einer *fertigen Integrationsschicht mit unverifizierter Gegenstelle* zu sprechen, nicht von einer verifizierten Integration.
