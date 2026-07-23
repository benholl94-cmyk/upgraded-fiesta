#!/usr/bin/env python3
"""
hugin_tool.py — HUGIN Integrierter Terminal-Editor & Gateway-Zugriff

Ersetzt den Browser als Werkzeug wenn nur Terminal-Zugang verfügbar ist.
Vollständig eigenentwickelt, kein Framework, reines Python stdlib.

Funktionen:
  ─ Interaktives ANSI-Terminal-Menü (Farbe, Cursor-Steuerung)
  ─ Speicher:   remember / search / list / export
  ─ Gateway:    health-check aller Endpunkte (parallel)
  ─ Dispatch:   Aufgaben abschicken, Antwort formatiert anzeigen
  ─ Config:     platform-config.json inline bearbeiten
  ─ Token:      Bearer-Token setzen / anzeigen
  ─ Diagnose:   Systemstatus, Ping-Latenz
  ─ Export:     Speicher-Einträge als JSON-Datei sichern

Start: python3 scripts/hugin_tool.py [--gateway URL] [--token TOKEN]
"""

import argparse
import json
import os
import sys
import time
import threading
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── Reflect-Logger (optional, lädt sich selbst nach wenn verfügbar) ───────────
try:
    _reflect_dir = str(Path(__file__).resolve().parent)
    if _reflect_dir not in sys.path:
        sys.path.insert(0, _reflect_dir)
    from hugin_reflect import task as _reflect_task, get_logger as _reflect_logger
    _REFLECT_AVAILABLE = True
except ImportError:
    _REFLECT_AVAILABLE = False
    _reflect_task = None
    _reflect_logger = None

# ── ANSI-Farbpalette ─────────────────────────────────────────────────────────
C = {
    "reset":  "\033[0m",
    "bold":   "\033[1m",
    "dim":    "\033[2m",
    "cyan":   "\033[36m",
    "bcyan":  "\033[1;36m",
    "violet": "\033[35m",
    "green":  "\033[32m",
    "amber":  "\033[33m",
    "red":    "\033[31m",
    "white":  "\033[37m",
    "gray":   "\033[90m",
    "clear":  "\033[2J\033[H",
    "line":   "\033[K",
}

REPO_ROOT   = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "ui" / "public" / "platform-config.json"
TOKEN_FILE  = REPO_ROOT / "settings" / "hugin_tool_token"
TIMEOUT_S   = 5.0

# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def c(color: str, text: str) -> str:
    if not sys.stdout.isatty():
        return text
    return C.get(color, "") + text + C["reset"]

def header(title: str) -> None:
    width = 64
    print()
    print(c("bcyan", "🜁 " + "HUGIN TOOL".center(width - 4) + " 🜁"))
    print(c("cyan", "─" * width))
    print(c("bcyan", f"  {title}"))
    print(c("cyan", "─" * width))

def success(msg: str) -> None:
    print(c("green", f"  ✓ {msg}"))

def warn(msg: str) -> None:
    print(c("amber", f"  ⚠ {msg}"))

def error(msg: str) -> None:
    print(c("red", f"  ✗ {msg}"))

def info(msg: str) -> None:
    print(c("gray", f"  · {msg}"))

def prompt(label: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    try:
        val = input(c("cyan", f"  {label}{hint}: ")).strip()
        return val if val else default
    except (EOFError, KeyboardInterrupt):
        return default

def pause() -> None:
    try:
        input(c("gray", "\n  [Enter zum Fortfahren]"))
    except (EOFError, KeyboardInterrupt):
        pass

def now_str() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

# ── Token-Verwaltung ─────────────────────────────────────────────────────────

def load_token() -> str:
    env = os.environ.get("HM_OWNER_TOKEN", "")
    if env:
        return env
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    return ""

def save_token(token: str) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token.strip())
    TOKEN_FILE.chmod(0o600)

# ── Gateway-HTTP-Client ──────────────────────────────────────────────────────

