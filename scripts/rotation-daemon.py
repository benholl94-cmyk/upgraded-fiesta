#!/usr/bin/env python3
"""
rotation-daemon.py — HUGIN Live-Rotations-Daemon
Prüft alle Endpunkte aus platform-config.json in dynamischer Rotation,
schreibt Echtzeit-Status nach ui/public/platform-status.json.
Die UI pollt diese Datei alle 5 Sekunden und aktualisiert sich automatisch.

Start: python3 scripts/rotation-daemon.py
Stop:  Ctrl+C
"""
import json
import time
import urllib.request
import urllib.error
import threading
import os
import sys
from datetime import datetime, timezone

REPO_ROOT    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH  = os.path.join(REPO_ROOT, "ui", "public", "platform-config.json")
STATUS_PATH  = os.path.join(REPO_ROOT, "ui", "public", "platform-status.json")
INTERVAL_S   = 5        # Prüfintervall in Sekunden
TIMEOUT_S    = 3.0      # HTTP-Timeout pro Endpunkt

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)

def check_endpoint(ep: dict) -> dict:
    base = ep["baseUrl"].rstrip("/")
    if not base.startswith(("http://", "https://")):
        return {
            "id": ep["id"], "label": ep["label"], "baseUrl": base,
            "state": "offline", "reason": "relative baseUrl — nicht daemon-erreichbar",
            "latencyMs": 0, "body": None,
        }
    url = base + ep.get("healthPath", "/health")
    t0  = time.monotonic()
    state, reason, body = "offline", "timeout", None
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            latency_ms = int((time.monotonic() - t0) * 1000)
            raw = resp.read(4096)
            try:
                body = json.loads(raw)
            except (ValueError, UnicodeDecodeError) as exc:
                # Bewusst schmal: json.loads wirft ValueError, decode-Fehler
                # kommen vom raw.decode-Fallback. Andere Fehler (z.B.
                # RecursionError bei zyklischer JSON) sollen eskalieren.
                log.debug("health-check returned non-json body",
                          extra={"error": str(exc), "url": url})
                body = {"raw": raw.decode("utf-8", errors="replace")[:200]}
            # Gilt als online wenn: 2xx UND Health-Wert positiv
            _HEALTHY = {"ok", "healthy", "up", "online", "running", True}
            _UNHEALTHY = {"offline", "unhealthy", "down", "error", "degraded", False}
            if isinstance(body, dict):
                val = (body.get("status") or body.get("state")
                       or body.get("health") or body.get("ok"))
                if val in _HEALTHY or val is True:
                    state  = "online"
                    reason = str(val)
                elif val in _UNHEALTHY or val is False:
                    state  = "degraded"
                    reason = str(val)
                else:
                    state  = "unknown"
                    reason = "2xx aber kein erkennbarer Health-Wert"
            else:
                state  = "unknown"
                reason = "2xx aber kein erkennbarer Health-Body"
    except urllib.error.HTTPError as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        state  = "degraded"
        reason = f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        # Engere Auswahl als `Exception`: ein DNS-Fehler, Timeout oder
        # kaputter Socket sind die realistischen Faelle hier. MemoryError
        # oder KeyboardInterrupt sollen weiter eskalieren.
        log.warning("health-check unreachable",
                    extra={"url": url, "error_type": type(exc).__name__})
        latency_ms = int((time.monotonic() - t0) * 1000)
        state  = "offline"
        reason = type(exc).__name__
    return {
        "id":        ep["id"],
        "label":     ep["label"],
        "baseUrl":   ep["baseUrl"],
        "state":     state,
        "reason":    str(reason)[:80],
        "latencyMs": latency_ms,
        "body":      body,
    }

def rotation_cycle(endpoints: list[dict]) -> list[dict]:
    """Prüft alle Endpunkte parallel und gibt sortierte Ergebnisse zurück."""
    results: list[dict] = [{}] * len(endpoints)
    threads = []
    def run(i: int, ep: dict) -> None:
        results[i] = check_endpoint(ep)
    for i, ep in enumerate(endpoints):
        t = threading.Thread(target=run, args=(i, ep), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=TIMEOUT_S + 1)
    return results

def pick_active(results: list[dict]) -> str | None:
    """Wählt den ersten online-Endpunkt als aktiven."""
    for r in results:
        if r.get("state") == "online":
            return r["id"]
    for r in results:
        if r.get("state") == "degraded":
            return r["id"]
    return None

def write_status(results: list[dict], cycle: int, config_name: str) -> None:
    active = pick_active(results)
    status = {
        "schema":       "hugin.rotation.status.v1",
        "platformName": config_name,
        "updatedAt":    now_iso(),
        "cycleCount":   cycle,
        "activeId":     active,
        "endpoints":    results,
    }
    tmp = STATUS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATUS_PATH)  # atomic write

def main() -> None:
    print(f"[HUGIN Rotation Daemon] Start — {now_iso()}")
    print(f"  Config : {CONFIG_PATH}")
    print(f"  Status : {STATUS_PATH}")
    print(f"  Interval: {INTERVAL_S}s\n")

    cycle = 0
    while True:
        try:
            config    = load_config()
            endpoints = config.get("endpoints", [])
            results   = rotation_cycle(endpoints)
            active    = pick_active(results) or "—"
            write_status(results, cycle, config.get("platformName", "HUGIN"))

            # Konsolenausgabe
            online  = sum(1 for r in results if r.get("state") == "online")
            total   = len(results)
            print(f"[{now_iso()}] Zyklus {cycle:4d} · {online}/{total} online · aktiv={active}")
            for r in results:
                mark = {"online": "✓", "degraded": "~", "offline": "✗", "unknown": "?"}.get(r.get("state","?"), "?")
                print(f"  {mark} {r.get('label','?'):28s} {r.get('state','?'):10s} {r.get('latencyMs',0):4d}ms  {r.get('reason','')}")
            print()

            cycle += 1
        except KeyboardInterrupt:
            print("\n[HUGIN Rotation Daemon] Gestoppt.")
            sys.exit(0)
        except Exception as exc:
            print(f"[FEHLER] {exc}", file=sys.stderr)

        time.sleep(INTERVAL_S)

if __name__ == "__main__":
    main()
