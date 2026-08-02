#!/usr/bin/env python3
"""munin_continuity.py -- Sitzungsgedächtnis, das den Container überlebt.

Das Problem, gegen das diese Datei gebaut ist, ist gemessen und nicht
vermutet: `.claude/persona/munin-state.json` steht in `.gitignore` (Zeile 67).
git hat sie nie gesehen. Jeder neue Container startet ohne Zustand, und
`munin_bridge.py wakeup` bricht ab. Ein Commit, der nicht gepusht ist,
existiert nur solange der Container lebt -- genau so ging `29b701c` verloren.

Der Ignore-Eintrag ist trotzdem richtig: die Datei ist Live-Zustand, den ein
Daemon fortschreibt, und hochfrequenter Schreibverkehr gehört nicht in die
History. Beide Anforderungen sind berechtigt, also werden die Kanäle getrennt:
flüchtiger Zustand bleibt ignoriert, das Kontinuitäts-Ledger hier ist eine
eigene Datei, wird selten geschrieben und committet.

KOMPRESSIONSPRINZIP -- gespeichert wird das Komplement von git
--------------------------------------------------------------
git speichert bereits vollständig und dauerhaft: was sich geändert hat, wann,
durch wen, und den Inhalt jeder Datei zu jedem Zeitpunkt. Prosa darüber ist
Redundanz, und Redundanz verrottet zu Drift. Das Ledger hält deshalb nur, was
git *nicht* rekonstruieren kann:

  entscheidung  Warum so und nicht anders. git zeigt das Was, nie das
                verworfene Alternativ.
  sackgasse     Was versucht wurde und scheiterte. Wird nie committet, ist
                daher unsichtbar, wird daher wiederholt. Der teuerste
                Verlust und der am häufigsten verlorene.
  offen         Noch nicht im Code, per Definition nicht ableitbar.
  invariante    Regel, die dauerhaft gilt.
  notiz         Alles andere; zuerst entsorgt.

Wer etwas fallen lässt, das aus git ableitbar ist, verliert nichts. Das ist
der Unterschied zwischen Verdichtung und Abschneiden.

ANKER STATT PROSA
-----------------
Jeder Eintrag darf auf git zeigen (`sha:`, `path:datei:zeile`, `test:`).
`verify` rechnet diese Anker nach, statt ihnen zu glauben -- dasselbe Prinzip,
nach dem `munin_supervisor.py` arbeitet. Ein Gedächtnis, das still auf nichts
zeigt, ist schlimmer als keines, weil man ihm ansieht, dass es existiert, aber
nicht, dass es leer ist.

GENERATIONEN -- weshalb der Zustand endlich bleibt
--------------------------------------------------
Unendliche Sitzungen brauchen beschränkten Zustand, sonst frisst der Kontext
sich selbst. Einträge altern über Generationen (Vorbild: LSM-Bäume und
generationelle GC), und bei jedem Übergang fällt weg, was git bereits hält:

  gen0  letzte 2 Sitzungen        alles, wörtlich
  gen1  bis 8 Sitzungen zurück    erledigte `offen`/`notiz` fallen weg
  gen2  älter                     nur invariante, offen, sackgasse, und
                                  entscheidungen ab Gewicht 2

Reicht das nicht unter das Byte-Budget, wird nach Rang und Alter verdrängt --
aber `offen` und `invariante` niemals. Lieber meldet das Ledger RISK, als
still zu vergessen, was noch offen ist. Texte werden bewusst *nicht*
abgeschnitten: ein halber Satz sieht aus wie Wissen und ist keins.

    python3 scripts/munin_continuity.py resume            # Sitzungsstart
    python3 scripts/munin_continuity.py capture --kind offen --text "..." \
        --anchor path:scripts/auto_rollback.py:112
    python3 scripts/munin_continuity.py resolve s12-3
    python3 scripts/munin_continuity.py verify            # Anker nachrechnen
    python3 scripts/munin_continuity.py compact
    python3 scripts/munin_continuity.py seal --push       # dauerhaft machen
    python3 scripts/munin_continuity.py handoff-prompt    # Prompt der Folgesitzung

Exit: 0 sauber, 1 Aufmerksamkeit nötig (verrottete Anker, ungepusht, Budget).
"""