def http_request(
    url: str,
    method: str = "GET",
    body: Optional[dict] = None,
    token: str = "",
    timeout: float = TIMEOUT_S,
) -> tuple[int, Any, float]:
    """Gibt (http_status, body_dict_or_str, latency_ms) zurück."""
    t0 = time.monotonic()
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ms = round((time.monotonic() - t0) * 1000)
            raw = resp.read(65536)
            try:
                return resp.status, json.loads(raw), ms
            except Exception:
                return resp.status, raw.decode("utf-8", errors="replace"), ms
    except urllib.error.HTTPError as exc:
        ms = round((time.monotonic() - t0) * 1000)
        try:
            body_text = exc.read(4096).decode("utf-8", errors="replace")
            body_parsed = json.loads(body_text)
        except Exception:
            body_parsed = {"error": str(exc)}
        return exc.code, body_parsed, ms
    except Exception as exc:
        ms = round((time.monotonic() - t0) * 1000)
        return 0, {"error": type(exc).__name__, "detail": str(exc)[:120]}, ms

# ── Config laden ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    return {
        "platformName": "HUGIN",
        "requestTimeoutMs": 6000,
        "endpoints": [
            {"id": "primary",   "label": "Gateway · Primär",  "baseUrl": "http://127.0.0.1:8787"},
            {"id": "local",     "label": "Gateway · Lokal",   "baseUrl": "http://127.0.0.1:8080"},
            {"id": "openclaw",  "label": "OpenClaw · Agent",  "baseUrl": "http://127.0.0.1:18789"},
            {"id": "fallback",  "label": "Gateway · Fallback","baseUrl": "http://127.0.0.1:8080"},
        ],
    }

def active_gateway(cfg: dict, token: str) -> Optional[str]:
    """Gibt die baseUrl des ersten erreichbaren Endpunkts zurück."""
    for ep in cfg.get("endpoints", []):
        base = ep.get("baseUrl", "").rstrip("/")
        status, _, _ = http_request(f"{base}/health", token=token, timeout=2.0)
        if 200 <= status < 300:
            return base
    return None

# ── Menü-Aktionen ────────────────────────────────────────────────────────────

