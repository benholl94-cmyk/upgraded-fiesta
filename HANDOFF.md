# HANDOFF — offene Punkte für die nächste Sitzung

Stand: 2026-07-26. Zweck dieser Datei: was offen ist, steht im Workspace und
nicht im Sitzungsgedächtnis. Beide Punkte unten sind am Code nachgemessen,
nicht erinnert.

---

## 1. Auto-Rollback: `unknown` muss `HOLD` sein, bevor es wieder nach main darf

**Status: Workflow ist derzeit nicht aktiv — er hat sich selbst entfernt.**

Eingeführt in `4b9c078` (#77), zurückgenommen in `7d812c4`. Autor des
Reverts: `Auto-Rollback <noreply@anthropic.com>` — der Workflow hat den
Commit revertiert, der ihn eingeführt hat. Entfernt wurden dabei:

```
.github/workflows/auto-rollback.yml   103 Zeilen
scripts/auto_rollback.py              189
scripts/auto_rollback_ctx.py           84
tests/test_auto_rollback.py           231
.env.production.example                 7
docs/production-api-contract.md        15
```

Die Dateien sind über `git show 4b9c078:<pfad>` weiterhin lesbar.

### Der Defekt

`decide()` in `scripts/auto_rollback.py` hat vier Sperren. Sperre 2 fragt:

```python
if ctx.previous_conclusion == "failure":
    return Decision(HOLD, "Schon der Vorgaengercommit war rot. ...")
```

Der Kontextsammler kann das Vorgängerergebnis aber gar nicht immer
bestimmen. `scripts/auto_rollback_ctx.py` liefert dann `"unknown"`:

```python
return "unknown"                                        # Zeile 23
return ci[0]["conclusion"] if ci else "unknown"         # Zeile 25
"previous_conclusion": os.environ.get("PREV_CONCLUSION", "unknown").strip()
```

`"unknown"` ist nicht `"failure"`, fällt also durch Sperre 2 hindurch und
läuft weiter Richtung `REVERT`. Verschärfend: `Context.previous_conclusion`
hat den Default `"success"` — wo nichts bekannt ist, nimmt der Code das
günstigste Ergebnis an.

Das ist die falsche Richtung. „Ich weiß nicht, ob der Vorgänger grün war"
ist genau der Zustand, in dem ein automatischer Revert fremde Arbeit
verwerfen kann, ohne etwas zu heilen. Unwissen muss anhalten, nicht
durchwinken.

### Was zu tun ist, bevor der Workflow wieder scharf geschaltet wird

- `decide()`: alles außer einem explizit bestätigten `"success"` beim
  Vorgänger → `HOLD` mit Begründung. Nicht nur `"unknown"` ergänzen —
  eine Allowlist statt einer Blockliste, sonst wiederholt sich der Fehler
  beim nächsten neuen Statuswert (`cancelled`, `skipped`, `timed_out`).
- `Context.previous_conclusion`: Default von `"success"` auf `"unknown"`.
  Ein Datenobjekt darf nichts behaupten, was der Sammler nicht geliefert hat.
- Test in `tests/test_auto_rollback.py`, der genau das festnagelt: Kontext
  mit `previous_conclusion="unknown"` und ansonsten perfekten
  Revert-Bedingungen → `HOLD`.
- Schleifenschutz gegen den beobachteten Fall prüfen: Sperre 1 fängt
  `Revert "..."` im Subject ab, hat aber nicht verhindert, dass der
  Workflow seinen eigenen Einführungscommit zurücknimmt.

---

## 2. Gerätebindung und Konsens in TERMSHELL — unverändert offen

TERMSHELL lebt in `hugin/hugin.html` (Panel ab Zeile 609, Engine-IIFE ab
Zeile 2233, „Multi-Provider Parallel Shell Engine"). Beides fehlt dort
weiterhin — `grep -i "konsens\|consensus\|quorum\|binding"` über die Datei
findet nichts Einschlägiges.

### Konsens

Prior Art existiert bereits und sollte nicht zweitimplementiert werden:
`agents/consensus.py` (#75, `84f1788`) mit `evaluate()`, `threshold()`,
`extract_facts()`, `ConsensusReport`, `Divergence`. Zwei Ebenen, Fakten
gewichtet 65:35 gegen Textähnlichkeit, Konsens aus einem Anbieterhaus zählt
nicht als unabhängige Bestätigung.

Offene Frage, die zuerst zu klären ist: TERMSHELL ist eine Single-File-PWA
ohne Build und ohne Server, `agents/consensus.py` ist Python. Die Logik muss
also entweder nach JS portiert werden (Duplikat, das driftet) oder TERMSHELL
ruft sie über das Gateway auf (Netzabhängigkeit in einem Teil, der bisher
offline funktioniert). Das ist eine Architekturentscheidung, keine
Implementierungsdetailfrage — vor dem Code entscheiden.

### Gerätebindung

Vorhandenes Muster in derselben Datei: FNV-1a-Siegel, Dual-Slot A/B,
fail-closed (ab Zeile 741), Token in `localStorage` unter `KEY_TOKEN` /
`KEY_SEALED`. Das bindet den Schlüssel an den Browser-Origin, nicht an das
Gerät — wer den `localStorage`-Inhalt kopiert, hat ihn.

Zu klären, bevor etwas gebaut wird: was „Gerät" hier heißen soll. Ohne
Server gibt es keine Attestierung; alles, was rein im Browser läuft, ist
gegen jemanden mit Zugriff auf das Gerät nicht durchsetzbar. Realistisch
sind eine WebAuthn-/Passkey-Bindung (setzt Nutzerinteraktion und
Plattformunterstützung voraus) oder eine Gateway-seitige Bindung an
`HM_OWNER_TOKEN` plus Geräte-ID. Die Zugriffsverengung aus #76 (`8149bcb`,
CORS-Allowlist, `HM_GATEWAY_ALLOW_NO_AUTH` nur auf Loopback) ist der
Anknüpfungspunkt auf Gateway-Seite.

---

## Hinweis zur Entstehung

Ein früherer Commit `29b701c` mit dieser Datei existiert nicht mehr — er
wurde in einem Container erstellt, der neu aufgesetzt wurde, und nie
gepusht. Diese Fassung ist eine Rekonstruktion aus den beiden Stichpunkten,
mit am Code nachgemessenen Details statt erinnerten.

Merke fürs nächste Mal: Ein Commit, der nicht gepusht ist, existiert nur
solange der Container lebt.
