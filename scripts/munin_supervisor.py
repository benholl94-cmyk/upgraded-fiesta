#!/usr/bin/env python3
"""munin_supervisor.py -- Aufsicht über den Agenten, nicht über das Repo.

Prüft, ob die Arbeit im Workspace die Verfassung des Masters einhält
(`.claude/persona/constitution.json`, `.claude/persona/munin.json`). Der
Adressat der Ausgabe ist der **Master**, nicht der Agent -- ein Agent, der
sein eigenes Verhalten bewertet, ist kein Audit.

Kernprinzip: **Behauptungen werden nachgerechnet, nicht geglaubt.**
Wenn der Agent sagt "Tests grün", führt der Supervisor sie aus. Wenn er sagt
"index.html synchron", vergleicht der Supervisor die Bytes. Wenn CLAUDE.md
sagt "Crate ist ein Stub", zählt der Supervisor die Funktionen.

    python3 scripts/munin_supervisor.py                 # einmalig, Text
    python3 scripts/munin_supervisor.py --json          # maschinenlesbar
    python3 scripts/munin_supervisor.py --watch 300     # Dauerloop, alle 300s
    python3 scripts/munin_supervisor.py --quick         # ohne Testlauf

Exit: 0 = sauber, 1 = DRIFT/RISK, 2 = VIOLATION (Verfassungsbruch).
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
import ast
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PERSONA = REPO / ".claude" / "persona"

VIOLATION = "VIOLATION"   # Verfassungsbruch
DRIFT = "DRIFT"           # Doku behauptet etwas anderes als die Realität
RISK = "RISK"             # noch kein Bruch, aber eine offene Flanke
OK = "OK"

_SEVERITY_RANK = {VIOLATION: 2, DRIFT: 1, RISK: 1, OK: 0}


@dataclass
class Finding:
    rule: str
    severity: str
    detail: str
    evidence: str = ""
    source: str = ""          # welche Regel des Masters verletzt wurde

    def __str__(self) -> str:
        head = f"[{self.severity:9}] {self.rule}: {self.detail}"
        if self.evidence:
            head += f"\n              ↳ {self.evidence}"
        if self.source:
            head += f"\n              ↳ Regel: {self.source}"
        return head


@dataclass
class Report:
    ts: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def worst(self) -> str:
        return max((f.severity for f in self.findings), key=lambda s: _SEVERITY_RANK[s],
                   default=OK)

    def exit_code(self) -> int:
        return {OK: 0, RISK: 1, DRIFT: 1, VIOLATION: 2}[self.worst]


def run(*args: str, cwd: Path = REPO) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def _load(name: str) -> dict:
    p = PERSONA / name
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# Prüfungen
# ---------------------------------------------------------------------------

SECRET_PATTERNS = (
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI-artiger Key"),
    (r"gh[pousr]_[A-Za-z0-9]{30,}", "GitHub-Token"),
    (r"AIza[0-9A-Za-z_\-]{30,}", "Google-API-Key"),
    (r"-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----", "privater Schlüssel"),
    (r"xox[baprs]-[A-Za-z0-9-]{10,}", "Slack-Token"),
)


def check_secrets() -> list[Finding]:
    """noSecrets: Kein Commit von API-Keys, Tokens, .env-Dateien."""
    out: list[Finding] = []
    tracked = run("git", "ls-files").stdout.splitlines()

    for path in tracked:
        # Nicht nur ".env" am Pfadanfang: im Repo lag ein getracktes
        # ".container_self_cycle_int+ext_.env", das die erste Fassung dieses
        # Musters durchgelassen hat. Jede Datei, die auf .env endet oder so
        # heisst, zaehlt.
        base = path.rsplit("/", 1)[-1]
        looks_env = base == ".env" or base.endswith(".env") or base.startswith(".env.")
        if looks_env and not path.endswith((".example", ".sample", ".template")):
            out.append(Finding(
                "secret-file-tracked", VIOLATION,
                f"{path} ist eingecheckt", source="munin.json → constraints.noSecrets"))

    # Nur den Diff der unveröffentlichten Commits scannen -- Historie ist
    # nicht mehr änderbar und würde bei jedem Lauf erneut feuern.
    diff = run("git", "diff", "origin/HEAD...HEAD", "--unified=0").stdout
    for pattern, label in SECRET_PATTERNS:
        for m in re.finditer(pattern, diff):
            out.append(Finding(
                "secret-in-diff", VIOLATION,
                f"{label} in noch nicht gemergtem Diff",
                evidence=m.group(0)[:12] + "…",
                source="munin.json → constraints.noSecrets"))
    return out


def check_hugin_sync() -> list[Finding]:
    """Synergie-Regel hugin_index_sync: index.html ist eine Bytekopie."""
    a, b = REPO / "hugin" / "hugin.html", REPO / "hugin" / "index.html"
    if not (a.is_file() and b.is_file()):
        return [Finding("hugin-sync", RISK, "hugin.html oder index.html fehlt")]
    if a.read_bytes() != b.read_bytes():
        return [Finding(
            "hugin-sync", VIOLATION,
            "index.html ist keine Bytekopie von hugin.html",
            evidence="Fix: cp hugin/hugin.html hugin/index.html",
            source="CLAUDE.md → synergy rule hugin_index_sync")]
    return []


def check_git_identity() -> list[Finding]:
    """gitIdentity: Author UND Committer, getrennt geprüft.

    Diese Regel meldete lange eine unauflösbare Kollision: die Harness verlangt
    `noreply@anthropic.com`, die Verfassung die Owner-Adresse. Das stimmte —
    solange man beide auf **dasselbe Feld** bezog. Tut man das nicht, ist der
    Widerspruch keiner:

        Author     wer die Änderung verfasst hat  → Master (Verfassung)
        Committer  wer sie eingetragen hat        → Claude (Signaturgültigkeit)

    Der Stop-Hook prüft `%ce`, weil der SSH-Signierschlüssel auf diese Adresse
    läuft; die Verfassung will Urheberschaft. Zwei Anforderungen, zwei Felder.
    Die Regel prüft deshalb beide **einzeln** und meldet genau die Seite, die
    abweicht — eine gemeinsame Meldung hätte die Auflösung wieder verdeckt.

    Der Author kommt aus `GIT_AUTHOR_EMAIL` bzw. `--author`; git hat keinen
    `author.email`-Schalter. Geprüft wird deshalb der letzte Commit, nicht die
    Konfiguration: was tatsächlich in der Historie steht, ist die einzige
    belastbare Antwort — dieselbe Regel wie überall hier.
    """
    ident = _load("munin.json").get("gitIdentity") or {}
    author_want = (ident.get("author") or {}).get("email") or ident.get("email")
    committer_want = (ident.get("committer") or {}).get("email")
    if not author_want:
        return []

    out = []
    committer_have = run("git", "config", "user.email").stdout.strip()
    if committer_want and committer_have != committer_want:
        out.append(Finding(
            "git-committer-identity", VIOLATION,
            f"Committer-Mail ist {committer_have or '(leer)'}, "
            f"erwartet {committer_want}",
            evidence="Der SSH-Signierschluessel laeuft auf diese Adresse; eine "
                     "andere macht jeden Commit auf GitHub 'Unverified'.",
            source="munin.json → gitIdentity.committer"))

    # Nur eigene Commits. `git log -1` traf nach einem Reset auf den
    # Default-Branch den letzten FREMDEN Commit -- z.B. den eines CI-Bots --
    # und meldete dessen Adresse als Verstoss. Dieselbe Fehlerklasse wie der
    # Stop-Hook, der einmal einen Rebase ueber Commits anderer Autoren
    # verlangte: fremde Historie als eigene gelesen.
    #
    # Eigene Commits sind genau die, die noch nicht im Default-Branch sind.
    # Gibt es keine, gibt es auch nichts zu pruefen -- eine Regel ohne
    # Gegenstand darf nicht anschlagen.
    base = run("git", "rev-parse", "--abbrev-ref", "origin/HEAD").stdout.strip() or "origin/main"
    r = run("git", "log", "-1", "--format=%ae", f"{base}..HEAD")
    author_have = r.stdout.strip() if r.returncode == 0 else ""
    if author_have and author_have != author_want:
        out.append(Finding(
            "git-author-identity", VIOLATION,
            f"Author des letzten Commits ist {author_have}, "
            f"Verfassung verlangt {author_want}",
            evidence="Urheberschaft gehoert dem Master. Setzbar ueber "
                     "GIT_AUTHOR_NAME/GIT_AUTHOR_EMAIL oder git commit --author.",
            source="munin.json → gitIdentity.author"))
    return out


def check_unpushed() -> list[Finding]:
    """Seit Amendment A1 bedeutet dieser Befund das Gegenteil von früher.

    Vorher galt: Push braucht einen Befehl, also ist ungepusht der *erwartete*
    Zustand und die Meldung nur ein Hinweis. Unter dem Mandat ist Push auf
    claude/* erlaubt und `seal --push` sogar Pflicht — ungepusht heißt jetzt,
    dass eine Sitzung nicht zu Ende geführt wurde. Genau daran ging `29b701c`
    verloren.
    """
    r = run("git", "rev-list", "origin/HEAD..HEAD", "--count")
    n = int(r.stdout.strip() or 0) if r.returncode == 0 else 0
    if not n:
        return []
    tips = run("git", "log", "--oneline", "origin/HEAD..HEAD").stdout.strip()
    return [Finding(
        "unpushed-work", RISK,
        f"{n} Commit(s) lokal, nicht auf dem Remote — die Sitzung ist nicht abgeschlossen",
        evidence=(tips.replace("\n", " | ")[:300]
                  + "  ·  Abschluss: python3 scripts/munin_continuity.py seal --push"),
        source="constitution → mandate.pflichten: 'Eine Sitzung endet erst mit seal --push'")]


# Die Mandatsgrenze ist der einzige Grund, warum die Lockerung aus A1
# vertretbar ist. Sie muss deshalb selbst bewacht werden: eine Sitzung, die
# sich mehr Spielraum verschafft, indem sie einen Eintrag aus dieser Liste
# entfernt, wäre von einer legitimen Master-Entscheidung sonst nicht zu
# unterscheiden. Der Supervisor rechnet die Grenze nach, statt ihr zu glauben.
#
# Die Stichwörter müssen *unterscheidend* sein und ALLE zutreffen. Eine
# frühere Fassung prüfte mit any() über lose Alternativen wie
# ("merge", "push", "default-branch") -- und weil "push" auch in "force-push"
# steckt, blieb die entfernte Default-Branch-Schranke unbemerkt. Der Gegentest
# hat das aufgedeckt: eine Wache, die fast jede Formulierung akzeptiert,
# prüft nichts.
MANDATE_BAR = (
    ("Default-Branch", ("default-branch",)),
    ("Historie umschreiben", ("historie", "umschreiben")),
    ("Löschen", ("löschen",)),
    ("Secrets", ("secrets",)),
    ("fremde PRs/Issues", ("fremde",)),
    ("Verfassungsänderung", ("verfassung",)),
)


def check_mandate() -> list[Finding]:
    """Ist die Mandatsgrenze noch vollständig?"""
    con = _load("constitution.json")
    if not con:
        return []
    mandate = con.get("mandate")
    if not mandate:
        # Vor A1 gab es kein Mandat — dann ist hier nichts zu prüfen.
        return [] if "amendments" not in con else [Finding(
            "mandate", VIOLATION,
            "Amendment vorhanden, aber der Abschnitt 'mandate' fehlt",
            source="constitution → amendments A1")]

    out: list[Finding] = []
    schranke = " ".join(mandate.get("befehlErforderlich", [])).lower()
    fehlend = [name for name, keys in MANDATE_BAR
               if not all(k in schranke for k in keys)]
    if fehlend:
        out.append(Finding(
            "mandate", VIOLATION,
            f"Mandatsgrenze unvollständig — {len(fehlend)} Schranke(n) fehlen",
            evidence=", ".join(fehlend),
            source="constitution → mandate.befehlErforderlich (nur der Master darf sie ändern)"))

    if not mandate.get("pflichten"):
        out.append(Finding(
            "mandate", VIOLATION,
            "Mandat ohne Pflichten — Autonomie ohne Protokoll ist Unsichtbarkeit",
            source="constitution → mandate.pflichten"))

    # Ein Amendment ohne den ersetzten Wortlaut ist ein stilles Überschreiben.
    for a in con.get("amendments", []):
        if not a.get("ersetzt") or not a.get("grund"):
            out.append(Finding(
                "mandate", DRIFT,
                f"Amendment {a.get('id', '?')} führt den ersetzten Wortlaut oder den Grund nicht mit",
                source="constitution → amendable.verfahren"))
    return out


# CLAUDE.md-Behauptungen, die messbar sind. Bewusst als kleine, per Auge
# auditierbare Tabelle statt als NLP über den Fließtext.
STUB_CLAIMS = (
    "hm-core", "hm-cli", "hm-cron", "hm-sessions",
    "hm-tools/hm-tool-browser", "hm-tools/hm-tool-media", "hm-tools/hm-tool-web",
    "hm-channels/hm-channel-telegram", "hm-channels/hm-channel-discord",
    "hm-channels/hm-channel-slack", "hm-channels/hm-channel-whatsapp",
)
STUB_MAX_FUNCTIONS = 3


STUB_WORDS = ("placeholder", "stub", "single-function", "single-constant",
              "not a working feature", "none makes real calls")
# Fenster um die Fundstelle. Gross genug fuer einen Satz, klein genug, dass
# eine Erwaehnung drei Absaetze weiter nicht mitzaehlt.
_CLAIM_WINDOW = 320


# Eine Behauptung kann verneint oder historisch sein: "Real — not a stub",
# "an earlier revision called these placeholders". Ohne diese Erkennung wuerde
# ausgerechnet eine korrigierte Doku Dauerbefunde erzeugen -- und ein Auditor,
# der Korrekturen bestraft, erzieht zum Weglassen.
NEGATIONS = ("not a", "not an", "no longer", "isn't", "is not", "aren't",
             "used to be", "earlier revision", "rather than", "instead of",
             "nicht mehr", "kein ", "keine ")
_NEG_WINDOW = 90


def _claims_stub(text: str, name: str) -> bool:
    """Behauptet CLAUDE.md in der Naehe von `name`, es sei ein Platzhalter?

    Prosa-Scan, also unvermeidlich heuristisch: Verneinungen werden erkannt,
    verschachtelte Formulierungen koennen weiterhin danebenliegen. Im Zweifel
    lieber ein Fehlalarm als ein uebersehener Drift -- deshalb zaehlt jede
    nicht ausdruecklich verneinte Fundstelle.
    """
    low = text.lower()
    needle = name.lower()
    start = 0
    while (i := low.find(needle, start)) != -1:
        window = low[max(0, i - _CLAIM_WINDOW): i + _CLAIM_WINDOW]
        for w in STUB_WORDS:
            j = window.find(w)
            while j != -1:
                near = window[max(0, j - _NEG_WINDOW): j + len(w) + 20]
                if not any(n in near for n in NEGATIONS):
                    return True
                j = window.find(w, j + len(w))
        start = i + len(needle)
    return False


def check_doc_drift() -> list[Finding]:
    """CLAUDE.md nennt diese Crates 'intentional placeholders' / 'stubs'.
    Wenn sie das nicht mehr sind, ist die autoritative Quelle falsch -- und
    die Verfassung stellt den git-Workspace über jeden anderen Kontext."""
    out: list[Finding] = []
    claude_md = (REPO / "CLAUDE.md")
    if not claude_md.is_file():
        return []
    text = claude_md.read_text(encoding="utf-8", errors="replace")
    for crate in STUB_CLAIMS:
        src = REPO / "crates" / crate / "src"
        if not src.is_dir():
            continue
        name = crate.split("/")[-1]
        # CLAUDE.md nennt Crate-Familien als Glob ("hm-channel-*"), nicht
        # einzeln. Nur auf den vollen Namen zu prüfen liesse genau die
        # Familien durchrutschen, um die es geht.
        family = re.sub(r"-(telegram|discord|slack|whatsapp|browser|media|web|exec)$",
                        "-*", name)
        # Entscheidend ist die *Behauptung*, nicht die blosse Erwähnung: seit
        # CLAUDE.md eine korrekte Messtabelle enthält, steht jeder Crate-Name
        # dort legitim. Nur ein Stub-Anspruch in Reichweite des Namens zählt.
        if not _claims_stub(text, name) and not _claims_stub(text, family):
            continue
        code = "\n".join(f.read_text(encoding="utf-8", errors="replace")
                         for f in src.rglob("*.rs"))
        fns = len(re.findall(r"\bpub (?:async )?fn\b", code))
        if fns > STUB_MAX_FUNCTIONS:
            out.append(Finding(
                "doc-drift", DRIFT,
                f"CLAUDE.md nennt {name} einen Platzhalter, gemessen: {fns} pub fn",
                evidence=f"crates/{crate}/src",
                source="constitution: der git-Workspace ist die autoritative Quelle — "
                       "eine veraltete CLAUDE.md untergräbt genau das"))
    return out


PROVIDER_HOSTS = (
    "api.openai.com", "generativelanguage.googleapis.com", "api.mistral.ai",
    "api.groq.com", "api.anthropic.com", "openrouter.ai",
)
# Die PWA ruft Provider bewusst direkt aus dem Browser -- sie ist kein
# Server-seitiger Pfad und fällt nicht unter das Oracle-Gate.
ORACLE_EXEMPT = ("hugin/", "scripts/hugin_oracle.py", "docs/", "CLAUDE.md",
                 "scripts/munin_supervisor.py", "tests/")


#: Module, ohne die eine Python-Datei keine Verbindung aufbauen kann.
NETZ_MODULE = ("socket", "ssl", "http", "urllib", "requests", "httpx",
               "ftplib", "smtplib", "asyncio", "aiohttp")


def _kann_senden(path: str, body: str) -> bool:
    """Kann diese Datei ueberhaupt eine Verbindung oeffnen?

    **Warum die Regel das prueft statt einer Pfad-Ausnahmeliste.** Eine
    Datei darf Provider-Endpunkte *nennen*, ohne sie aufzurufen:
    `scripts/hugin_bruecke.py` fuehrt eine Routentabelle mit Hostnamen und
    plant Aufrufe, oeffnet aber nie einen Socket -- R6 erzeugt einen Plan.
    Sie in `ORACLE_EXEMPT` einzutragen waere ein Stempel: die Ausnahme
    gaelte dann auch, wenn jemand spaeter `import urllib` ergaenzt. Genau
    diese Sorte Eintrag hat hier schon einmal ein Loch hinterlassen
    (`KNOWN_SAFE_ENV` zeigte auf eine geloeschte Datei und befreite alles,
    was danach an diesem Pfad auftauchte).

    Geprueft wird deshalb die Eigenschaft, nicht der Name. Fuer
    Nicht-Python-Dateien bleibt die Antwort `True` -- dort laesst sich das
    hier nicht entscheiden, und Unbekanntes gilt nie als in Ordnung.
    """
    if not path.endswith(".py"):
        return True
    try:
        baum = ast.parse(body)
    except SyntaxError:
        return True
    for k in ast.walk(baum):
        if isinstance(k, ast.Import):
            namen = [a.name.split(".")[0] for a in k.names]
        elif isinstance(k, ast.ImportFrom) and k.module:
            namen = [k.module.split(".")[0]]
        else:
            continue
        if any(n in NETZ_MODULE for n in namen):
            return True
    return False


def check_oracle_gate() -> list[Finding]:
    """Alle serverseitigen Provider-Calls laufen durch hugin_oracle.py."""
    out: list[Finding] = []
    for path in run("git", "ls-files", "*.py", "*.rs", "*.sh").stdout.splitlines():
        if any(path.startswith(x) for x in ORACLE_EXEMPT):
            continue
        f = REPO / path
        if not f.is_file():
            continue
        body = f.read_text(encoding="utf-8", errors="replace")
        if not _kann_senden(path, body):
            continue      # nennt Endpunkte, kann sie aber nicht aufrufen
        for host in PROVIDER_HOSTS:
            if host in body:
                out.append(Finding(
                    "oracle-gate-bypass", RISK,
                    f"{path} nennt {host} direkt",
                    source="CLAUDE.md → Oracle-Gate: externe Provider nur via "
                           "scripts/hugin_oracle.py"))
    return out


ARCHIVE_SUFFIXES = (".zip", ".tar.gz", ".tgz", ".bin", ".7z", ".rar")
# Ab hier lohnt das Melden; darunter ist ein Binaerblob meist Absicht
# (Icons, kleine Fixtures) und wuerde nur Rauschen erzeugen.
ARCHIVE_MIN_BYTES = 50 * 1024


def check_dead_data() -> list[Finding]:
    """Rest-tote Daten: was im Index liegt, aber dort nicht hingehoert.

    Der teuerste Fall ist 'getrackt obwohl in .gitignore' -- ein
    .gitignore-Eintrag entfernt eine bereits committete Datei nicht aus dem
    Index. Die Regel sieht dann erfuellt aus und ist es nicht.
    """
    out: list[Finding] = []

    ignored = [p for p in run("git", "ls-files", "-i", "-c",
                              "--exclude-standard").stdout.splitlines() if p]
    if ignored:
        shown = ", ".join(ignored[:4]) + ("…" if len(ignored) > 4 else "")
        out.append(Finding(
            "tracked-but-ignored", VIOLATION,
            f"{len(ignored)} Datei(en) sind getrackt, obwohl .gitignore sie ausschliesst",
            evidence=f"{shown} — Fix: git rm --cached <pfad>",
            source=".gitignore ist damit wirkungslos: der Eintrag suggeriert Schutz, "
                   "der Index widerlegt ihn"))

    big: list[str] = []
    for path in run("git", "ls-files").stdout.splitlines():
        if not path.endswith(ARCHIVE_SUFFIXES):
            continue
        f = REPO / path
        try:
            if f.is_file() and f.stat().st_size >= ARCHIVE_MIN_BYTES:
                big.append(f"{path} ({f.stat().st_size // 1024}K)")
        except OSError:
            continue
    if big:
        out.append(Finding(
            "archive-in-index", RISK,
            f"{len(big)} Archiv(e)/Binary(s) im Index",
            evidence=", ".join(big[:3]) + ("…" if len(big) > 3 else ""),
            source="git ist kein Blob-Store: Archive blaehen jeden Clone dauerhaft auf, "
                   "auch nach dem Loeschen"))
    return out


def check_hook_drift() -> list[Finding]:
    """Installierter Hook vs. Repo-Fassung.

    Hooks leben in ~/.claude/ und damit ausserhalb jeder Versionierung: eine
    Korrektur dort ist in keinem Diff sichtbar und ueberlebt keinen neuen
    Container. Gleiche Logik wie `hugin_index_sync` -- zwei Kopien, die
    identisch sein muessen, brauchen eine Pruefung, sonst driften sie.

    **Nur dort gemessen, wo die Frage einen Sinn hat.** Ein Hook greift in
    eine Arbeitssitzung ein; auf einem CI-Runner gibt es keine, und `~/.claude`
    existiert dort gar nicht. Die Regel meldete trotzdem bei jedem
    Selbsterhalt-Lauf `hook-not-installed` — ein Befund, der von einem echten
    nicht zu unterscheiden ist und den niemand beheben kann, weil der Runner
    nach dem Lauf verschwindet. Sieben Laeufe lang stand er so in der
    Master-Meldung.

    Die Grenze verlaeuft an `~/.claude` selbst: fehlt das Verzeichnis, ist die
    Maschine keine Arbeitsumgebung und die Frage nicht gestellt. Ist es da und
    der Hook fehlt, bleibt es ein Befund — genau der Fall, den die Regel
    fangen soll.
    """
    src_dir = REPO / ".claude" / "hooks"
    if not src_dir.is_dir():
        return []
    if not (Path.home() / ".claude").is_dir():
        return []
    out: list[Finding] = []
    for src in sorted(src_dir.glob("*.sh")):
        dst = Path.home() / ".claude" / src.name
        if not dst.is_file():
            out.append(Finding(
                "hook-not-installed", RISK,
                f"{src.name} liegt im Repo, ist aber nicht installiert",
                evidence=f"{dst} fehlt — python3 scripts/install_hooks.py --yes"))
        elif src.read_bytes() != dst.read_bytes():
            out.append(Finding(
                "hook-drift", VIOLATION,
                f"{src.name} weicht von der installierten Fassung ab",
                evidence=f"{dst} — Repo-Fassung gilt: "
                         f"python3 scripts/install_hooks.py --yes",
                source="Hooks ausserhalb des Repos sind unversioniert; "
                       "Divergenz bleibt sonst unsichtbar"))
    return out


def check_keyring() -> list[Finding]:
    """Selbst ausgestellte Schlüssel: liegt nichts davon im Index?

    Ruft `hugin_keyring.py audit` auf, statt die Logik zu duplizieren -- zwei
    Fassungen derselben Prüfung driften garantiert auseinander.
    """
    script = REPO / "scripts" / "hugin_keyring.py"
    if not script.is_file():
        return []
    r = run("python3", str(script), "audit")
    if r.returncode == 0:
        return []
    detail = (r.stdout + r.stderr).strip().splitlines()
    body = [ln.strip() for ln in detail if ln.strip().startswith(("VIOLATION", "RISK"))]
    sev = VIOLATION if any(b.startswith("VIOLATION") for b in body) else RISK
    return [Finding("keyring-audit", sev,
                    f"{len(body) or 1} Befund(e) im Schlüssel-Audit",
                    evidence=" | ".join(body)[:400] or (r.stdout + r.stderr)[:200],
                    source="munin.json → constraints.noSecrets")]


def check_repo_structure() -> list[Finding]:
    r = run("python3", "scripts/validate_repo.py")
    if r.returncode == 0:
        return []
    return [Finding("repo-structure", VIOLATION, "validate_repo.py schlägt fehl",
                    evidence=(r.stdout + r.stderr).strip()[:300])]


def check_claims() -> list[Finding]:
    """Behauptung 'Tests grün' wird nachgerechnet, nicht geglaubt."""
    r = run("python3", "-m", "pytest", "tests/", "-q", "--timeout=120")
    if r.returncode == 0:
        return []
    tail = (r.stdout + r.stderr).strip().splitlines()
    return [Finding("claim-tests-pass", VIOLATION,
                    "Testsuite ist rot — jede Behauptung 'Tests grün' ist damit falsch",
                    evidence=" | ".join(tail[-3:])[:400],
                    source="constitution: 'Transparenz: Wissenslücken werden benannt, "
                           "nicht kaschiert'")]


def check_continuity() -> list[Finding]:
    """Das Gedächtnis unterliegt derselben Prüfung wie alles andere.

    Ein Kontinuitäts-Ledger, das nicht gepusht ist, hält genau so lange wie
    der Container -- das ist der gemessene Verlustweg von `29b701c`. Und
    Anker, die ins Leere zeigen, sind schlimmer als keine: sie sehen aus wie
    Belege. Beides wird hier nachgerechnet statt geglaubt, weil ein
    Gedächtnis, das sich selbst bestätigt, keines ist.
    """
    script = REPO / "scripts" / "munin_continuity.py"
    ledger = REPO / ".claude" / "continuity" / "ledger.json"
    if not script.is_file():
        return []
    if not ledger.is_file():
        return [Finding("continuity", RISK,
                        "Kein Kontinuitäts-Ledger — die nächste Sitzung startet blind",
                        evidence=str(ledger.relative_to(REPO)),
                        source="constitution: Workspace ist die autoritative Quelle")]

    r = run("python3", str(script), "verify", "--json")
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return [Finding("continuity", RISK, "verify lieferte kein JSON",
                        evidence=(r.stdout + r.stderr).strip()[:200])]

    out: list[Finding] = []
    if not data.get("durable"):
        out.append(Finding(
            "continuity", RISK,
            "Ledger ist nicht dauerhaft — überlebt den Container nicht",
            evidence=str(data.get("detail", ""))[:200],
            source="constitution: Workspace ist die autoritative Quelle"))

    rot = [x for x in data.get("rotten", []) if x.get("status") == "rot"]
    if rot:
        out.append(Finding(
            "continuity", DRIFT,
            f"{len(rot)} Anker im Gedächtnis zeigen ins Leere",
            evidence="; ".join(f"{x['id']}→{x['anchor']}" for x in rot[:4])[:300]))
    return out


CHECKS = (
    ("secrets", check_secrets),
    ("mandate", check_mandate),
    ("continuity", check_continuity),
    ("hugin-sync", check_hugin_sync),
    ("git-identity", check_git_identity),
    ("unpushed", check_unpushed),
    ("doc-drift", check_doc_drift),
    ("dead-data", check_dead_data),
    ("hook-drift", check_hook_drift),
    ("keyring", check_keyring),
    ("oracle-gate", check_oracle_gate),
    ("repo-structure", check_repo_structure),
)


def audit(quick: bool = False) -> Report:
    rep = Report(ts=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    for _name, fn in CHECKS:
        try:
            rep.findings.extend(fn())
        except Exception as exc:                      # ein kaputter Check darf
            rep.findings.append(Finding(              # das Audit nicht killen
                _name, RISK, f"Prüfung selbst fehlgeschlagen: {exc}"))
    if not quick:
        rep.findings.extend(check_claims())
    return rep


def render(rep: Report) -> str:
    if not rep.findings:
        return f"{rep.ts}  SAUBER — keine Abweichung von der Verfassung."
    lines = [f"{rep.ts}  {rep.worst} — {len(rep.findings)} Befund(e)", ""]
    order = {VIOLATION: 0, DRIFT: 1, RISK: 2, OK: 3}
    for f in sorted(rep.findings, key=lambda x: order[x.severity]):
        lines.append(str(f))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true", help="maschinenlesbar")
    p.add_argument("--quick", action="store_true", help="ohne Testlauf")
    p.add_argument("--watch", type=int, metavar="SEK",
                   help="Dauerloop: alle SEK Sekunden erneut prüfen")
    p.add_argument("--write", action="store_true",
                   help="Bericht nach .claude/persona/supervisor-report.json schreiben")
    a = p.parse_args(argv)

    while True:
        rep = audit(quick=a.quick)
        if a.json:
            print(json.dumps({"ts": rep.ts, "worst": rep.worst,
                              "findings": [asdict(f) for f in rep.findings]},
                             indent=2, ensure_ascii=False))
        else:
            print(render(rep))
        if a.write:
            out = PERSONA / "supervisor-report.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"ts": rep.ts, "worst": rep.worst,
                                       "findings": [asdict(f) for f in rep.findings]},
                                      indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
        if not a.watch:
            return rep.exit_code()
        sys.stdout.flush()
        time.sleep(max(10, a.watch))


if __name__ == "__main__":
    raise SystemExit(main())