def action_health(cfg: dict, token: str) -> None:
    header("Endpunkt-Gesundheitscheck")
    endpoints = cfg.get("endpoints", [])
    results: list[dict] = [{}] * len(endpoints)
    lock = threading.Lock()

    def check(i: int, ep: dict) -> None:
        base = ep.get("baseUrl", "").rstrip("/")
        label = ep.get("label", ep.get("id", "?"))
        status, body, ms = http_request(f"{base}/health", token=token, timeout=3.0)
        with lock:
            results[i] = {"label": label, "status": status, "ms": ms, "body": body}

    threads = [threading.Thread(target=check, args=(i, ep), daemon=True)
               for i, ep in enumerate(endpoints)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    print()
    for r in results:
        if not r:
            continue
        s = r["status"]
        ms = r["ms"]
        lbl = r["label"]
        if 200 <= s < 300:
            mark = c("green", "✓ online ")
        elif s == 0:
            mark = c("red",   "✗ offline")
        else:
            mark = c("amber", f"~ {s}    ")
        body_hint = ""
        if isinstance(r["body"], dict):
            body_hint = r["body"].get("status", r["body"].get("state", ""))
        print(f"  {mark}  {c('white', lbl.ljust(28))}  {ms:4d}ms  {c('gray', str(body_hint)[:40])}")
    print()
    pause()

def action_dispatch(cfg: dict, token: str) -> None:
    header("Aufgaben-Dispatch")
    base = active_gateway(cfg, token)
    if not base:
        error("Kein erreichbarer Endpunkt — starte das Gateway zuerst.")
        pause()
        return

    task_types = ["analyze", "build", "test", "deploy", "generate", "document", "monitor", "echo", "llm-chat", "ops-tool"]
    print(c("gray", "  Aufgabentypen: " + " · ".join(task_types)))
    t_type = prompt("Aufgabentyp", "analyze")
    objective = prompt("Ziel", "Systemstatus validieren")
    payload_str = prompt("JSON-Payload", "{}")
    try:
        payload = json.loads(payload_str)
    except Exception:
        warn("Ungültiges JSON — leeres Payload wird verwendet.")
        payload = {}

    body = {
        "taskType": t_type,
        "objective": objective,
        "payload": payload,
        "submittedAt": datetime.now(timezone.utc).isoformat(),
    }
    print(c("gray", f"\n  → POST {base}/tasks ..."))
    status, resp, ms = http_request(f"{base}/tasks", method="POST", body=body, token=token)
    if 200 <= status < 300:
        success(f"Antwort in {ms}ms (HTTP {status})")
    else:
        error(f"HTTP {status} in {ms}ms")
    print(c("gray", "\n  Antwort:"))
    print(json.dumps(resp, ensure_ascii=False, indent=2))
    pause()

def action_memory_remember(cfg: dict, token: str) -> None:
    base = active_gateway(cfg, token)
    if not base:
        error("Kein Gateway erreichbar.")
        pause()
        return
    text = prompt("Text zum Speichern")
    if not text:
        return
    status, resp, ms = http_request(f"{base}/memory", method="POST", body={"text": text}, token=token)
    if 200 <= status < 300:
        success(f"Gespeichert in {ms}ms")
        if isinstance(resp, dict) and "record" in resp:
            info(f"ID: {resp['record'].get('id', '?')}")
    else:
        error(f"HTTP {status}: {resp}")
    pause()

def action_memory_search(cfg: dict, token: str) -> None:
    base = active_gateway(cfg, token)
    if not base:
        error("Kein Gateway erreichbar.")
        pause()
        return
    query = prompt("Suchanfrage")
    if not query:
        return
    top_k = int(prompt("Anzahl Ergebnisse", "5") or "5")
    status, resp, ms = http_request(
        f"{base}/memory/search",
        method="POST",
        body={"query": query, "topK": top_k},
        token=token,
    )
    if 200 <= status < 300:
        results = resp.get("results", []) if isinstance(resp, dict) else []
        success(f"{len(results)} Ergebnis(se) in {ms}ms")
        for hit in results:
            r = hit.get("record", {})
            score = hit.get("score", 0.0)
            print(f"\n  {c('cyan', f'Score {score:.4f}')}")
            print(f"  {c('white', r.get('text', ''))}")
            print(c("gray", f"  ID: {r.get('id', '')}"))
    else:
        error(f"HTTP {status}: {resp}")
    pause()

def action_memory_list(cfg: dict, token: str) -> None:
    base = active_gateway(cfg, token)
    if not base:
        error("Kein Gateway erreichbar.")
        pause()
        return
    status, resp, ms = http_request(f"{base}/memory", token=token)
    records = resp.get("records", []) if isinstance(resp, dict) else []
    success(f"{len(records)} Einträge in {ms}ms")
    for i, r in enumerate(records[-20:], 1):  # letzte 20
        print(f"  {c('gray', str(i).rjust(3))}  {c('cyan', r.get('id','')[:20])}  {r.get('text','')[:60]}")
    if len(records) > 20:
        info(f"... {len(records) - 20} ältere Einträge ausgeblendet.")
    pause()

def action_memory_export(cfg: dict, token: str) -> None:
    base = active_gateway(cfg, token)
    if not base:
        error("Kein Gateway erreichbar.")
        pause()
        return
    status, resp, ms = http_request(f"{base}/memory", token=token)
    records = resp.get("records", []) if isinstance(resp, dict) else []
    out_path = REPO_ROOT / "logs" / f"memory_export_{int(time.time())}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"exported_at": now_str(), "records": records}, ensure_ascii=False, indent=2))
    success(f"{len(records)} Einträge exportiert → {out_path.relative_to(REPO_ROOT)}")
    pause()

def action_config_edit() -> None:
    header("Konfiguration bearbeiten")
    if not CONFIG_PATH.exists():
        error(f"Konfigurationsdatei nicht gefunden: {CONFIG_PATH}")
        pause()
        return
    cfg = json.loads(CONFIG_PATH.read_text())
    print(c("gray", "\n  Aktuelle Konfiguration:\n"))
    print(json.dumps(cfg, ensure_ascii=False, indent=2))
    print()
    field = prompt("Feld zum Bearbeiten (z.B. requestTimeoutMs / leer = abbrechen)")
    if not field:
        return
    if field not in cfg:
        warn(f"Feld '{field}' nicht gefunden. Verfügbare Felder: {list(cfg.keys())}")
        pause()
        return
    cur = cfg[field]
    new_val_str = prompt(f"Neuer Wert für '{field}'", str(cur))
    try:
        # Versuche Typ beizubehalten
        if isinstance(cur, int):
            cfg[field] = int(new_val_str)
        elif isinstance(cur, bool):
            cfg[field] = new_val_str.lower() in ("true", "1", "ja", "yes")
        else:
            cfg[field] = new_val_str
    except ValueError:
        cfg[field] = new_val_str
    tmp = str(CONFIG_PATH) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)
    success(f"'{field}' → {cfg[field]} (gespeichert)")
    pause()

