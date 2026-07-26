#!/usr/bin/env python3
"""hugin_keyring.py — Selbstversorgung mit eigenen Dienstschlüsseln.

Das Repo stellt die Schlüssel, die es selbst kontrolliert, selbst aus. Kein
externer Dienst, keine Abhängigkeit, kein manuelles Würfeln.

## Der Ansatz: hierarchisch deterministische Ableitung

Statt sechs unabhängige Zufallswerte zu erzeugen und einzeln zu sichern, gibt
es **einen** Master-Seed. Jeder Dienstschlüssel wird daraus per HKDF
(RFC 5869, hier auf hashlib/hmac aufgebaut) abgeleitet:

    key(service, version) = HKDF(master_seed, info = "service:version")

Folgen, und das ist der eigentliche Gewinn:

* **Ein Backup genügt.** Wer den Seed hat, kann jeden Dienstschlüssel jederzeit
  reproduzieren. Wer ihn verliert, verliert alle — das ist bewusst so, ein
  Seed ist leichter sicher zu verwahren als sechs Einzelwerte.
* **Rotation ist ein Zähler.** Version hochzählen, neuer Schlüssel. Die alte
  Version bleibt ableitbar, solange sie in der Karenzliste steht, also kann ein
  laufender Dienst weiterlaufen, während Clients umgestellt werden.
* **Nichts Geheimes wandert je ins Repo.** Der Seed liegt unter
  ~/.hugin/ mit Modus 0600, die abgeleiteten Schlüssel existieren nur im
  Speicher und in der Shell-Umgebung. Die Karte, welche Dienste es gibt, ist
  dagegen öffentlich und liegt hier im Code.

Das ist derselbe Mechanismus, den Hardware-Wallets für Schlüsselhierarchien
nutzen (BIP32-Idee, ohne die Kurvenarithmetik). Ungewöhnlich für
Service-Tokens, kryptografisch aber gut abgehangen und mit Bordmitteln
nachrechenbar.

## Was hier NICHT passiert

Providergebundene Schlüssel (OpenAI, Gemini, Telegram, Discord, Slack,
WhatsApp) werden **nicht** erzeugt. Sie stammen vom jeweiligen Anbieter, und
ein selbst gewürfelter Wert wäre schlicht ungültig. Für sie führt das Keyring
nur Buch: wo man sie holt, welches Format erwartet wird, ob einer gesetzt ist.

    python3 scripts/hugin_keyring.py init          # Master-Seed anlegen
    python3 scripts/hugin_keyring.py status        # was ist da, was fehlt
    python3 scripts/hugin_keyring.py env           # export-Zeilen für die Shell
    python3 scripts/hugin_keyring.py rotate HM_OWNER_TOKEN
    python3 scripts/hugin_keyring.py audit         # Leck- und Rechteprüfung
    python3 scripts/hugin_keyring.py show HM_OWNER_TOKEN --reveal

Exit: 0 in Ordnung / 1 Befund / 2 abgebrochen.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# Bewusst ausserhalb des Repos: was im Arbeitsverzeichnis liegt, landet
# irgendwann im Index. Diese Datei kann es dort gar nicht erst hinschaffen.
HOME_DIR = Path(os.environ.get("HUGIN_KEYRING_HOME", Path.home() / ".hugin"))
SEED_FILE = HOME_DIR / "master.seed"
STATE_FILE = HOME_DIR / "keyring.json"
AUDIT_FILE = HOME_DIR / "keyring-audit.jsonl"

SEED_BYTES = 32
KEY_BYTES = 32
HKDF_HASH = "sha256"


@dataclass(frozen=True)
class KeySpec:
    """Ein Eintrag der Schlüsselkarte. Öffentlich — enthält nie einen Wert."""

    env: str
    purpose: str
    self_issued: bool
    prefix: str = ""
    provider_url: str = ""
    note: str = ""


# Die Karte. Selbst ausstellbar heisst: beide Enden gehoeren dem Repo, ein
# frisch gewuerfelter Wert ist gueltig, weil niemand sonst ihn kennen muss.
KEYS: tuple[KeySpec, ...] = (
    KeySpec("HM_OWNER_TOKEN", "Gateway-Auth für jede Route", True, "hmo"),
    KeySpec("HM_DIAGNOSTICS_KEY", "Zugang zu /diagnostics", True, "hmd"),
    KeySpec("HM_MEMORY_KEY", "Schlüssel des Memory-Stores", True, "hmm"),
    KeySpec("HM_CONSOLE_SECRET", "Konsolen-/Steuerfeld-Zugang", True, "hmc"),
    KeySpec("HM_REMOTE_STORAGE_TOKEN", "Auth zwischen zwei eigenen Instanzen", True, "hmr"),
    KeySpec("HM_WHATSAPP_VERIFY_TOKEN",
            "Webhook-Verify — Wert wählst DU und hinterlegst ihn bei Meta",
            True, "hmw",
            note="Selbst ausstellbar, obwohl WhatsApp beteiligt ist: Meta "
                 "vergleicht nur, was du dort einträgst."),

    KeySpec("HUGIN_OPENAI_KEY", "OpenAI über das Oracle-Gate", False,
            provider_url="https://platform.openai.com/api-keys"),
    KeySpec("HUGIN_GEMINI_KEY", "Google Gemini über das Oracle-Gate", False,
            provider_url="https://aistudio.google.com/app/apikey"),
    KeySpec("HUGIN_MISTRAL_KEY", "Mistral über das Oracle-Gate", False,
            provider_url="https://console.mistral.ai/api-keys"),
    KeySpec("HM_TELEGRAM_BOT_TOKEN", "Telegram-Bot", False,
            provider_url="https://t.me/BotFather"),
    KeySpec("HM_DISCORD_BOT_TOKEN", "Discord-Bot", False,
            provider_url="https://discord.com/developers/applications"),
    KeySpec("HM_SLACK_BOT_TOKEN", "Slack-Bot (xoxb-)", False,
            provider_url="https://api.slack.com/apps"),
    KeySpec("HM_SLACK_APP_TOKEN", "Slack-App (xapp-)", False,
            provider_url="https://api.slack.com/apps"),
    KeySpec("HM_WHATSAPP_BOT_TOKEN", "WhatsApp Cloud API", False,
            provider_url="https://developers.facebook.com/apps"),
    KeySpec("HM_LLM_API_KEY", "Generischer LLM-Plugin-Provider", False,
            note="Anbieter je nach HM_LLM_API_URL"),
)

BY_ENV = {k.env: k for k in KEYS}
SELF_ISSUED = tuple(k for k in KEYS if k.self_issued)


# ---------------------------------------------------------------------------
# Ableitung
# ---------------------------------------------------------------------------

def hkdf(seed: bytes, info: bytes | str, length: int = KEY_BYTES,
         salt: bytes = b"") -> bytes:
    """HKDF nach RFC 5869 (extract + expand) auf hmac/hashlib.

    Bewusst von Hand statt via cryptography: das Repo ist stdlib-only, und
    diese ~10 Zeilen sind gegen die RFC-Testvektoren nachrechenbar (siehe
    tests/test_hugin_keyring.py).
    """
    info_b = info.encode() if isinstance(info, str) else info
    hash_len = hashlib.new(HKDF_HASH).digest_size
    if not 0 < length <= 255 * hash_len:
        raise ValueError(f"length muss in 1..{255 * hash_len} liegen")
    prk = hmac.new(salt or bytes(hash_len), seed, HKDF_HASH).digest()
    out, block, counter = b"", b"", 1
    while len(out) < length:
        block = hmac.new(prk, block + info_b + bytes([counter]), HKDF_HASH).digest()
        out += block
        counter += 1
    return out[:length]


def derive(seed: bytes, env: str, version: int) -> str:
    """Dienstschlüssel als lesbares Token. Präfix macht ihn im Log erkennbar,
    ohne ihn zu verraten."""
    spec = BY_ENV[env]
    raw = hkdf(seed, info=f"hugin.keyring.v1|{env}|{version}")
    body = raw.hex()[: KEY_BYTES * 2]
    return f"{spec.prefix}_{version}_{body}" if spec.prefix else body


def fingerprint(value: str) -> str:
    """Kurzer, nicht umkehrbarer Fingerabdruck — damit Statusausgaben und
    Audit-Log einen Schlüssel identifizieren können, ohne ihn zu zeigen."""
    return hashlib.sha256(value.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Zustand
# ---------------------------------------------------------------------------

@dataclass
class Keyring:
    versions: dict[str, int] = field(default_factory=dict)
    grace: dict[str, list[int]] = field(default_factory=dict)
    created: str = ""
    rotated: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls) -> Keyring:
        if not STATE_FILE.is_file():
            return cls()
        d = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return cls(versions=d.get("versions", {}), grace=d.get("grace", {}),
                   created=d.get("created", ""), rotated=d.get("rotated", {}))

    def save(self) -> None:
        HOME_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        STATE_FILE.write_text(json.dumps({
            "schema": "hugin.keyring.v1", "created": self.created,
            "versions": self.versions, "grace": self.grace, "rotated": self.rotated,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        STATE_FILE.chmod(0o600)

    def version(self, env: str) -> int:
        return self.versions.get(env, 1)


def read_seed() -> bytes | None:
    if not SEED_FILE.is_file():
        return None
    return bytes.fromhex(SEED_FILE.read_text(encoding="utf-8").strip())


def audit_log(action: str, payload: dict) -> None:
    HOME_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    line = json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "action": action, **payload}, sort_keys=True)
    with AUDIT_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    AUDIT_FILE.chmod(0o600)


# ---------------------------------------------------------------------------
# Befehle
# ---------------------------------------------------------------------------

def cmd_init(a) -> int:
    if SEED_FILE.is_file() and not a.force:
        print(f"Master-Seed existiert bereits: {SEED_FILE}", file=sys.stderr)
        print("Ein Neuanlegen macht ALLE abgeleiteten Schlüssel ungültig.\n"
              "Wenn das gewollt ist: --force", file=sys.stderr)
        return 2
    if a.force and SEED_FILE.is_file():
        print("WARNUNG: --force verwirft den bisherigen Seed.")
        print("Jeder daraus abgeleitete Schlüssel wird unbrauchbar; laufende")
        print("Dienste und hinterlegte Werte müssen neu gesetzt werden.")
        if not a.yes:
            print("\nZustimmung fehlt. Erneut mit --yes.", file=sys.stderr)
            return 2

    HOME_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    seed = secrets.token_bytes(SEED_BYTES)
    SEED_FILE.write_text(seed.hex() + "\n", encoding="utf-8")
    SEED_FILE.chmod(0o600)

    ring = Keyring(created=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    for spec in SELF_ISSUED:
        ring.versions[spec.env] = 1
    ring.save()
    audit_log("init", {"keys": [s.env for s in SELF_ISSUED]})

    print(f"Master-Seed angelegt: {SEED_FILE}  (Modus 0600, ausserhalb des Repos)")
    print(f"{len(SELF_ISSUED)} Dienstschlüssel sind daraus jetzt ableitbar.\n")
    print("SICHERE DIESE EINE DATEI. Sie ist das gesamte Geheimnis —")
    print("aus ihr lässt sich jeder Dienstschlüssel jederzeit reproduzieren,")
    print("ohne sie ist keiner wiederherstellbar.\n")
    print("In die Shell laden:  eval \"$(python3 scripts/hugin_keyring.py env)\"")
    return 0


def cmd_status(a) -> int:
    seed = read_seed()
    ring = Keyring.load()
    print(f"Master-Seed: {'vorhanden' if seed else 'FEHLT — python3 scripts/hugin_keyring.py init'}")
    print(f"Ablage:      {HOME_DIR}\n")

    print(f"{'VARIABLE':<28}{'QUELLE':<12}{'V':<4}{'UMGEBUNG':<12}HINWEIS")
    findings = 0
    for spec in KEYS:
        in_env = bool(os.environ.get(spec.env))
        if spec.self_issued:
            src = "selbst"
            ver = str(ring.version(spec.env)) if seed else "-"
            hint = "" if seed else "kein Seed"
            if not seed:
                findings += 1
        else:
            src = "Provider"
            ver = "-"
            hint = spec.provider_url or spec.note
            if not in_env:
                findings += 1
        env_state = "gesetzt" if in_env else ("ableitbar" if spec.self_issued and seed
                                              else "fehlt")
        print(f"{spec.env:<28}{src:<12}{ver:<4}{env_state:<12}{hint}")

    print(f"\n{len(SELF_ISSUED)} selbst ausgestellt, {len(KEYS) - len(SELF_ISSUED)} "
          f"providergebunden.")
    if seed:
        print("Selbst ausgestellte Schlüssel brauchen kein Backup ausser dem Seed.")
    return 1 if findings else 0


def cmd_env(a) -> int:
    seed = read_seed()
    if seed is None:
        print("Kein Master-Seed. Erst: python3 scripts/hugin_keyring.py init",
              file=sys.stderr)
        return 2
    ring = Keyring.load()
    for spec in SELF_ISSUED:
        val = derive(seed, spec.env, ring.version(spec.env))
        print(f"export {spec.env}={val}")
    missing = [s for s in KEYS if not s.self_issued and not os.environ.get(s.env)]
    if missing and not a.quiet:
        print("\n# Providergebunden, hier nicht erzeugbar — selbst holen:", file=sys.stderr)
        for s in missing:
            print(f"#   {s.env:<26} {s.provider_url or s.note}", file=sys.stderr)
    audit_log("env", {"keys": [s.env for s in SELF_ISSUED]})
    return 0


def cmd_show(a) -> int:
    spec = BY_ENV.get(a.env)
    if spec is None:
        print(f"{a.env!r} ist keine bekannte Variable.", file=sys.stderr)
        return 2
    if not spec.self_issued:
        print(f"{spec.env} ist providergebunden — hier nicht erzeugbar.")
        print(f"Beziehen: {spec.provider_url or spec.note}")
        return 1
    seed = read_seed()
    if seed is None:
        print("Kein Master-Seed.", file=sys.stderr)
        return 2
    ring = Keyring.load()
    val = derive(seed, spec.env, ring.version(spec.env))
    if a.reveal:
        print(val)
    else:
        print(f"{spec.env}  v{ring.version(spec.env)}  fp={fingerprint(val)}")
        print("Wert nur mit --reveal — sonst landet er in der Shell-Historie.")
    audit_log("show", {"key": spec.env, "revealed": bool(a.reveal),
                       "fingerprint": fingerprint(val)})
    return 0


def cmd_rotate(a) -> int:
    spec = BY_ENV.get(a.env)
    if spec is None or not spec.self_issued:
        print(f"{a.env!r} ist nicht selbst ausgestellt und damit nicht rotierbar.",
              file=sys.stderr)
        return 2
    seed = read_seed()
    if seed is None:
        print("Kein Master-Seed.", file=sys.stderr)
        return 2
    ring = Keyring.load()
    old = ring.version(spec.env)
    new = old + 1

    print(f"{spec.env}: v{old} -> v{new}")
    print(f"  alt  fp={fingerprint(derive(seed, spec.env, old))}")
    print(f"  neu  fp={fingerprint(derive(seed, spec.env, new))}")
    print(f"\nDie alte Version bleibt in der Karenzliste ableitbar, damit ein")
    print("laufender Dienst nicht sofort abreisst. Nach der Umstellung:")
    print(f"  python3 scripts/hugin_keyring.py revoke {spec.env}")
    if not a.yes:
        print("\nZustimmung fehlt. Erneut mit --yes.", file=sys.stderr)
        return 2

    ring.versions[spec.env] = new
    ring.grace.setdefault(spec.env, [])
    if old not in ring.grace[spec.env]:
        ring.grace[spec.env].append(old)
    ring.rotated[spec.env] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ring.save()
    audit_log("rotate", {"key": spec.env, "from": old, "to": new})
    print(f"\nRotiert. Neu laden: eval \"$(python3 scripts/hugin_keyring.py env)\"")
    return 0


def cmd_revoke(a) -> int:
    ring = Keyring.load()
    if not ring.grace.get(a.env):
        print(f"Keine Karenz-Versionen für {a.env}.")
        return 0
    dropped = ring.grace.pop(a.env)
    ring.save()
    audit_log("revoke", {"key": a.env, "versions": dropped})
    print(f"{a.env}: Version(en) {dropped} sind nicht mehr gültig.")
    return 0


def cmd_audit(a) -> int:
    """Leck- und Rechteprüfung. Behauptungen werden nachgerechnet."""
    findings: list[str] = []

    # 1. Liegt der Seed ausserhalb des Repos?
    try:
        HOME_DIR.resolve().relative_to(REPO.resolve())
        findings.append(f"VIOLATION  Keyring liegt IM Repo: {HOME_DIR}")
    except ValueError:
        pass

    # 2. Dateirechte
    for f in (SEED_FILE, STATE_FILE, AUDIT_FILE):
        if f.is_file():
            mode = stat.S_IMODE(f.stat().st_mode)
            if mode & 0o077:
                findings.append(f"VIOLATION  {f} ist {mode:o}, erwartet 0600")

    # 3. Ist je ein abgeleiteter Schlüssel im Repo gelandet?
    seed = read_seed()
    if seed:
        ring = Keyring.load()
        tracked = subprocess.run(["git", "grep", "-lI", "-e", "hmo_", "-e", "hmd_",
                                  "-e", "hmm_", "-e", "hmc_", "-e", "hmr_", "-e", "hmw_"],
                                 cwd=REPO, capture_output=True, text=True)
        for path in tracked.stdout.splitlines():
            if path and not path.startswith(("scripts/hugin_keyring.py", "tests/",
                                             "docs/")):
                findings.append(f"RISK       Schlüssel-Präfix in {path}")
        for spec in SELF_ISSUED:
            val = derive(seed, spec.env, ring.version(spec.env))
            hit = subprocess.run(["git", "grep", "-lF", val], cwd=REPO,
                                 capture_output=True, text=True)
            if hit.stdout.strip():
                findings.append(f"VIOLATION  {spec.env} im Index: {hit.stdout.strip()}")

    # 4. Steht die Ablage in .gitignore, falls sie doch im Repo liegt?
    gi = REPO / ".gitignore"
    if gi.is_file() and ".hugin/" not in gi.read_text(encoding="utf-8"):
        findings.append("RISK       '.hugin/' fehlt in .gitignore "
                        "(Schutz, falls HUGIN_KEYRING_HOME umgebogen wird)")

    if not findings:
        print("Keyring-Audit: sauber.")
        print(f"  Ablage ausserhalb des Repos, Rechte 0600, kein Schlüssel im Index.")
        return 0
    print(f"Keyring-Audit: {len(findings)} Befund(e)")
    for f in findings:
        print("  " + f)
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("init", help="Master-Seed anlegen")
    i.add_argument("--force", action="store_true", help="bestehenden Seed verwerfen")
    i.add_argument("--yes", action="store_true", help="Zustimmung zu --force")
    i.set_defaults(func=cmd_init)

    s = sub.add_parser("status", help="was ist da, was fehlt")
    s.set_defaults(func=cmd_status)

    e = sub.add_parser("env", help="export-Zeilen für die Shell")
    e.add_argument("--quiet", action="store_true", help="ohne Provider-Hinweise")
    e.set_defaults(func=cmd_env)

    sh = sub.add_parser("show", help="einzelnen Schlüssel ansehen")
    sh.add_argument("env")
    sh.add_argument("--reveal", action="store_true", help="Klartext ausgeben")
    sh.set_defaults(func=cmd_show)

    r = sub.add_parser("rotate", help="Schlüssel rotieren")
    r.add_argument("env")
    r.add_argument("--yes", action="store_true")
    r.set_defaults(func=cmd_rotate)

    rv = sub.add_parser("revoke", help="Karenz-Versionen endgültig ungültig machen")
    rv.add_argument("env")
    rv.set_defaults(func=cmd_revoke)

    a = sub.add_parser("audit", help="Leck- und Rechteprüfung")
    a.set_defaults(func=cmd_audit)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
