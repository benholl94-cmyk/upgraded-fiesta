#!/usr/bin/env python3
"""generate_crate_readmes.py — 1-Seiten-README pro Crate.

Vorher: 0/20 Crates haben ein README. Wer onboardet, liest entweder das
717-Zeilen-CLAUDE.md oder rÃ¤t, wozu `hm-vector` da ist.

Nachher: pro Crate ein `crates/hm-X/README.md` mit Name + Zweck + einem
Aufruf-Beispiel + Link in den Source. Generiert idempotent aus der
Cargo.toml-`description` (oder einem hartkodierten Fallback) und der
`pub const NAME`-Zeile im lib.rs.

Idempotenz: zweimal laufen lassen ist ein No-Op (Inhalte sind deterministisch
aus Cargo.toml + lib.rs abgeleitet). Manuell editierte READMEs werden NICHT
ueberschrieben (Schutzmechanismus: wenn die Datei schon existiert, skippen).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CRATES = REPO / "crates"

# Hartkodierte Zwecke (1 Zeile) fuer Crates ohne `description` in Cargo.toml.
# Wer eine bessere Beschreibung hat, tragt sie in `description = "..."` ein.
PURPOSES = {
    "hm-core": "Gemeinsame Datentypen und PluginRequest/PluginResponse-Vertrag fuer alle Crates.",
    "hm-storage": "FileStorage-Trait mit zwei Backends: LocalFsStorage (Platte) und RemoteHttpStorage (fremdes Gateway).",
    "hm-gateway": "Hand-rolled Async-TCP-HTTP-Server; einziger Auth- und Routing-Punkt fuer das ganze System.",
    "hm-agent": "TaskDispatch zu hm-plugins; verknuepft Gateway-Eingang mit Plugin-Aufruf und Memory-Eintrag.",
    "hm-memory": "Persistente MemoryStore mit semantischer Vektor-Suche + strukturellem Knowledge-Graph.",
    "hm-channels/hm-channel-telegram": "Outbound: Telegram sendMessage (HTTPS, opt-in `tls`-Feature).",
    "hm-channels/hm-channel-discord": "Outbound-Stub: validiert Bot-Token; realer Send folgt.",
    "hm-channels/hm-channel-slack": "Outbound-Stub: validiert App-Token; realer Send folgt.",
    "hm-channels/hm-channel-whatsapp": "Outbound: Meta Graph API send_message (HTTPS, opt-in `tls`-Feature).",
    "hm-tools/hm-tool-exec": "Subprocess-Plugin `ops-tool`: read-only Checks (disk/memory/gateway-status) ueber fixed allowlist.",
    "hm-tools/hm-tool-browser": "CDP-Browser-Steuerung (Chrome DevTools Protocol).",
    "hm-tools/hm-tool-web": "HTTP(S)-Fetch-Plugin mit SSRF-Schutz; HTTPS nur mit `--features tls`.",
    "hm-tools/hm-tool-media": "Media-Bearbeitungs-Plugin (Platzhalter, noch kein echter Codec).",
    "hm-plugins": "Subprocess-Plugin-Dispatcher: eine JSON-Zeile rein, eine raus, Timeout-Trennung.",
    "hm-sdk": "Gemeinsamer Wire-Code (TaskSubmission) + optionaler HTTPS-Client (`tls`-Modul).",
    "hm-sessions": "In-Memory SessionStore; exponiert via /sessions und /sessions/{id}.",
    "hm-vector": "Embedding-Vektor-Indizierung als optionale Erweiterung von hm-memory.",
    "hm-cron": "Cron-Scheduler: liest config/cron.json, ruft due Jobs als POST /tasks auf.",
    "hm-auth": "Owner-Token-Validierung mit constant-time-Vergleich (`tokens_match`).",
    "hm-cli": "Owner-Cockpit: status / rotate-token / repl / shell -- in einem Binary.",
}


def _purpose(crate_rel: str, toml_text: str) -> str:
    m = re.search(r'^description\s*=\s*"([^"]+)"', toml_text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return PURPOSES.get(crate_rel, "TODO: Zweck in Cargo.toml description="" ergaenzen.")


def _detect_pub_const_name(crate_dir: Path) -> str | None:
    """Sucht `pub const NAME: &str = "..."` in src/lib.rs oder src/main.rs."""
    for fname in ("lib.rs", "main.rs"):
        p = crate_dir / "src" / fname
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        m = re.search(r'pub const NAME:\s*&str\s*=\s*"([^"]+)"', text)
        if m:
            return m.group(1)
    return None


def _render(crate_dir: Path, crate_rel: str, purpose: str, name: str | None) -> str:
    """Rendert das README fuer ein Crate."""
    lines = [
        f"# {crate_dir.name}",
        "",
        purpose,
        "",
    ]
    if name:
        lines += [
            "## Wire-Identitaet",
            "",
            f"- Plugin/task_type-Name: `{name}`",
            "- Public-API-Stabilitaet: semver folgt `Cargo.toml` (`workspace.package.version` = `0.1.0`).",
            "",
        ]
    lines += [
        "## Aufruf (Beispiel)",
        "",
        "```bash",
        f"cargo test -p {crate_dir.name}",
        "```",
        "",
        "## Quelle",
        "",
        f"- `crates/{crate_rel}/src/`",
        f"- `crates/{crate_rel}/Cargo.toml`",
        "",
        "_Dieses README wird durch `scripts/generate_crate_readmes.py` erzeugt._",
        "_Manuelle Edits werden beim naechsten Lauf nicht ueberschrieben (Schutzmechanismus)._",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--force", action="store_true",
                   help="existierende READMEs ueberschreiben (Vorsicht: manuelle Edits weg)")
    p.add_argument("--dry-run", action="store_true",
                   help="nur anzeigen, was geschrieben wuerde")
    args = p.parse_args(argv)

    written = 0
    skipped = 0
    # Auch in hm-channels/ und hm-tools/ rekursiv suchen.
    seen: set[Path] = set()
    for cargo in sorted(CRATES.rglob("Cargo.toml")):
        crate_dir = cargo.parent
        if crate_dir in seen:
            continue
        seen.add(crate_dir)
        # Workspace-Crate-Name vs. Verzeichnis-Name: bei hm-channels/* und
        # hm-tools/* ist der Verzeichnisname anders als der crate-Name.
        crate_rel = crate_dir.relative_to(CRATES).as_posix()
        toml_text = cargo.read_text(encoding="utf-8")
        purpose = _purpose(crate_rel, toml_text)
        name = _detect_pub_const_name(crate_dir)
        readme = crate_dir / "README.md"
        if readme.is_file() and not args.force:
            skipped += 1
            continue
        body = _render(crate_dir, crate_rel, purpose, name)
        if args.dry_run:
            print(f"--- {crate_rel}/README.md (would write) ---")
            print(body)
        else:
            readme.write_text(body, encoding="utf-8")
            written += 1
            print(f"wrote {crate_rel}/README.md ({len(body)} bytes)")
    print(f"\n{written} written, {skipped} skipped (already exist)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