from __future__ import annotations

# Strukturiertes Logging (Plan B.3). Idempotent -- mehrfach
# aufgerufen waere ein No-Op, weil `_configure_once()` einen
# Flag abfragt, bevor sie Handler anhaengt.
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PARENT = _os.path.dirname(_HERE)
_SCRIPTS = _os.path.join(_PARENT, 'scripts')
if _SCRIPTS not in _sys.path:
    _sys.path.insert(0, _SCRIPTS)
from _log import get_logger
log = get_logger(__name__)

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEDGER_F = REPO / ".claude" / "continuity" / "ledger.json"

VERSION = 1

# Einträge nach Wert. Die Reihenfolge ist die Verdrängungsreihenfolge von
# unten: `notiz` geht zuerst, `offen` und `invariante` gehen nie.
KIND_RANK = {
    "invariante": 4,
    "offen": 4,
    "sackgasse": 3,
    "entscheidung": 2,
    "notiz": 0,
}
KINDS = tuple(KIND_RANK)
UNDROPPABLE = ("offen", "invariante")

GEN0_AGE = 2      # Sitzungen zurück, in denen alles wörtlich bleibt
GEN1_AGE = 8      # danach gen2
DEFAULT_BUDGET = 32_768   # Bytes serialisiertes Ledger