def action_token_set() -> None:
    header("Bearer-Token setzen")
    current = load_token()
    if current:
        info(f"Aktueller Token: {current[:8]}…{'*' * (len(current) - 8 if len(current) > 8 else 0)}")
    else:
        info("Kein Token gesetzt.")
    new_token = prompt("Neuer Token (leer = löschen)")
    if new_token:
        save_token(new_token)
        success(f"Token gespeichert in {TOKEN_FILE}")
    else:
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
        success("Token gelöscht.")
    pause()

def action_diagnostics(cfg: dict, token: str) -> None:
    header("System-Diagnose")
    import platform

    # Reflect-Logger: Task öffnen
    if _REFLECT_AVAILABLE:
        _t = __import__("hugin_reflect").Task("Diagnose: System-Status", auto_print=False)
        _t.plan("Systemstatus, Daemon-Zustand und Endpunkt-Erreichbarkeit prüfen")
    else:
        _t = None

    info(f"Python:   {platform.python_version()}")
    info(f"OS:       {platform.system()} {platform.release()}")
    info(f"Arch:     {platform.machine()}")
    info(f"Repo:     {REPO_ROOT}")
    info(f"Config:   {'✓' if CONFIG_PATH.exists() else '✗'} {CONFIG_PATH.name}")
    info(f"Token:    {'✓ gesetzt' if load_token() else '✗ fehlt'}")

    status_path = REPO_ROOT / "ui" / "public" / "platform-status.json"
    if status_path.exists():
        try:
            st = json.loads(status_path.read_text())
            info(f"Daemon:   Zyklus #{st.get('cycleCount','?')} — {st.get('updatedAt','?')}")
            active = st.get("activeId")
            info(f"Aktiv:    {active or 'keiner'}")
            if _t: _t.exec("platform-status.json", f"Daemon aktiv, Zyklus {st.get('cycleCount','?')}")
        except Exception:
            warn("platform-status.json unlesbar.")
            if _t: _t.note("platform-status.json unlesbar — JSON-Fehler")
    else:
        info("Daemon:   inaktiv (platform-status.json fehlt)")
        if _t: _t.note("Daemon inaktiv — keine Status-Datei")

    print(c("cyan", "\n  Endpunkt-Ping:"))
    ping_ok = 0
    for ep in cfg.get("endpoints", []):
        base = ep.get("baseUrl", "").rstrip("/")
        label = ep.get("label", ep.get("id", "?"))
        if not base.startswith("http"):
            print(f"  {c('gray','─')}  {label.ljust(28)}  (relative URL, kein Ping)")
            continue
        status, _, ms = http_request(f"{base}/health", token=token, timeout=2.0)
        ok = 200 <= status < 300
        if ok: ping_ok += 1
        mark = c("green", "✓") if ok else c("red", "✗")
        print(f"  {mark}  {label.ljust(28)}  {ms:4d}ms")
        if _t: _t.exec(f"ping {label}", f"HTTP {status} in {ms}ms")

    if _t:
        _t.verify("endpoint-ping", passed=(ping_ok > 0),
                  detail=f"{ping_ok}/{len(cfg.get('endpoints',[]))} Endpunkte erreichbar")
        snap = _t.reflect()
        if _t.has_errors or _t.quality_score < 70:
            print()
            snap.print()
        _reflect_logger().record(_t)

    pause()

def action_knowledge_graph(cfg: dict, token: str) -> None:
    header("Wissensgraph")
    base = active_gateway(cfg, token)
    if not base:
        error("Kein Gateway erreichbar.")
        pause()
        return
    status, resp, ms = http_request(f"{base}/memory/graph", token=token)
    if status == 404:
        warn("Kein Graph-Seed geladen. Starte: python3 scripts/generate_knowledge_graph_seed.py")
    elif 200 <= status < 300:
        nodes = resp.get("nodes", []) if isinstance(resp, dict) else []
        edges = resp.get("edges", []) if isinstance(resp, dict) else []
        success(f"{len(nodes)} Knoten, {len(edges)} Kanten — geladen in {ms}ms")
        print(c("gray", "\n  Erste 10 Knoten:"))
        for n in nodes[:10]:
            nid = n.get("id", "?")
            label = n.get("label", n.get("name", ""))
            print(f"  {c('cyan', nid.ljust(20))}  {label}")
    else:
        error(f"HTTP {status}: {resp}")
    pause()

