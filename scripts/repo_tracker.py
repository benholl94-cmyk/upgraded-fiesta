#!/usr/bin/env python3
"""
repo_tracker.py — Inkrementeller Workspace-Index für upgraded-fiesta.

Statt vollem Repo-Audit bei jeder Session: einmal scannen, dann nur
noch geänderte Dateien (via mtime) neu prüfen.

Commands:
  scan    — Vollscan: Index neu aufbauen (alle überwachten Pfade)
  update  — Inkrementell: nur mtime-geänderte Dateien prüfen
  status  — Drift seit letztem scan/update anzeigen
  audit   — Synergy-Checks über registrierte Logik-Regeln laufen lassen
  show    — Index-Statistik anzeigen
  watch   — Kontinuierlicher Update-Loop (--interval SECS, default 120)
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
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import logging
log = logging.getLogger(__name__)

# ── Pfade ─────────────────────────────────────────────────────────────────────
REPO_ROOT   = Path(__file__).resolve().parent.parent
INDEX_FILE  = REPO_ROOT / ".claude" / "persona" / "repo-index.json"
REPORT_FILE = REPO_ROOT / ".claude" / "persona" / "tracker-report.json"

# ── Überwachte Pfade (Glob-Muster relativ zu REPO_ROOT) ──────────────────────
WATCH_PATTERNS: list[tuple[str, str]] = [
    # (glob-pattern, kategorie)
    ("crates/**/*.rs",           "rust"),
    ("crates/**/*.toml",         "rust"),
    ("plugins/*.py",             "plugin"),
    ("scripts/*.py",             "script"),
    ("config/*.json",            "config"),
    ("ui/src/**/*.ts",           "ui"),
    ("ui/src/**/*.tsx",          "ui"),
    ("ui/public/*.json",         "ui"),
    (".claude/persona/*.json",   "persona"),
    (".claude/agents/*.md",      "persona"),
    ("Dockerfile",               "infra"),
    ("docker-compose.yml",       "infra"),
    (".env.production.example",  "infra"),
    ("CLAUDE.md",                "meta"),
    ("AGENTS.md",                "meta"),
]

# ── Synergy-Regeln (Logik-Audits, keine Hash-Checks) ─────────────────────────
def _rule_plugin_response_fields() -> dict:
    """Alle Plugin-Python-Dateien müssen 'result' statt 'output' zurückgeben."""
    issues = []
    for p in (REPO_ROOT / "plugins").glob("*.py"):
        text = p.read_text(errors="replace")
        if '"output"' in text or "'output'" in text:
            # Prüfe ob es ein PluginResponse-Return ist (nicht nur ein Kommentar)
            for i, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if ('"output"' in line or "'output'" in line) and "result" not in line:
                    issues.append(f"{p.name}:{i} — 'output' statt 'result'")
    return {"rule": "plugin_response_fields", "ok": len(issues) == 0,
            "issues": issues, "note": "PluginResponse serde erwartet 'result' + 'message'"}

def _rule_cargo_deps_consistent() -> dict:
    """hm-gateway Cargo.toml muss alle intern genutzten Crates listen."""
    required = ["hm-storage", "hm-plugins", "hm-memory", "hm-agent",
                 "hm-auth", "hm-cron", "hm-sessions"]
    toml = (REPO_ROOT / "crates" / "hm-gateway" / "Cargo.toml").read_text()
    missing = [d for d in required if d not in toml]
    return {"rule": "gateway_cargo_deps", "ok": len(missing) == 0,
            "issues": [f"missing: {m}" for m in missing],
            "note": "Alle genutzten Crates müssen in Cargo.toml stehen"}

def _rule_plugins_json_registered() -> dict:
    """Alle task_types aus config/plugins.json müssen reale Command-Dateien haben."""
    cfg = REPO_ROOT / "config" / "plugins.json"
    if not cfg.exists():
        return {"rule": "plugins_registered", "ok": False,
                "issues": ["config/plugins.json fehlt"], "note": ""}
    data = json.loads(cfg.read_text())
    issues = []
    for entry in data.get("plugins", []):
        cmd = entry.get("command", [])
        if not cmd:
            continue
        # Nur Dateipfade prüfen (nicht Binaries wie target/release/...)
        target = cmd[-1] if len(cmd) > 1 else cmd[0]
        if target.startswith("plugins/") or target.startswith("scripts/"):
            full = REPO_ROOT / target
            if not full.exists():
                issues.append(f"{entry['task_type']}: {target} nicht gefunden")
    return {"rule": "plugins_json_registered", "ok": len(issues) == 0,
            "issues": issues, "note": "Plugin-Commands müssen existieren"}

def _rule_env_vars_documented() -> dict:
    """Alle HM_* Vars in main.rs müssen in .env.production.example stehen."""
    main = (REPO_ROOT / "crates" / "hm-gateway" / "src" / "main.rs").read_text()
    env_doc = (REPO_ROOT / ".env.production.example").read_text()
    vars_in_code = set(re.findall(r'env::var\("(HM_[A-Z_]+)"\)', main))
    missing = [v for v in vars_in_code if v not in env_doc]
    return {"rule": "env_vars_documented", "ok": len(missing) == 0,
            "issues": [f"undokumentiert: {v}" for v in sorted(missing)],
            "note": "Alle HM_* Vars müssen in .env.production.example stehen"}

def _rule_platform_config_port() -> dict:
    """ui/public/platform-config.json primary endpoint darf nicht auf Port 8787 zeigen."""
    cfg = REPO_ROOT / "ui" / "public" / "platform-config.json"
    if not cfg.exists():
        return {"rule": "platform_config_port", "ok": False,
                "issues": ["platform-config.json fehlt"], "note": ""}
    text = cfg.read_text()
    bad = re.findall(r'127\.0\.0\.1:8787', text)
    return {"rule": "platform_config_port", "ok": len(bad) == 0,
            "issues": [f"{len(bad)}× Port 8787 gefunden"] if bad else [],
            "note": "Primary endpoint muss auf 8080 (hm-gateway) zeigen"}

def _rule_console_log_schema() -> dict:
    """hardware_console.py muss {'entries':[...]} schreiben, nicht flat list."""
    src = (REPO_ROOT / "scripts" / "hardware_console.py").read_text()
    has_entries_key = '"entries"' in src and 'log["entries"]' in src
    flat_write = 'json.dumps(log["entries"]' not in src  # sollte nie flat schreiben
    ok = has_entries_key
    return {"rule": "console_log_schema", "ok": ok,
            "issues": [] if ok else ["hardware_console.py schreibt kein {'entries':[...]} Format"],
            "note": "security_sentinel.py erwartet log['entries'] Schlüssel"}

def _rule_graph_seed_exists() -> dict:
    """data/graph-seed.json muss existieren (knowledge graph für /memory/graph)."""
    seed = REPO_ROOT / "data" / "graph-seed.json"
    if not seed.exists():
        return {"rule": "graph_seed_exists", "ok": False,
                "issues": ["data/graph-seed.json fehlt — HM_MEMORY_GRAPH_SEED_PATH nicht nutzbar"],
                "note": "Generieren: python3 scripts/generate_knowledge_graph_seed.py --out data/graph-seed.json"}
    try:
        d = json.loads(seed.read_text())
        nodes = len(d.get("nodes", []))
        edges = len(d.get("edges", []))
        return {"rule": "graph_seed_exists", "ok": nodes > 0,
                "issues": [] if nodes > 0 else ["Seed hat 0 Nodes"],
                "note": f"{nodes} Nodes, {edges} Edges"}
    except Exception as e:
        log.warning("swallowed in repo_tracker: %s", exc)
        return {"rule": "graph_seed_exists", "ok": False,
                "issues": [f"Ungültiges JSON: {e}"], "note": ""}

def _rule_oracle_config_exists() -> dict:
    """oracle-config.json muss existieren (hugin_oracle.py dead reference)."""
    cfg = REPO_ROOT / ".claude" / "persona" / "oracle-config.json"
    ok = cfg.exists()
    return {"rule": "oracle_config_exists", "ok": ok,
            "issues": [] if ok else ["oracle-config.json fehlt — hugin_oracle.py hat dead reference"],
            "note": "Wird von hugin_oracle.py als CONFIG_FILE geladen"}

def _rule_hugin_index_sync() -> dict:
    """hugin/index.html muss bytewise identisch mit hugin/hugin.html sein (GitHub Pages root)."""
    src = REPO_ROOT / "hugin" / "hugin.html"
    dst = REPO_ROOT / "hugin" / "index.html"
    if not src.exists():
        return {"rule": "hugin_index_sync", "ok": False,
                "issues": ["hugin/hugin.html fehlt"], "note": ""}
    if not dst.exists():
        return {"rule": "hugin_index_sync", "ok": False,
                "issues": ["hugin/index.html fehlt — GitHub Pages liefert 404 auf /"],
                "note": "Fix: cp hugin/hugin.html hugin/index.html"}
    src_hash = hashlib.sha256(src.read_bytes()).hexdigest()[:16]
    dst_hash = hashlib.sha256(dst.read_bytes()).hexdigest()[:16]
    ok = src_hash == dst_hash
    return {"rule": "hugin_index_sync", "ok": ok,
            "issues": [] if ok else [f"hugin.html ({src_hash}) ≠ index.html ({dst_hash}) — Pages wäre veraltet"],
            "note": "Fix: cp hugin/hugin.html hugin/index.html && git add + commit"}

def _rule_knowledge_feeds_reachable() -> dict:
    """Alle enabled Feeds in config/knowledge-feeds.json müssen existieren und enabled sein."""
    feeds_file = REPO_ROOT / "config" / "knowledge-feeds.json"
    if not feeds_file.exists():
        return {"rule": "knowledge_feeds_reachable", "ok": False,
                "issues": ["config/knowledge-feeds.json fehlt"], "note": ""}
    feeds = json.loads(feeds_file.read_text())
    enabled = [f for f in feeds if f.get("enabled", True)]
    issues = []
    for f in enabled:
        if "github.com/trending" in f.get("url", ""):
            issues.append(f"{f['name']}: github.com/trending gibt 403 in CI zurück — ersetzen durch Atom/API")
    return {"rule": "knowledge_feeds_reachable", "ok": len(issues) == 0,
            "issues": issues, "note": f"{len(enabled)} Feeds aktiv"}

SYNERGY_RULES = [
    _rule_plugin_response_fields,
    _rule_cargo_deps_consistent,
    _rule_plugins_json_registered,
    _rule_env_vars_documented,
    _rule_platform_config_port,
    _rule_console_log_schema,
    _rule_graph_seed_exists,
    _rule_oracle_config_exists,
    _rule_hugin_index_sync,
    _rule_knowledge_feeds_reachable,
]

# ── Index-Operationen ─────────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return "ERROR"

def _git_blob(path: Path) -> str:
    try:
        rel = path.relative_to(REPO_ROOT)
        r = subprocess.run(
            ["git", "ls-files", "-s", str(rel)],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=5
        )
        parts = r.stdout.strip().split()
        return parts[1] if len(parts) >= 2 else "untracked"
    except Exception as exc:
        log.warning("swallowed in repo_tracker: %s", exc)
        return "unknown"

def _collect_paths() -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for pattern, _ in WATCH_PATTERNS:
        for p in sorted(REPO_ROOT.glob(pattern)):
            if p.is_file() and p not in seen:
                seen.add(p)
                result.append(p)
    return result

def _record(path: Path, kategorie: str) -> dict:
    stat = path.stat()
    return {
        "path":       str(path.relative_to(REPO_ROOT)),
        "kategorie":  kategorie,
        "sha256":     _sha256(path),
        "git_blob":   _git_blob(path),
        "size":       stat.st_size,
        "mtime":      stat.st_mtime,
        "last_seen":  _now(),
    }

def _kategorie(path: Path) -> str:
    for pattern, kat in WATCH_PATTERNS:
        if path.match(pattern) or path.relative_to(REPO_ROOT).match(pattern):
            return kat
    return "other"

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _load_index() -> dict:
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text())
    return {"created": _now(), "updated": _now(), "files": {}}

def _save_index(idx: dict) -> None:
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    idx["updated"] = _now()
    INDEX_FILE.write_text(json.dumps(idx, indent=2, ensure_ascii=False) + "\n")

# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_scan(verbose: bool = False) -> dict:
    """Vollscan: gesamten Index neu aufbauen."""
    paths = _collect_paths()
    files: dict[str, dict] = {}
    for p in paths:
        kat = _kategorie(p)
        rec = _record(p, kat)
        files[rec["path"]] = rec
        if verbose:
            print(f"  [{kat:8s}] {rec['path']}")
    idx = {"created": _now(), "updated": _now(), "files": files}
    _save_index(idx)
    print(f"scan: {len(files)} Dateien indexiert → {INDEX_FILE.relative_to(REPO_ROOT)}")
    return idx

def cmd_update(verbose: bool = False) -> dict:
    """Inkrementell: nur Dateien mit geänderter mtime neu prüfen."""
    idx = _load_index()
    files = idx.get("files", {})
    changed = added = removed = 0

    # Bekannte Dateien auf mtime prüfen
    for rel, rec in list(files.items()):
        p = REPO_ROOT / rel
        if not p.exists():
            files[rel]["status"] = "DELETED"
            removed += 1
            continue
        stat = p.stat()
        if stat.st_mtime != rec.get("mtime") or stat.st_size != rec.get("size"):
            new_rec = _record(p, rec.get("kategorie", "other"))
            old_hash = rec.get("sha256")
            new_rec["status"] = "MODIFIED" if new_rec["sha256"] != old_hash else "TOUCHED"
            files[rel] = new_rec
            changed += 1
            if verbose:
                print(f"  {new_rec['status']:8s} {rel}")
        else:
            files[rel].pop("status", None)  # sauber

    # Neue Dateien entdecken
    current_paths = _collect_paths()
    for p in current_paths:
        rel = str(p.relative_to(REPO_ROOT))
        if rel not in files:
            kat = _kategorie(p)
            rec = _record(p, kat)
            rec["status"] = "NEW"
            files[rel] = rec
            added += 1
            if verbose:
                print(f"  {'NEW':8s} {rel}")

    idx["files"] = files
    _save_index(idx)
    print(f"update: {changed} geändert, {added} neu, {removed} gelöscht")
    return idx

def cmd_status() -> None:
    """Drift seit letztem scan/update anzeigen."""
    idx = _load_index()
    files = idx.get("files", {})
    drift = {k: v for k, v in files.items() if v.get("status") in ("MODIFIED", "DELETED", "NEW")}
    if not drift:
        print(f"status: CLEAN — {len(files)} Dateien, kein Drift")
        print(f"  Index zuletzt aktualisiert: {idx.get('updated', '?')}")
        return
    print(f"status: {len(drift)} Änderungen seit letztem Update:")
    for rel, rec in sorted(drift.items()):
        s = rec.get("status", "?")
        print(f"  [{s:8s}] {rel}")

def cmd_audit() -> None:
    """Synergy-Logik-Checks laufen lassen und Bericht speichern."""
    results = []
    passed = failed = 0
    for rule_fn in SYNERGY_RULES:
        try:
            r = rule_fn()
        except Exception as e:
            log.warning("swallowed in repo_tracker: %s", exc)
            r = {"rule": rule_fn.__name__, "ok": False,
                 "issues": [f"Ausnahme: {e}"], "note": ""}
        results.append(r)
        if r["ok"]:
            passed += 1
            print(f"  ✓ {r['rule']}")
        else:
            failed += 1
            print(f"  ✗ {r['rule']}")
            for iss in r.get("issues", []):
                print(f"      → {iss}")

    report = {
        "generated": _now(),
        "passed": passed,
        "failed": failed,
        "total": passed + failed,
        "score": round(100 * passed / (passed + failed), 1) if (passed + failed) else 0,
        "rules": results,
    }
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"\naudit: {passed}/{passed+failed} Regeln OK — Score {report['score']}%")
    print(f"  Bericht → {REPORT_FILE.relative_to(REPO_ROOT)}")

def cmd_show() -> None:
    """Index-Statistik anzeigen."""
    idx = _load_index()
    files = idx.get("files", {})
    if not files:
        print("show: Kein Index vorhanden — zuerst 'scan' ausführen")
        return
    cats: dict[str, int] = {}
    for rec in files.values():
        k = rec.get("kategorie", "other")
        cats[k] = cats.get(k, 0) + 1
    print(f"Index: {len(files)} Dateien, zuletzt aktualisiert {idx.get('updated', '?')}")
    for kat, count in sorted(cats.items()):
        print(f"  {kat:12s}: {count}")

def cmd_watch(interval: int) -> None:
    """Kontinuierlicher Update-Loop."""
    print(f"watch: Update alle {interval}s (Ctrl-C zum Beenden)")
    while True:
        try:
            cmd_update()
            cmd_audit()
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nwatch: beendet")
            break

# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Inkrementeller Workspace-Tracker für upgraded-fiesta",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("command", choices=["scan", "update", "status", "audit", "show", "watch"])
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--interval", type=int, default=120, help="Watch-Interval in Sekunden")
    args = ap.parse_args()

    if args.command == "scan":
        cmd_scan(verbose=args.verbose)
    elif args.command == "update":
        cmd_update(verbose=args.verbose)
    elif args.command == "status":
        cmd_status()
    elif args.command == "audit":
        cmd_audit()
    elif args.command == "show":
        cmd_show()
    elif args.command == "watch":
        cmd_watch(args.interval)

if __name__ == "__main__":
    main()
