"""brain.py -- der eine Einstiegspunkt. Chat rein, Strom raus.

Bisher lagen die Teile nebeneinander: `hugin_relay.py` kannte die Stufen,
`kernel.py` die Belege, `adapters.py` die Agenten, `hugin_model.py` das lokale
Modell, das Gateway den Port. Keines rief das andere. Wer etwas ausfuehren
wollte, brauchte eine Sitzung mit mir — **und genau das war die harte Bindung
an Anthropic**, nicht irgendein Import.

Diese Datei schliesst den Kreis: eine Funktion, die eine Chatzeile
entgegennimmt und einen Strom von Ereignissen liefert. Was sie benutzt, um zu
antworten, entscheidet die gemessene Verfuegbarkeit — nicht eine Voreinstellung
und kein bevorzugter Anbieter.

## Die Leiter

    T0   Kein Modell.        Immer da. Befehle, Pruefungen, Belege aus dem Repo.
    T1b  Lokales GGUF.       Eigene Hardware, 0 EUR, keine Gegenstelle.
    T1   Keylose Provider.   0 EUR, ueber das Oracle-Gate.
    T2   Bezahlte Provider.  Nur wenn die Kostensperre offen ist.

Anthropic ist auf dieser Leiter **eine Sprosse unter anderen** und keine
Voraussetzung. `tests/test_brain.py` beweist das, indem es die Umgebung von
jeder ANTHROPIC-Variablen befreit und trotzdem eine Antwort verlangt. Ein
System, das ohne mich nur behauptet zu laufen, laeuft nicht ohne mich.

## Zwei Arten von Eingabe

Eine Zeile mit `/` vorn ist ein **Befehl**, alles andere eine **Frage**.
Befehle laufen nach demselben Prinzip wie `hm-tool-exec`: die Eingabe *waehlt*
aus einer festen Liste, sie *baut* nie eine Kommandozeile. Ein Chat, der argv
zusammensetzt, ist eine Shell mit Bearer-Token davor.

## Warum ein Strom und kein Ergebnis

Eine lokale 12B-Antwort dauert Minuten. Ohne Strom sieht der Operator eine
haengende Verbindung und weiss nicht, ob gerechnet oder gestorben wird. Jede
Zeile ist ein JSON-Objekt (NDJSON); das Gateway reicht sie unveraendert als
SSE weiter und muss den Inhalt nicht verstehen.

    python3 -m agents.brain "/status"
    python3 -m agents.brain --json "Was ist im Subroom offen?"
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

T0, T1B, T1, T2 = "T0", "T1b", "T1", "T2"


# ---------------------------------------------------------------------------
# Ereignisse
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Event:
    """Eine Zeile im Strom. `typ` sagt dem Empfaenger, was er damit tut.

    `info` ist bewusst ein eigener Typ und kein Text mit Praefix: eine
    Oberflaeche soll Herkunftsangaben anders darstellen koennen als Inhalt,
    und ein Praefix im Text laesst sich nicht zuverlaessig wieder abtrennen.
    """

    typ: str                    # info | token | fehler | ende
    text: str = ""
    meta: dict = field(default_factory=dict)

    def to_json(self) -> str:
        d = {"typ": self.typ, "text": self.text}
        if self.meta:
            d["meta"] = self.meta
        return json.dumps(d, ensure_ascii=False)


def _info(text: str, **meta) -> Event:
    return Event("info", text, meta)


# ---------------------------------------------------------------------------
# Befehle -- auswaehlen, nie bauen
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Command:
    argv: tuple[str, ...]
    zweck: str
    nimmt_text: bool = False    # haengt genau EIN Argument an, als ein argv-Element
    #: Pfade relativ zum Repo-Wurzelverzeichnis, ohne die dieser Befehl kein
    #: sinnvolles Ergebnis liefern kann.
    #:
    #: Das Laufzeit-Image kopiert `config/`, `plugins/`, `scripts/`, `agents/`
    #: und Teile von `.claude/` — aber weder `crates/` noch `Cargo.toml` noch
    #: `tests/`. Ohne diese Prüfung lief der Befehl trotzdem los, und zwar in
    #: drei verschiedene Sorten falscher Antwort, alle im Container gemessen:
    #:
    #:   /struktur   ein roher Python-Traceback im Chat
    #:   /supervisor "VIOLATION — 4 Befunde", die reine Artefakte der
    #:               fehlenden Dateien sind und wie echte Verfassungs-
    #:               verstoesse aussehen
    #:   /tests      "no tests ran in 0.00s" — eine leere, gruen wirkende
    #:               Testsuite statt der Aussage, dass gar keine da ist
    #:
    #: Die zweite und dritte sind die gefaehrlicheren: sie sehen nach einem
    #: Ergebnis aus. Ein Befehl, der seine Voraussetzung nicht hat, muss das
    #: sagen, statt eine Antwort zu erfinden.
    braucht: tuple[str, ...] = ()


COMMANDS: dict[str, Command] = {
    "status":     Command(("python3", "scripts/hugin_relay.py", "status"),
                          "Welche Stufe traegt gerade"),
    "supervisor": Command(("python3", "scripts/munin_supervisor.py", "--quick"),
                          "Verfassungs-Audit",
                          braucht=("Cargo.toml", "crates", "tests")),
    "tests":      Command(("python3", "-m", "pytest", "tests/", "-q"),
                          "Testsuite",
                          braucht=("tests",)),
    "struktur":   Command(("python3", "scripts/validate_repo.py"),
                          "Strukturpruefung",
                          braucht=("Cargo.toml", "crates")),
    "queue":      Command(("python3", "scripts/hugin_relay.py", "queue"),
                          "Was im Subroom wartet"),
    "drain":      Command(("python3", "scripts/hugin_relay.py", "drain"),
                          "T0-Aufgaben abarbeiten"),
    "ledger":     Command(("python3", "scripts/munin_continuity.py", "resume"),
                          "Kurzfassung der Kontinuitaet"),
    "anker":      Command(("python3", "scripts/munin_continuity.py", "verify"),
                          "Ledger-Anker nachrechnen"),
    "persona":    Command(("python3", "scripts/hugin_model.py", "persona"),
                          "Welche Regeln der Kern gerade traegt"),
    "modell":     Command(("python3", "scripts/hugin_model.py", "plan"),
                          "Gepinnte Modellauswahl"),
    "keyring":    Command(("python3", "scripts/hugin_keyring.py", "status"),
                          "Schluessel: vorhanden / fehlend"),
    "park":       Command(("python3", "scripts/hugin_relay.py", "park"),
                          "Arbeit in den Subroom legen", nimmt_text=True),
}

CMD_TIMEOUT_S = 900


def command_help() -> list[str]:
    out = ["Befehle (alles andere ist eine Frage an den Kern):"]
    out += [f"  /{n:<11}{c.zweck}" + ("  <text>" if c.nimmt_text else "")
            for n, c in sorted(COMMANDS.items())]
    out.append("  /tiers      Welche Stufen gerade wirklich verfuegbar sind")
    out.append("  /help       Diese Liste")
    return out


def run_command(name: str, rest: str) -> Iterator[Event]:
    """Fester Befehl, festes argv. `rest` wird nie zerlegt und nie zu Optionen.

    Ohne diese Eigenschaft waere `/park --tier T0; rm -rf` eine Frage der
    Formulierung. So ist es genau ein Argument mit einem Bindestrich darin.
    """
    cmd = COMMANDS.get(name)
    if cmd is None:
        yield Event("fehler", f"Unbekannter Befehl /{name}")
        yield from (_info(l) for l in command_help())
        return

    # Voraussetzungen zuerst, denn ein Befehl ohne seine Dateien liefert
    # keine Fehlermeldung, sondern eine falsche Antwort — siehe die
    # Begruendung an `Command.braucht`.
    fehlend = [p for p in cmd.braucht if not (REPO / p).exists()]
    if fehlend:
        yield Event(
            "fehler",
            f"/{name} ist in dieser Installation nicht verfuegbar: "
            f"{', '.join(fehlend)} fehlt. "
            "Das Laufzeit-Image traegt nur config/, plugins/, scripts/ und agents/ — "
            "dieser Befehl braucht den vollstaendigen Checkout.",
        )
        return

    argv = list(cmd.argv)
    if cmd.nimmt_text:
        if not rest.strip():
            yield Event("fehler", f"/{name} braucht einen Text")
            return
        argv.append(rest.strip())          # EIN Element, kein Split
    elif rest.strip():
        yield _info(f"/{name} nimmt keinen Text — {rest.strip()[:40]!r} ignoriert")

    yield _info(f"$ {' '.join(argv)}", tier=T0)
    try:
        proc = subprocess.Popen(argv, cwd=REPO, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
    except OSError as exc:
        yield Event("fehler", f"Start fehlgeschlagen: {exc}")
        return
    try:
        for line in proc.stdout:           # zeilenweise, nicht am Ende auf einmal
            yield Event("token", line.rstrip("\n"))
        code = proc.wait(timeout=CMD_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        yield Event("fehler", f"/{name} nach {CMD_TIMEOUT_S}s abgebrochen")
        return
    finally:
        if proc.stdout:
            proc.stdout.close()
    yield Event("ende", f"exit {code}", {"exit": code, "tier": T0})


# ---------------------------------------------------------------------------
# Verfuegbarkeit -- gemessen, nicht angenommen
# ---------------------------------------------------------------------------

MODEL_PATHS = ("models/model.gguf",)
LLAMA_BINS = ("llama.cpp/build/bin/llama-cli", "llama-cli")


def _llama_binary() -> str | None:
    for cand in LLAMA_BINS:
        p = REPO / cand
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
        found = shutil.which(cand)
        if found:
            return found
    return None


def _model_file() -> Path | None:
    for cand in MODEL_PATHS:
        p = REPO / cand
        if p.is_file():
            return p
    return None


def tiers() -> list[tuple[str, bool, str]]:
    """(Stufe, verfuegbar, Begruendung) -- jede Zeile nachgerechnet.

    Der Supervisor-Grundsatz gilt auch hier: eine Stufe gilt nicht als
    verfuegbar, weil sie konfiguriert ist, sondern weil die Datei da ist.
    """
    out = [(T0, True, "Befehle, Pruefungen, Belege — braucht kein Modell")]

    mdl, bina = _model_file(), _llama_binary()
    if mdl and bina:
        out.append((T1B, True, f"{mdl.name} + {Path(bina).name}"))
    else:
        fehlt = []
        if not mdl:
            fehlt.append("models/model.gguf (Workflow hugin-kern.yml holt sie)")
        if not bina:
            fehlt.append("llama-cli")
        out.append((T1B, False, "fehlt: " + ", ".join(fehlt)))

    # Zwei getrennte try-Bloecke: faellt die Budget-Abfrage aus, darf sie
    # nicht die schon ermittelte T1-Zeile mitreissen. Ein gemeinsamer Block
    # haengte T1 zweimal an — einmal richtig, einmal als Fehler.
    try:
        from agents import budget
        frei = _remote_providers()
        alle = budget.free_providers()
        out.append((T1, bool(frei),
                    f"{len(frei)} von {len(alle)} keylosen Providern erreichbar"))
    except Exception as exc:
        out.append((T1, False, f"agents.budget nicht ladbar: {exc}"))
    try:
        from agents import budget
        # `Budget.active` heisst "die Bremse greift", NICHT "Ausgeben erlaubt".
        # Die erste Fassung las es andersherum und meldete "T2 offen", waehrend
        # jeder kostenpflichtige Provider gesperrt war — die gefaehrliche
        # Richtung des Irrtums: verfuegbar behaupten, was gesperrt ist.
        gebremst = budget.Budget.load().active
        out.append((T2, not gebremst,
                    "Kostensperre zu (config/budget.json → development_phase) — "
                    "kostenpflichtige Provider gesperrt" if gebremst
                    else "Kostensperre geloest — kostenpflichtige Aufrufe moeglich"))
    except Exception as exc:
        # Unbekannt heisst gesperrt, nie erlaubt — dieselbe Richtung wie
        # cost_class(), wo Unbekanntes als kostenpflichtig gilt.
        out.append((T2, False, f"Kostenstand unbekannt, deshalb gesperrt: {exc}"))
    return out


# ---------------------------------------------------------------------------
# Fragen
# ---------------------------------------------------------------------------

def _grounded(question: str, paths: tuple[str, ...]) -> tuple[str, list, list]:
    """Prompt + Belege + Verbote. Ein Aufruf, damit T0 und T1b dieselbe
    Erdung sehen — zwei Erdungen waeren zwei Wahrheiten."""
    import hugin_model
    prompt = hugin_model.grounded_prompt(question, paths)
    belege, verboten = [], []
    try:
        from agents.kernel import Situation, infer
        r = infer(Situation(text=question, paths=paths))
        belege = list(r.evidence)
        if r.verdict == "verboten":
            verboten = list(r.blocking)
    except Exception:
        pass
    return prompt, belege, verboten


def _answer_t0(question: str, belege: list, verboten: list) -> Iterator[Event]:
    """Ohne jedes Modell antworten. Das ist keine Notloesung, sondern der
    ehrlichste Fall: Belege aus der verifizierten Historie, sonst nichts.

    Was hier NICHT passiert: Formulieren. Ohne Modell gibt es keine Prosa,
    und erfundene Prosa waere schlimmer als keine.
    """
    if verboten:
        yield Event("token", "VERWEIGERT — eine Invariante verbietet das:")
        for c in verboten:
            yield Event("token", f"  · {c.text}")
        yield Event("ende", "", {"tier": T0, "verdict": "verboten"})
        return
    if belege:
        yield Event("token", "Kein Modell verfuegbar. Belege aus der Repo-Historie:")
        for e in belege:
            yield Event("token", f"  · [{e.case.kind}, Naehe {e.score:.2f}] {e.case.text}")
        yield Event("token", "")
        yield Event("token", "Das ist die Fundstelle, nicht die Antwort — "
                             "formulieren kann sie nur ein Modell.")
    else:
        yield Event("token", "Kein Modell verfuegbar und kein Praezedenzfall im Repo.")
        yield Event("token", "Damit ist die Frage hier nicht beantwortbar. "
                             "'/tiers' zeigt, was fehlt.")
    yield Event("ende", "", {"tier": T0, "belege": len(belege)})


def _answer_local(prompt: str) -> Iterator[Event]:
    """Lokales GGUF, tokenweise. Kein Netz, keine Gegenstelle, kein Konto."""
    import hugin_model
    binary, model = _llama_binary(), _model_file()
    cfg = hugin_model.config().get("laufzeit", {})
    grammar = REPO / ".claude" / "relay" / "schema.gbnf"
    grammar.parent.mkdir(parents=True, exist_ok=True)
    grammar.write_text(hugin_model.GRAMMAR, encoding="utf-8")

    argv = [binary, "--model", str(model), "--prompt", prompt,
            "--grammar-file", str(grammar),
            "--threads", str(cfg.get("threads", os.cpu_count() or 4)),
            "--ctx-size", str(cfg.get("context", 8192)),
            "--temp", str(cfg.get("temp", 0.2)),
            "--n-predict", "700", "--no-display-prompt", "--simple-io"]
    yield _info(f"lokales Modell: {Path(model).name}", tier=T1B)
    proc = subprocess.Popen(argv, cwd=REPO, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, bufsize=1)
    try:
        for line in proc.stdout:
            yield Event("token", line.rstrip("\n"))
        code = proc.wait(timeout=CMD_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        yield Event("fehler", "lokales Modell abgebrochen (Zeit)")
        return
    finally:
        if proc.stdout:
            proc.stdout.close()
    yield Event("ende", "", {"tier": T1B, "exit": code})


def _oracle():
    """Das Gate als Modul. Kein zweiter Weg nach draussen — die Verfassung
    laesst externe Provider ausschliesslich hierdurch."""
    import importlib.util
    path = REPO / "scripts" / "hugin_oracle.py"
    spec = importlib.util.spec_from_file_location("hugin_oracle", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("hugin_oracle", mod)
    spec.loader.exec_module(mod)
    return mod


def _reachable(host: str, port: int, timeout: float = 0.4) -> bool:
    """Ein TCP-Handshake. Mehr Beweis gibt es ohne echten Aufruf nicht,
    und weniger ist geraten."""
    import socket
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


# Provider, deren Verfuegbarkeit NICHT an einem Key haengt, sondern an einem
# laufenden Dienst. Ein gesetzter (oder nicht noetiger) Key sagt hier nichts.
_LOCAL_ENDPOINTS = {
    "local": ("127.0.0.1", 11434),      # Ollama
}


def _remote_providers(pruefe_dienste: bool = True) -> list[str]:
    """Keylose Provider, die das Gate kennt UND wirklich erreichbar sind.

    Die erste Fassung nahm jeden Provider ohne Key-Pflicht als verfuegbar an.
    Gemessene Folge: `/tiers` meldete "1 von 10 keylosen Providern erreichbar"
    — gemeint war `local` (Ollama), das gar nicht lief. Der erste echte Aufruf
    scheiterte dann mit "Ollama nicht erreichbar (localhost:11434)".

    Das ist genau der Fehler, den dieses Repo sonst ueberall vermeidet:
    Konfiguration als Zustand lesen. Eine Sprosse gilt jetzt nur als tragend,
    wenn sie nachweislich traegt — bei Netzdiensten heisst das ein
    TCP-Handshake, kein Blick in ein Dict.
    """
    try:
        from agents import budget
        gate = getattr(_oracle(), "PROVIDERS", {})
    except Exception:
        return []
    out = []
    for name in budget.free_providers():
        adapter = gate.get(name)
        if adapter is None:
            continue
        endpunkt = _LOCAL_ENDPOINTS.get(name)
        if endpunkt is not None:
            if pruefe_dienste and not _reachable(*endpunkt):
                continue
            out.append(name)
            continue
        env_key = getattr(adapter, "env_key", "")
        if not env_key or os.environ.get(env_key, ""):
            out.append(name)
    return out


def answer(question: str, paths: tuple[str, ...] = ()) -> Iterator[Event]:
    """Eine Frage, die beste real verfuegbare Stufe."""
    prompt, belege, verboten = _grounded(question, paths)

    # Invariante schlaegt jede Stufe. Erst gar nicht fragen ist billiger und
    # verlaesslicher als ein Modell zu bitten, sich selbst zu verweigern.
    if verboten:
        yield from _answer_t0(question, belege, verboten)
        return

    yield _info(f"{len(belege)} Beleg(e) aus der Repo-Historie",
                belege=len(belege))

    if _model_file() and _llama_binary():
        yield from _answer_local(prompt)
        return

    frei = _remote_providers()
    if frei:
        yield _info(f"kein lokales Modell — keyloser Provider {frei[0]}", tier=T1)
        yield _info("Antwort kommt in einem Stueck, nicht tokenweise — "
                    "das Gate liefert kein Stroemen.")
        try:
            raw = _oracle().GATE.query(frei[0], "research", prompt)
            for line in str(raw).splitlines():
                yield Event("token", line)
            yield Event("ende", "", {"tier": T1, "provider": frei[0]})
            return
        except Exception as exc:
            yield _info(f"Provider {frei[0]} nicht erreichbar: {exc}")

    yield from _answer_t0(question, belege, verboten)


# ---------------------------------------------------------------------------
# Der eine Einstiegspunkt
# ---------------------------------------------------------------------------

def handle(line: str, paths: tuple[str, ...] = ()) -> Iterator[Event]:
    """Chatzeile -> Ereignisstrom. Alles laeuft hier durch — Gateway, CLI,
    Oberflaeche. Ein zweiter Einstieg waere eine zweite Sicherheitsgrenze."""
    line = (line or "").strip()
    if not line:
        yield Event("fehler", "Leere Eingabe")
        return

    if line.startswith("/"):
        name, _, rest = line[1:].partition(" ")
        name = name.strip().lower()
        if name in ("help", "hilfe", ""):
            for l in command_help():
                yield Event("token", l)
            yield Event("ende", "", {"tier": T0})
            return
        if name == "tiers":
            for t, ok, why in tiers():
                yield Event("token", f"[{'x' if ok else ' '}] {t:<4} {why}")
            yield Event("ende", "", {"tier": T0})
            return
        yield from run_command(name, rest)
        return

    yield from answer(line, paths)


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("line", nargs="?", default="/help")
    p.add_argument("--file", action="append", default=[])
    p.add_argument("--json", action="store_true",
                   help="NDJSON statt Klartext (so liest es das Gateway)")
    a = p.parse_args(argv)

    worst = 0
    try:
        worst = _emit(handle(a.line, tuple(a.file)), a.json)
    except BrokenPipeError:
        # Der Empfaenger ist weg (Verbindung getrennt, `| head`). Das ist der
        # Normalfall beim Streamen und kein Fehler -- ein Traceback hier
        # faerbte jeden abgebrochenen Chat rot.
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 0
    return worst


def _emit(events: Iterator[Event], as_json: bool) -> int:
    worst = 0
    for ev in events:
        if as_json:
            print(ev.to_json(), flush=True)
        elif ev.typ == "token":
            print(ev.text, flush=True)
        elif ev.typ == "info":
            print(f"# {ev.text}", file=sys.stderr, flush=True)
        elif ev.typ == "fehler":
            print(f"FEHLER: {ev.text}", file=sys.stderr, flush=True)
            worst = 1
        if ev.typ == "ende":
            worst = max(worst, min(int(ev.meta.get("exit", 0) or 0), 1))
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