# ── Haupt-Menü ───────────────────────────────────────────────────────────────

MENU_ITEMS = [
    ("1", "Gesundheitscheck",        "action_health"),
    ("2", "Aufgaben-Dispatch",       "action_dispatch"),
    ("3", "Speicher: Speichern",     "action_memory_remember"),
    ("4", "Speicher: Suchen",        "action_memory_search"),
    ("5", "Speicher: Liste",         "action_memory_list"),
    ("6", "Speicher: Exportieren",   "action_memory_export"),
    ("7", "Wissensgraph",            "action_knowledge_graph"),
    ("8", "Konfiguration bearbeiten","action_config_edit"),
    ("9", "Bearer-Token setzen",     "action_token_set"),
    ("0", "System-Diagnose",         "action_diagnostics"),
    ("q", "Beenden",                 None),
]

def main_menu(cfg: dict, token_ref: list) -> None:
    while True:
        if sys.stdout.isatty():
            print(C["clear"], end="")
        header(f"Hauptmenü  ·  {now_str()}")

        # Status-Zeile
        gw = cfg.get("platformName", "HUGIN")
        tok = token_ref[0]
        tok_hint = f"{tok[:8]}…" if tok else c("red", "kein Token")
        info(f"Platform: {gw}  |  Token: {tok_hint}")
        print()

        for key, label, _ in MENU_ITEMS:
            kc = c("bcyan", f"[{key}]")
            print(f"  {kc}  {label}")

        print()
        choice = prompt("Auswahl").lower()

        for key, label, fn_name in MENU_ITEMS:
            if choice == key:
                if fn_name is None:
                    print(c("cyan", "\n  Auf Wiedersehen. 🜁\n"))
                    sys.exit(0)
                fn = globals()[fn_name]
                # Token bei jeder Aktion neu laden (kann sich ändern)
                token_ref[0] = load_token()
                if fn_name == "action_config_edit":
                    fn()
                    cfg.update(load_config())
                elif fn_name == "action_token_set":
                    fn()
                    token_ref[0] = load_token()
                else:
                    fn(cfg, token_ref[0])
                break
        else:
            warn(f"Unbekannte Auswahl: '{choice}'")
            time.sleep(0.5)

# ── Einstiegspunkt ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="HUGIN Terminal-Editor & Gateway-Zugriff",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--token",   help="Bearer-Token (überschreibt gespeicherten)")
    parser.add_argument("--gateway", help="Gateway-URL (überschreibt Konfiguration)")
    parser.add_argument("--reflect", action="store_true", help="Reflect-Demo vor dem Start ausführen")
    args = parser.parse_args()

    # Reflect-Logger initialisieren (Hintergrund-Thread)
    if _REFLECT_AVAILABLE:
        _reflect_logger()  # Singleton starten

    if args.reflect and _REFLECT_AVAILABLE:
        import hugin_reflect
        hugin_reflect._run_demo()

    cfg = load_config()
    if args.gateway:
        cfg["endpoints"] = [{"id": "cli", "label": "CLI-Override", "baseUrl": args.gateway}]

    token_ref = [args.token or load_token()]

    if not sys.stdout.isatty():
        # Nicht-interaktiver Modus: Diagnose ausgeben und beenden
        if _REFLECT_AVAILABLE:
            with __import__("hugin_reflect").task("Nicht-interaktive Diagnose") as t:
                t.plan("Systemstatus im nicht-interaktiven Modus ausgeben")
                action_diagnostics(cfg, token_ref[0])
                t.exec("action_diagnostics", "Ausgabe abgeschlossen")
                t.verify("tty-check", passed=False, detail="Non-TTY Modus erkannt — korrekt")
        else:
            action_diagnostics(cfg, token_ref[0])
        sys.exit(0)

    try:
        main_menu(cfg, token_ref)
    except KeyboardInterrupt:
        print(c("cyan", "\n\n  Auf Wiedersehen. 🜁\n"))
        sys.exit(0)

if __name__ == "__main__":
    main()