HOT, WARM, COLD = 0, 1, 2


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(("git", *args), cwd=REPO, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------


@dataclass
class Entry:
    id: str
    session: int
    ts: str
    kind: str
    text: str
    anchors: list[str] = field(default_factory=list)
    state: str = "offen"          # offen | erledigt
    weight: int = 1

    @property
    def rank(self) -> int:
        return KIND_RANK.get(self.kind, 0)

    @property
    def droppable(self) -> bool:
        if self.kind in UNDROPPABLE and self.state != "erledigt":
            return False
        return True

    @classmethod
    def from_dict(cls, d: dict) -> Entry:
        return cls(
            id=str(d.get("id", "")),
            session=int(d.get("session", 0)),
            ts=str(d.get("ts", "")),
            kind=str(d.get("kind", "notiz")),
            text=str(d.get("text", "")),
            anchors=[str(a) for a in d.get("anchors", [])],
            state=str(d.get("state", "offen")),
            weight=int(d.get("weight", 1)),
        )


@dataclass
class Ledger:
    version: int = VERSION
    updated: str = ""
    session: int = 1              # laufende Sitzungsnummer
    entries: list[Entry] = field(default_factory=list)

    # -- Persistenz ---------------------------------------------------------

    @classmethod
    def load(cls) -> Ledger:
        if not LEDGER_F.is_file():
            return cls(updated=now_iso())
        try:
            raw = json.loads(LEDGER_F.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Ein kaputtes Ledger wird gemeldet, nicht stillschweigend
            # überschrieben -- Überschreiben wäre der zweite Datenverlust.
            raise SystemExit(f"Ledger unlesbar: {LEDGER_F}")
        return cls(
            version=int(raw.get("version", VERSION)),
            updated=str(raw.get("updated", "")),
            session=int(raw.get("session", 1)),
            entries=[Entry.from_dict(e) for e in raw.get("entries", [])],
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "version": self.version,
                "updated": self.updated,
                "session": self.session,
                "entries": [asdict(e) for e in self.entries],
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n"

    def save(self) -> None:
        self.updated = now_iso()
        LEDGER_F.parent.mkdir(parents=True, exist_ok=True)
        tmp = LEDGER_F.with_suffix(".tmp")
        tmp.write_text(self.to_json(), encoding="utf-8")
        os.replace(tmp, LEDGER_F)

    # -- Abfragen -----------------------------------------------------------

    @property
    def size(self) -> int:
        return len(self.to_json().encode("utf-8"))

    def next_id(self) -> str:
        n = 1 + sum(1 for e in self.entries if e.session == self.session)
        return f"s{self.session}-{n}"

    def open_entries(self) -> list[Entry]:
        return [e for e in self.entries if e.state != "erledigt"]

    def by_kind(self, kind: str) -> list[Entry]:
        return [e for e in self.entries if e.kind == kind]

    def generation(self, e: Entry) -> int:
        age = self.session - e.session
        if age <= GEN0_AGE:
            return HOT
        if age <= GEN1_AGE:
            return WARM
        return COLD


# ---------------------------------------------------------------------------
# Verdichtung
# ---------------------------------------------------------------------------


def compact(led: Ledger, budget: int = DEFAULT_BUDGET) -> tuple[list[str], bool]:
    """Generationelle Verdichtung. Gibt (Protokoll, budget_eingehalten) zurück.

    Reine Funktion auf dem Ledger-Objekt -- schreibt nicht. Der Aufrufer
    entscheidet, ob das Ergebnis gespeichert wird.
    """
    log: list[str] = []
    keep: list[Entry] = []

    for e in led.entries:
        gen = led.generation(e)

        if gen == HOT:
            keep.append(e)
            continue

        if gen == WARM:
            # Erledigte Fragen und Notizen stehen jetzt in git.
            if e.state == "erledigt" and e.kind in ("offen", "notiz"):
                log.append(f"gen1 verworfen (in git ableitbar): {e.id} {e.kind}")
                continue
            keep.append(e)
            continue

        # COLD -- nur noch, was git prinzipiell nicht hergibt.
        if e.kind in ("invariante", "offen", "sackgasse") and e.state != "erledigt":
            keep.append(e)
        elif e.kind == "entscheidung" and e.weight >= 2:
            keep.append(e)
        else:
            log.append(f"gen2 verworfen: {e.id} {e.kind}/{e.state}")

    led.entries = keep

    # Byte-Budget: verdrängen nach Rang, dann Alter. Offene Punkte und
    # Invarianten bleiben auch dann, wenn das Budget reißt -- ein stilles
    # Vergessen offener Arbeit ist der Fehler, den dieses Modul verhindert.
    if led.size > budget:
        order = sorted(
            (e for e in led.entries if e.droppable),
            key=lambda e: (e.rank, e.session, e.ts),
        )
        for victim in order:
            if led.size <= budget:
                break
            led.entries = [e for e in led.entries if e.id != victim.id]
            log.append(f"Budget verdrängt: {victim.id} {victim.kind}")

    within = led.size <= budget
    if not within:
        log.append(
            f"Budget {budget}B überschritten ({led.size}B) — es bleiben nur "
            "offene Punkte und Invarianten. Nichts davon wird verworfen."
        )
    return log, within


# ---------------------------------------------------------------------------
# Ankerprüfung -- nachrechnen statt glauben
# ---------------------------------------------------------------------------


def _default_branch() -> str:
    r = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip().split("/", 1)[-1]
    return "main"


def _fluechtiger_sha(anchor: str) -> bool:
    """Ist dieser SHA-Anker beim Anlegen schon zum Tod verurteilt?

    **Die Wurzel der beiden toten Anker dieser Sitzung.** `s4-3` und `s4-4`
    zeigten auf `b724047`, einen Commit vom Branch zu PR #106. Beim
    Squash-Merge entsteht ein *neuer* Commit; der alte wird unerreichbar
    und irgendwann weggeraeumt. Der Anker war nicht verrottet -- er konnte
    in einem Squash-Workflow nie halten.

    Gewarnt wird beim `capture`, nicht erst beim `verify`: dort ist die
    Information noch nuetzlich, weil der Schreiber sie sofort durch einen
    `path:`-Anker ersetzen kann. Beim Verify ist der Commit schon weg und
    niemand weiss mehr, worauf er zeigte.

    Kein Abbruch: ein SHA vom Feature-Branch kann trotzdem der richtige
    Bezug sein, solange man weiss, dass er den Merge nicht ueberlebt.
    """
    if not anchor.startswith("sha:"):
        return False
    rev = anchor[4:]
    if git("cat-file", "-e", f"{rev}^{{commit}}").returncode != 0:
        return False          # existiert nicht -- das meldet verify_anchor
    zweig = _default_branch()
    r = git("merge-base", "--is-ancestor", rev, f"origin/{zweig}")
    return r.returncode != 0


def verify_anchor(anchor: str) -> tuple[str, str]:
    """Gibt (status, detail). status: ok | rot | extern."""
    if anchor.startswith("sha:"):
        rev = anchor[4:]
        if git("cat-file", "-e", f"{rev}^{{commit}}").returncode == 0:
            return "ok", ""
        # **Die Wurzel, nicht das Symptom.** Ein SHA von einem
        # Feature-Branch stirbt beim Squash-Merge: der Squash erzeugt einen
        # neuen Commit, der alte wird unerreichbar und irgendwann
        # weggeraeumt. `s4-3` und `s4-4` zeigten auf `b724047` -- einen
        # Commit aus PR #106, der genau so verschwand.
        #
        # Das ist kein Datenverlust, sondern eine Anker-Art, die in einem
        # Squash-Workflow nicht taugt. Deshalb wird hier benannt, WARUM er
        # weg ist, statt nur DASS er weg ist: nur so weiss der naechste
        # Leser, dass er den Eintrag umankern und nicht suchen muss.
        return "rot", ("Commit nicht im Repo — bei Squash-Merge verschwindet "
                       "der Feature-Branch-SHA. Auf einen Pfad umankern.")

    if anchor.startswith("path:"):
        rest = anchor[5:]
        line = None
        if ":" in rest:
            head, _, tail = rest.rpartition(":")
            if tail.isdigit():
                rest, line = head, int(tail)
        p = REPO / rest
        # `exists()`, nicht `is_file()`. Ein Anker darf auf ein VERZEICHNIS
        # zeigen: `s3-19` haelt eine Sackgasse ueber `.github/workflows`
        # als Ganzes fest -- der OAuth-Token des Codespace hat keinen
        # workflow-Scope, das betrifft jede Datei darin und keine einzelne.
        # Die vorige Fassung meldete diesen Anker als "Datei existiert
        # nicht", waehrend das Verzeichnis danebenlag. Ein falscher
        # Rot-Befund ist teurer als keiner: er trainiert das Weglesen.
        if not p.exists():
            return "rot", "Pfad existiert nicht"
        if line is not None:
            try:
                n = sum(1 for _ in p.open(encoding="utf-8", errors="replace"))
            except OSError:
                return "rot", "Datei nicht lesbar"
            if line > n:
                return "rot", f"Zeile {line} > {n} Zeilen"
        return "ok", ""

    # Anker auf Dinge außerhalb des Repos (PRs, Branches auf der Gegenseite,
    # Tests, die einen Lauf bräuchten) werden als solche gekennzeichnet statt
    # als geprüft ausgegeben.
    return "extern", "nicht lokal prüfbar"


def verify(led: Ledger) -> list[tuple[Entry, str, str, str]]:
    out = []
    for e in led.entries:
        for a in e.anchors:
            status, detail = verify_anchor(a)
            if status != "ok":
                out.append((e, a, status, detail))
    return out


# ---------------------------------------------------------------------------
# Dauerhaftigkeit -- die eigentliche Lehre aus 29b701c
# ---------------------------------------------------------------------------


def _rel_to_repo() -> str | None:
    """Ledgerpfad relativ zum Repo, oder None wenn er außerhalb liegt.

    Außerhalb des Repos ist kein Randfall, sondern der denkbar
    undauerhafteste Zustand: git kann die Datei gar nicht sehen. Das muss
    gemeldet werden, nicht als ValueError abstürzen -- eine Prüfung, die beim
    schlimmsten Fall selbst kaputtgeht, prüft ihn nicht.
    """
    try:
        return str(LEDGER_F.relative_to(REPO))
    except ValueError:
        return None


def durability() -> tuple[bool, str]:
    """Liegt der Ledger-Stand wirklich auf der Gegenstelle?

    Uncommitted oder ungepusht heißt: existiert nur solange der Container
    lebt. Das ist kein Randfall, das ist der beobachtete Verlustweg.
    """
    if not LEDGER_F.is_file():
        return False, "Ledger existiert nicht"

    rel = _rel_to_repo()
    if rel is None:
        return False, f"Ledger liegt außerhalb des Repos ({LEDGER_F}) — git sieht es nie"
    if git("diff", "--quiet", "--", rel).returncode != 0:
        return False, "Ledger hat uncommittete Änderungen"
    if git("diff", "--cached", "--quiet", "--", rel).returncode != 0:
        return False, "Ledger ist gestaged, aber nicht committet"
    if git("ls-files", "--error-unmatch", rel).returncode != 0:
        return False, "Ledger ist nicht in git — genau der Fehler von munin-state.json"

    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    up = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if up.returncode != 0:
        return False, f"Branch {branch} hat keine Gegenstelle — nichts ist gepusht"

    ahead = git("rev-list", "--count", f"{up.stdout.strip()}..HEAD").stdout.strip()
    if ahead.isdigit() and int(ahead) > 0:
        return False, f"{ahead} Commit(s) ungepusht — überlebt den Container nicht"
    return True, f"gepusht nach {up.stdout.strip()}"


def seal(push: bool) -> int:
    if not LEDGER_F.is_file():
        print("Nichts zu sichern: kein Ledger.")
        return 1

    rel = _rel_to_repo()
    if rel is None:
        print(f"Ledger liegt außerhalb des Repos ({LEDGER_F}) — nicht sicherbar.")
        return 1

    git("add", rel)
    if git("diff", "--cached", "--quiet", "--", rel).returncode != 0:
        led = Ledger.load()
        msg = (
            f"chore(continuity): Sitzung {led.session} gesichert "
            f"({len(led.open_entries())} offen, {led.size}B)"
        )
        r = git("commit", "-m", msg, "--", rel)
        if r.returncode != 0:
            print(f"Commit fehlgeschlagen: {r.stderr.strip()}")
            return 1
        print(f"✓ committet: {msg}")
    else:
        print("· Ledger unverändert, kein Commit nötig")

    if push:
        branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        r = git("push", "-u", "origin", branch)
        if r.returncode != 0:
            print(f"Push fehlgeschlagen: {r.stderr.strip()}")
            return 1
        print(f"✓ gepusht: {branch}")

    ok, detail = durability()
    print(("✓ dauerhaft: " if ok else "⚠ NICHT dauerhaft: ") + detail)
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Der Prompt, mit dem sich die Schleife selbst fortsetzt
# ---------------------------------------------------------------------------

HANDOFF_PROMPT = """\
Fortsetzung einer laufenden Arbeit in benholl94-cmyk/upgraded-fiesta.
Dein Gedächtnis liegt im Repo, nicht in diesem Prompt.

Erster Befehl, vor allem anderen:

    python3 scripts/munin_continuity.py resume

Das druckt offene Punkte, getroffene Entscheidungen, bekannte Sackgassen und
den Zustand der Anker. Danach:

1. Arbeite die offenen Punkte nach Rang ab. Verrottete Anker zuerst — sie
   heißen, dass das Gedächtnis auf etwas zeigt, das es nicht mehr gibt.
2. Halte jedes Ergebnis sofort fest, nicht am Ende:
     capture --kind entscheidung|sackgasse|offen|invariante --text "..." \\
             --anchor sha:<commit> --anchor path:<datei>:<zeile>
   Sackgassen sind Pflicht. Was scheiterte, steht in keinem Commit und wird
   sonst in der nächsten Sitzung noch einmal versucht.
3. Erledigtes schließen: resolve <id>
4. Zum Schluss, ausnahmslos:
     python3 scripts/munin_continuity.py compact
     python3 scripts/munin_continuity.py seal --push

Ungepusht heißt nicht vorhanden. Wenn seal fehlschlägt, ist die Sitzung nicht
beendet — dann ist das Ergebnis verloren, sobald der Container endet.

Gibt es keine offenen Punkte und keine verrotteten Anker, ist nichts zu tun:
das melden und aufhören. Eine leere Runde ist ein gültiges Ergebnis.
"""


# ---------------------------------------------------------------------------
# Ausgabe
# ---------------------------------------------------------------------------


def render_resume(led: Ledger, rotten: list, dur: tuple[bool, str]) -> str:
    L = []
    A = L.append
    A(f"MUNIN · Kontinuität — Sitzung {led.session}")
    A(f"  Ledger {led.size}B · {len(led.entries)} Einträge · Stand {led.updated}")
    ok, detail = dur
    A(f"  Dauerhaftigkeit: {'ok' if ok else 'ACHTUNG'} — {detail}")
    A("")

    if rotten:
        A(f"── Verrottete Anker ({len(rotten)}) — zuerst klären")
        for e, a, status, detail in rotten:
            A(f"  [{status}] {e.id} → {a}  ({detail})")
        A("")

    for kind, title in (
        ("offen", "Offene Punkte"),
        ("sackgasse", "Sackgassen — nicht noch einmal versuchen"),
        ("entscheidung", "Entscheidungen und ihr Grund"),
        ("invariante", "Invarianten"),
    ):
        items = [e for e in led.by_kind(kind) if e.state != "erledigt"]
        if not items:
            continue
        items.sort(key=lambda e: (-e.weight, e.session))
        A(f"── {title} ({len(items)})")
        for e in items:
            A(f"  {e.id} · {e.text}")
            for a in e.anchors:
                A(f"       ↳ {a}")
        A("")

    if not led.entries:
        A("Ledger ist leer. Erste Sitzung — Ergebnisse mit `capture` festhalten.")
        A("")

    A("Abschluss dieser Sitzung, ausnahmslos:")
    A("  python3 scripts/munin_continuity.py compact")
    A("  python3 scripts/munin_continuity.py seal --push")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Befehle
# ---------------------------------------------------------------------------


def cmd_resume(a: argparse.Namespace) -> int:
    led = Ledger.load()
    if not a.peek:
        led.session += 1
        led.save()
    rotten = verify(led)
    dur = durability()
    if a.json:
        print(json.dumps({
            "session": led.session,
            "size": led.size,
            "durable": dur[0],
            "durability_detail": dur[1],
            "rotten": [{"id": e.id, "anchor": an, "status": s, "detail": d}
                       for e, an, s, d in rotten],
            "entries": [asdict(e) for e in led.entries if e.state != "erledigt"],
        }, ensure_ascii=False, indent=2))
    else:
        print(render_resume(led, rotten, dur))
    return 0 if (dur[0] and not rotten) else 1


def cmd_capture(a: argparse.Namespace) -> int:
    if a.kind not in KINDS:
        print(f"Unbekannte Art {a.kind!r}. Erlaubt: {', '.join(KINDS)}")
        return 1
    led = Ledger.load()
    e = Entry(
        id=led.next_id(),
        session=led.session,
        ts=now_iso(),
        kind=a.kind,
        text=a.text.strip(),
        anchors=list(a.anchor or []),
        weight=a.weight,
    )
    bad = [(an, *verify_anchor(an)) for an in e.anchors]
    fluechtig = [an for an in e.anchors if _fluechtiger_sha(an)]
    led.entries.append(e)
    led.save()
    print(f"✓ {e.id} [{e.kind}] {e.text[:70]}")
    for an, status, detail in bad:
        if status == "rot":
            print(f"  ⚠ Anker zeigt ins Leere: {an} ({detail})")
    for an in fluechtig:
        print(f"  ⚠ {an} liegt nicht auf dem Default-Branch — beim "
              "Squash-Merge verschwindet dieser SHA. Besser: path:<datei>")
    print("  · noch nicht dauerhaft — `seal --push` macht es dauerhaft")
    return 0


def cmd_resolve(a: argparse.Namespace) -> int:
    led = Ledger.load()
    for e in led.entries:
        if e.id == a.id:
            if e.kind == "sackgasse":
                print(f"{a.id} ist eine Sackgasse — die bleibt bestehen, "
                      "damit sie nicht wiederholt wird.")
                return 1
            e.state = "erledigt"
            led.save()
            print(f"✓ {a.id} erledigt")
            return 0
    print(f"{a.id} nicht gefunden")
    return 1


def cmd_compact(a: argparse.Namespace) -> int:
    led = Ledger.load()
    before = led.size
    log, within = compact(led, a.budget)
    led.save()
    for line in log:
        print(f"  · {line}")
    print(f"Ledger {before}B → {led.size}B (Budget {a.budget}B) · "
          f"{len(led.entries)} Einträge")
    return 0 if within else 1


def cmd_verify(a: argparse.Namespace) -> int:
    led = Ledger.load()
    rotten = verify(led)
    ok, detail = durability()
    if a.json:
        print(json.dumps({
            "durable": ok, "detail": detail,
            "rotten": [{"id": e.id, "anchor": an, "status": s, "detail": d}
                       for e, an, s, d in rotten],
        }, ensure_ascii=False, indent=2))
    else:
        print(("✓ dauerhaft: " if ok else "⚠ nicht dauerhaft: ") + detail)
        if rotten:
            for e, an, s, d in rotten:
                print(f"  [{s}] {e.id} → {an} ({d})")
        else:
            print("✓ alle Anker tragen")
    hard = [r for r in rotten if r[2] == "rot"]
    return 0 if (ok and not hard) else 1


def cmd_seal(a: argparse.Namespace) -> int:
    return seal(a.push)


def cmd_handoff_prompt(_a: argparse.Namespace) -> int:
    print(HANDOFF_PROMPT)
    return 0


def cmd_status(_a: argparse.Namespace) -> int:
    led = Ledger.load()
    ok, _ = durability()
    print(f"Kontinuität · Sitzung={led.session} Einträge={len(led.entries)} "
          f"offen={len(led.open_entries())} {led.size}B "
          f"dauerhaft={'ja' if ok else 'NEIN'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="munin_continuity.py",
        description="Sitzungsgedächtnis, das den Container überlebt.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("resume", help="Sitzungsstart: verdichteter Kontext")
    r.add_argument("--json", action="store_true")
    r.add_argument("--peek", action="store_true",
                   help="lesen ohne die Sitzungsnummer zu erhöhen")
    r.set_defaults(func=cmd_resume)

    c = sub.add_parser("capture", help="Ergebnis festhalten")
    c.add_argument("--kind", required=True, choices=KINDS)
    c.add_argument("--text", required=True)
    c.add_argument("--anchor", action="append",
                   help="sha:<rev> | path:<datei>[:<zeile>] | frei")
    c.add_argument("--weight", type=int, default=1,
                   help="ab 2 überlebt eine Entscheidung auch gen2")
    c.set_defaults(func=cmd_capture)

    d = sub.add_parser("resolve", help="Eintrag schließen")
    d.add_argument("id")
    d.set_defaults(func=cmd_resolve)

    k = sub.add_parser("compact", help="generationell verdichten")
    k.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    k.set_defaults(func=cmd_compact)

    v = sub.add_parser("verify", help="Anker und Dauerhaftigkeit nachrechnen")
    v.add_argument("--json", action="store_true")
    v.set_defaults(func=cmd_verify)

    s = sub.add_parser("seal", help="committen (und pushen)")
    s.add_argument("--push", action="store_true")
    s.set_defaults(func=cmd_seal)

    h = sub.add_parser("handoff-prompt",
                       help="Prompt, mit dem die Folgesitzung startet")
    h.set_defaults(func=cmd_handoff_prompt)

    t = sub.add_parser("status", help="Einzeiler")
    t.set_defaults(func=cmd_status)
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
