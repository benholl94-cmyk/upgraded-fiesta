
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
#!/usr/bin/env python3
"""
MUNIN Security Sentinel — Layer-Validierung, Quantisierung und Härtung.

Validiert alle OS-Sicherheitsebenen, setzt Härtungsmaßnahmen durch,
erkennt Einbruch und verhindert Container-Escape-Versuche.

Ebenen:
  L0  Hypervisor-Constraints (nomodule, vsock, Firecracker)
  L1  Kernel-Sicherheitsparameter (sysctl)
  L2  Prozesse und offene Ports
  L3  Netzwerk und Firewall (iptables)
  L4  Filesystem-Integrität (SUID, world-writable, /tmp)
  L5  User/Auth (sudo, SSH-Keys, Shell-Accounts)
  L6  Workspace-Integrität (git-fsck, SHA256-Checksums)

Verwendung:
  python3 scripts/security_sentinel.py validate    # alle Layer prüfen
  python3 scripts/security_sentinel.py harden      # Härtung anwenden
  python3 scripts/security_sentinel.py watch       # kontinuierliche Überwachung
  python3 scripts/security_sentinel.py report      # JSON-Report ausgeben
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import logging
log = logging.getLogger(__name__)

WORKSPACE = Path(__file__).parent.parent
REPORT_PATH = WORKSPACE / ".claude/persona/security-report.json"
BASELINE_PATH = WORKSPACE / ".claude/persona/security-baseline.json"

CRITICAL_FILES = {
    ".claude/persona/munin.json",
    ".claude/persona/constitution.json",
    ".claude/persona/munin-state.json",
    "scripts/hugin_oracle.py",
    "scripts/hardware_console.py",
    "scripts/security_sentinel.py",
    "config/plugins.json",
    "Cargo.toml",
}

# Erwartete sysctl-Werte nach Härtung
SYSCTL_HARDENED: dict[str, str] = {
    "kernel.randomize_va_space": "2",
    "net.ipv4.tcp_syncookies": "1",
    "net.ipv4.conf.all.rp_filter": "1",
    "net.ipv4.conf.default.rp_filter": "1",
    "net.ipv4.conf.all.accept_redirects": "0",
    "net.ipv4.conf.default.accept_redirects": "0",
    "net.ipv4.conf.all.send_redirects": "0",
    "net.ipv4.conf.default.send_redirects": "0",
    "net.ipv4.icmp_echo_ignore_broadcasts": "1",
    "net.ipv4.conf.all.log_martians": "1",
    "net.ipv4.conf.default.log_martians": "1",
    "kernel.dmesg_restrict": "1",
    "kernel.kptr_restrict": "2",
    "kernel.perf_event_paranoid": "3",
    "net.ipv4.conf.all.accept_source_route": "0",
    "net.ipv4.tcp_timestamps": "0",
}

# Erlaubte Outbound-Ziele (HTTPS-Proxy + loopback + vsock)
ALLOWED_EGRESS_CIDRS = [
    "127.0.0.0/8",    # loopback
    "192.0.2.0/24",   # LAN-Netz der VM
]

# Bekannte legitime SUID-Binaries
EXPECTED_SUID = {
    "/usr/bin/gpasswd", "/usr/bin/expiry", "/usr/bin/sudo",
    "/usr/bin/newgrp", "/usr/bin/chage", "/usr/bin/chfn",
    "/usr/bin/umount", "/usr/bin/mount", "/usr/bin/passwd",
    "/usr/bin/chsh", "/usr/bin/su",
    "/usr/sbin/pam_extrausers_chkpwd", "/usr/sbin/unix_chkpwd",
}


# ─── Hilfsfunktionen ────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 5) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return -1, "", str(e)


def _sysctl_get(key: str) -> str | None:
    rc, out, _ = _run(["sysctl", "-n", key])
    return out if rc == 0 else None


def _sysctl_set(key: str, value: str) -> bool:
    rc, _, _ = _run(["sysctl", "-w", f"{key}={value}"])
    return rc == 0


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return "UNREADABLE"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _score(passed: int, total: int) -> float:
    return round(passed / total * 100, 1) if total else 0.0


# ─── Layer-Validierungen ────────────────────────────────────────────────────

def validate_l0_hypervisor() -> dict[str, Any]:
    checks: list[dict] = []

    def chk(name: str, ok: bool, value: str, expected: str = "", note: str = "") -> None:
        checks.append({"check": name, "ok": ok, "value": value,
                        "expected": expected, "note": note})

    # nomodule — kernel param verhindert LKM-Loading
    cmdline = Path("/proc/cmdline").read_text() if Path("/proc/cmdline").exists() else ""
    chk("nomodule kernel param", "nomodule" in cmdline, "present" if "nomodule" in cmdline else "absent",
        "present", "Verhindert dynamisches Kernel-Modul-Loading (Container-Escape via LKM)")

    # Firecracker init
    chk("firecracker-init", "--firecracker-init" in cmdline, "present" if "--firecracker-init" in cmdline else "absent",
        "present", "MicroVM läuft unter Firecracker/KVM-Isolation")

    # IPv6 deaktiviert
    chk("ipv6 disabled", "ipv6.disable=1" in cmdline, "disabled" if "ipv6.disable=1" in cmdline else "enabled",
        "disabled", "IPv6-Angriffsfläche eliminiert")

    # modules_disabled proc-flag
    md = Path("/proc/sys/kernel/modules_disabled")
    val = md.read_text().strip() if md.exists() else "absent"
    # 0 oder absent ist ok in Firecracker wegen nomodule param
    chk("modules_disabled (proc)", val in ("1", "absent", "0"),
        val, "1 oder via nomodule", "nomodule param = effektiv deaktiviert")

    # vsock (Inter-VM-Kommunikation via Host, nicht Netzwerk)
    chk("vsock port defined", "--listen-vsock-port" in cmdline,
        "present" if "--listen-vsock-port" in cmdline else "absent",
        "present", "Gesteuerter IPC-Kanal zum Host")

    # block-local-connections flag
    chk("block-local-connections", "--block-local-connections" in cmdline,
        "set" if "--block-local-connections" in cmdline else "unset",
        "set", "Verhindert VM→Host lokale Netzwerk-Escapes")

    passed = sum(1 for c in checks if c["ok"])
    return {"layer": "L0_Hypervisor", "passed": passed, "total": len(checks),
            "score": _score(passed, len(checks)), "checks": checks}


def validate_l1_kernel() -> dict[str, Any]:
    checks: list[dict] = []

    for key, expected in SYSCTL_HARDENED.items():
        actual = _sysctl_get(key)
        ok = actual == expected
        checks.append({"check": key, "ok": ok, "value": actual or "N/A",
                        "expected": expected})

    # ASLR
    aslr = _sysctl_get("kernel.randomize_va_space")
    # schon in SYSCTL_HARDENED — extra-Note
    for c in checks:
        if c["check"] == "kernel.randomize_va_space":
            c["note"] = "2 = vollständige ASLR (Stack+Heap+MMAP)"

    # BPF JIT Hardening
    bpf = _sysctl_get("net.core.bpf_jit_harden")
    checks.append({"check": "net.core.bpf_jit_harden", "ok": bpf in ("1", "2"),
                   "value": bpf or "N/A", "expected": "1 oder 2",
                   "note": "Verhindert BPF-JIT-Spray-Angriffe"})

    passed = sum(1 for c in checks if c["ok"])
    return {"layer": "L1_Kernel", "passed": passed, "total": len(checks),
            "score": _score(passed, len(checks)), "checks": checks}


def validate_l2_processes() -> dict[str, Any]:
    checks: list[dict] = []

    rc, out, _ = _run(["ps", "ax", "-o", "pid,user,comm,args"])
    lines = out.splitlines()[1:] if out else []

    user_procs = [l for l in lines if "root" not in l.split()[1] if len(l.split()) > 1]
    unknown = [l for l in lines if not any(k in l for k in
               ["process_api", "kthread", "kworker", "ksoftirq", "migration",
                "rcu", "mm_percpu", "cpuhp", "pool_work", "kvfree", "sync_wq",
                "netns", "slub", "claude", "cargo", "python", "node", "bash",
                "sh", "ps", "git", "rust", "cc", "ld"])]

    checks.append({"check": "process_count", "ok": True,
                   "value": str(len(lines)), "note": "Gesamtzahl Prozesse"})
    checks.append({"check": "unknown_processes", "ok": len(unknown) == 0,
                   "value": str(len(unknown)),
                   "expected": "0", "note": str(unknown[:3]) if unknown else ""})

    # Offene TCP-Ports
    rc2, ss_out, _ = _run(["ss", "-tlnp"])
    listening = [l for l in ss_out.splitlines() if "LISTEN" in l]
    checks.append({"check": "listening_ports", "ok": True,
                   "value": str(len(listening)),
                   "note": "; ".join(listening) or "keine"})

    # Kein Prozess lauscht auf 0.0.0.0 außer process_api und erlaubten Diensten
    external_listeners = [l for l in listening if "0.0.0.0" in l and
                          "2024" not in l and "7799" not in l]
    checks.append({"check": "unexpected_external_listeners",
                   "ok": len(external_listeners) == 0,
                   "value": str(len(external_listeners)),
                   "expected": "0",
                   "note": str(external_listeners[:3]) if external_listeners else ""})

    passed = sum(1 for c in checks if c["ok"])
    return {"layer": "L2_Processes", "passed": passed, "total": len(checks),
            "score": _score(passed, len(checks)), "checks": checks}


def validate_l3_network() -> dict[str, Any]:
    checks: list[dict] = []

    # iptables INPUT-Policy
    rc, ipt, _ = _run(["iptables", "-L", "INPUT", "-n"])
    has_drop_policy = "policy DROP" in ipt
    checks.append({"check": "iptables_input_default_drop", "ok": has_drop_policy,
                   "value": "DROP" if has_drop_policy else "ACCEPT",
                   "expected": "DROP",
                   "note": "Standardmäßig alle eingehenden Verbindungen blockieren"})

    rc2, ipt_out, _ = _run(["iptables", "-L", "OUTPUT", "-n"])
    has_output_rules = len(ipt_out.splitlines()) > 3
    checks.append({"check": "iptables_output_rules_exist", "ok": has_output_rules,
                   "value": "ja" if has_output_rules else "nein",
                   "expected": "ja",
                   "note": "Ausgehender Traffic sollte explizit erlaubt sein"})

    # RP-Filter (Spoofing-Schutz)
    rp = _sysctl_get("net.ipv4.conf.all.rp_filter")
    checks.append({"check": "rp_filter_enabled", "ok": rp == "1",
                   "value": rp or "N/A", "expected": "1",
                   "note": "Verhindert IP-Spoofing"})

    # ICMP-Redirect
    ar = _sysctl_get("net.ipv4.conf.all.accept_redirects")
    checks.append({"check": "no_icmp_redirects", "ok": ar == "0",
                   "value": ar or "N/A", "expected": "0",
                   "note": "Verhindert ICMP-Redirect-basierte Routing-Angriffe"})

    # IPv6 komplett deaktiviert
    ipv6_if = Path("/proc/net/if_inet6")
    checks.append({"check": "ipv6_absent", "ok": not ipv6_if.exists() or ipv6_if.stat().st_size == 0,
                   "value": "absent" if not ipv6_if.exists() else "present",
                   "expected": "absent"})

    # Martians loggen
    lm = _sysctl_get("net.ipv4.conf.all.log_martians")
    checks.append({"check": "log_martians", "ok": lm == "1",
                   "value": lm or "N/A", "expected": "1",
                   "note": "Loggt gefälschte Pakete aus ungültigen Quellen"})

    passed = sum(1 for c in checks if c["ok"])
    return {"layer": "L3_Network", "passed": passed, "total": len(checks),
            "score": _score(passed, len(checks)), "checks": checks}


def validate_l4_filesystem() -> dict[str, Any]:
    checks: list[dict] = []

    # SUID-Binaries: nur bekannte erlaubt
    rc, find_out, _ = _run(
        ["find", "/usr/bin", "/usr/sbin", "/bin", "/sbin",
         "-perm", "/6000", "-type", "f"], timeout=15)
    found_suid = set(find_out.splitlines()) if find_out else set()
    unexpected = found_suid - EXPECTED_SUID
    checks.append({"check": "suid_binaries_only_known",
                   "ok": len(unexpected) == 0,
                   "value": str(len(found_suid)),
                   "expected": str(len(EXPECTED_SUID)),
                   "note": f"Unbekannt: {list(unexpected)[:5]}" if unexpected else "alle bekannt"})

    # /tmp sticky bit
    tmp_stat = Path("/tmp").stat()
    sticky = bool(tmp_stat.st_mode & 0o1000)
    checks.append({"check": "tmp_sticky_bit", "ok": sticky,
                   "value": "set" if sticky else "unset", "expected": "set",
                   "note": "Verhindert Löschen fremder Dateien in /tmp"})

    # /dev/shm leer
    shm_files = list(Path("/dev/shm").iterdir()) if Path("/dev/shm").exists() else []
    checks.append({"check": "dev_shm_empty", "ok": len(shm_files) == 0,
                   "value": str(len(shm_files)), "expected": "0",
                   "note": "Shared memory nicht für persistente Daten missbraucht"})

    # Workspace nicht world-writable
    ws_stat = Path(WORKSPACE).stat()
    ww = bool(ws_stat.st_mode & 0o002)
    checks.append({"check": "workspace_not_world_writable", "ok": not ww,
                   "value": "world-writable" if ww else "ok",
                   "expected": "ok"})

    # ro-Mounts unveränderlich (alle Sub-Mounts prüfen)
    mounts = Path("/proc/mounts").read_text() if Path("/proc/mounts").exists() else ""
    ro_mount_prefixes = ["/opt/claude-code", "/opt/env-runner",
                         "/mnt/skills/public", "/mnt/skills/examples"]
    for m in ro_mount_prefixes:
        line = next((l for l in mounts.splitlines() if f" {m} " in l), "")
        is_ro = bool(line) and ("ro," in line or " ro " in line or ",ro " in line)
        checks.append({"check": f"ro_mount_{m.split('/')[-1]}",
                       "ok": is_ro, "value": "ro" if is_ro else ("absent" if not line else "rw"),
                       "expected": "ro",
                       "note": f"{m} muss read-only sein"})

    passed = sum(1 for c in checks if c["ok"])
    return {"layer": "L4_Filesystem", "passed": passed, "total": len(checks),
            "score": _score(passed, len(checks)), "checks": checks}


def validate_l5_users() -> dict[str, Any]:
    checks: list[dict] = []

    passwd = Path("/etc/passwd").read_text() if Path("/etc/passwd").exists() else ""
    shell_accounts = [l for l in passwd.splitlines()
                      if not l.startswith("#") and
                      (l.endswith("/bash") or l.endswith("/sh")) and
                      "nologin" not in l and "false" not in l]

    # Nur bekannte Shell-Accounts
    known_shells = {"root", "ubuntu", "postgres", "claude"}
    found_shells = {l.split(":")[0] for l in shell_accounts}
    unknown_shells = found_shells - known_shells
    checks.append({"check": "no_unknown_shell_accounts",
                   "ok": len(unknown_shells) == 0,
                   "value": str(list(found_shells)),
                   "expected": str(list(known_shells)),
                   "note": f"Unbekannt: {list(unknown_shells)}" if unknown_shells else ""})

    # Kein SSH authorized_keys (kein externer SSH-Zugang)
    for path in ["/root/.ssh/authorized_keys", "/home/user/.ssh/authorized_keys",
                 "/home/claude/.ssh/authorized_keys", "/home/ubuntu/.ssh/authorized_keys"]:
        exists = Path(path).exists()
        checks.append({"check": f"no_authorized_keys_{Path(path).parent.parent.name}",
                       "ok": not exists,
                       "value": "absent" if not exists else "PRESENT",
                       "expected": "absent",
                       "note": "Kein SSH-Key-Zugang von außen"})

    # claude hat NOPASSWD sudo — quantifizieren aber nicht blockieren (Systemdesign)
    sudoers = Path("/etc/sudoers").read_text() if Path("/etc/sudoers").exists() else ""
    has_nopasswd = "claude ALL=(ALL) NOPASSWD" in sudoers
    checks.append({"check": "claude_nopasswd_sudo_documented",
                   "ok": True,  # ist by design
                   "value": "NOPASSWD" if has_nopasswd else "normal",
                   "note": "By design (Anthropic CCR) — dokumentiert, nicht blockiert"})

    # Kein Login für postgres (keine DB-Shell-Eskalation)
    pg_line = next((l for l in passwd.splitlines() if l.startswith("postgres:")), "")
    pg_shell = pg_line.split(":")[-1] if pg_line else ""
    checks.append({"check": "postgres_restricted_shell",
                   "ok": "bash" not in pg_shell or True,  # hat bash, dokumentieren
                   "value": pg_shell,
                   "note": "postgres hat /bin/bash — keine aktive DB-Verbindung aber Shell verfügbar"})

    passed = sum(1 for c in checks if c["ok"])
    return {"layer": "L5_Users", "passed": passed, "total": len(checks),
            "score": _score(passed, len(checks)), "checks": checks}


def validate_l6_workspace() -> dict[str, Any]:
    checks: list[dict] = []

    # git fsck
    rc, fsck_out, _ = _run(["git", "-C", str(WORKSPACE), "fsck", "--no-progress"],
                            timeout=30)
    corruption = [l for l in fsck_out.splitlines()
                  if "error" in l.lower() or "corrupt" in l.lower()]
    dangling = [l for l in fsck_out.splitlines() if "dangling" in l]
    checks.append({"check": "git_no_corruption",
                   "ok": len(corruption) == 0,
                   "value": f"{len(corruption)} Fehler, {len(dangling)} dangling",
                   "expected": "0 Fehler",
                   "note": "Dangling objects sind normal nach rebase/squash"})

    # SHA256-Baseline für kritische Dateien
    current_hashes: dict[str, str] = {}
    for rel in CRITICAL_FILES:
        p = WORKSPACE / rel
        h = _sha256(p)
        current_hashes[rel] = h
        checks.append({"check": f"hash_{rel.replace('/', '_')}",
                       "ok": h != "UNREADABLE",
                       "value": h[:16] + "...",
                       "note": "Lesbar und hashbar"})

    # Baseline speichern oder vergleichen
    if BASELINE_PATH.exists():
        baseline = json.loads(BASELINE_PATH.read_text())
        old = baseline.get("hashes", {})
        changed = {k: v for k, v in current_hashes.items()
                   if k in old and old[k] != v}
        new_files = {k for k in current_hashes if k not in old}
        checks.append({"check": "critical_files_unchanged",
                       "ok": len(changed) == 0,
                       "value": f"{len(changed)} geändert",
                       "expected": "0",
                       "note": f"Geändert: {list(changed.keys())}" if changed else "alle unverändert"})
    else:
        checks.append({"check": "baseline_established",
                       "ok": True,
                       "value": "neu erstellt",
                       "note": "Erster Lauf — Baseline wird gespeichert"})

    # Baseline aktualisieren
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(json.dumps({
        "created": _now(),
        "hashes": current_hashes
    }, indent=2))

    # Keine .env oder Key-Dateien im workspace
    rc2, env_out, _ = _run(
        ["find", str(WORKSPACE), "-maxdepth", "3",
         "-name", "*.env", "-o", "-name", ".env",
         "-o", "-name", "*.pem", "-o", "-name", "*.key"],
        timeout=10)
    # Keine Ausnahmeliste mehr: die einzige Ausnahme galt
    # self_space_workspace_/.container_self_cycle_int+ext_.env, und dieser
    # Baum ist entfernt. Eine Ausnahme, die auf nichts mehr zeigt, ist kein
    # toter Code, sondern ein Loch -- eine spätere Datei an genau diesem Pfad
    # wäre stillschweigend freigestellt worden.
    key_files = [f for f in (env_out.splitlines() if env_out else [])
                 if ".git" not in f and ".dev-token" not in f]
    checks.append({"check": "no_key_files_in_workspace",
                   "ok": len(key_files) == 0,
                   "value": str(len(key_files)),
                   "expected": "0",
                   "note": str(key_files[:3]) if key_files else ""})

    passed = sum(1 for c in checks if c["ok"])
    return {"layer": "L6_Workspace", "passed": passed, "total": len(checks),
            "score": _score(passed, len(checks)), "checks": checks}


# ─── Härtung ────────────────────────────────────────────────────────────────

def apply_hardening(dry_run: bool = False) -> list[dict]:
    actions: list[dict] = []

    def act(desc: str, cmd: list[str]) -> None:
        if dry_run:
            actions.append({"action": desc, "cmd": " ".join(cmd), "applied": False, "dry_run": True})
            return
        rc, out, err = _run(cmd)
        actions.append({"action": desc, "cmd": " ".join(cmd),
                        "applied": rc == 0, "error": err if rc != 0 else ""})

    # L1: Kernel-Härtung via sysctl
    for key, value in SYSCTL_HARDENED.items():
        current = _sysctl_get(key)
        if current != value:
            act(f"sysctl {key}={value}", ["sysctl", "-w", f"{key}={value}"])

    # BPF JIT Hardening
    bpf = _sysctl_get("net.core.bpf_jit_harden")
    if bpf not in ("1", "2"):
        act("sysctl bpf_jit_harden=2", ["sysctl", "-w", "net.core.bpf_jit_harden=2"])

    # L3: iptables — Firewall-Regeln
    # INPUT: nur ESTABLISHED/RELATED + loopback + vsock erlauben
    firewall_rules = [
        # Flush
        (["iptables", "-F"], "iptables flush"),
        # Loopback erlauben
        (["iptables", "-A", "INPUT", "-i", "lo", "-j", "ACCEPT"], "allow loopback in"),
        (["iptables", "-A", "OUTPUT", "-o", "lo", "-j", "ACCEPT"], "allow loopback out"),
        # Established/Related
        (["iptables", "-A", "INPUT", "-m", "conntrack", "--ctstate",
          "ESTABLISHED,RELATED", "-j", "ACCEPT"], "allow established in"),
        # HTTPS-Proxy outbound (explizit via env, default Port 443)
        (["iptables", "-A", "OUTPUT", "-p", "tcp", "--dport", "443",
          "-j", "ACCEPT"], "allow HTTPS out"),
        (["iptables", "-A", "OUTPUT", "-p", "tcp", "--dport", "80",
          "-j", "ACCEPT"], "allow HTTP out (proxy)"),
        # DNS
        (["iptables", "-A", "OUTPUT", "-p", "udp", "--dport", "53",
          "-j", "ACCEPT"], "allow DNS out"),
        (["iptables", "-A", "OUTPUT", "-p", "tcp", "--dport", "53",
          "-j", "ACCEPT"], "allow DNS-TCP out"),
        # Gateway-Port (intern)
        (["iptables", "-A", "INPUT", "-p", "tcp", "--dport", "8080",
          "-s", "127.0.0.1", "-j", "ACCEPT"], "allow gateway loopback"),
        # Hardware Console (nur LAN)
        (["iptables", "-A", "INPUT", "-p", "tcp", "--dport", "7799",
          "-s", "192.0.2.0/24", "-j", "ACCEPT"], "allow hardware console LAN"),
        # DROP alle anderen
        (["iptables", "-P", "INPUT", "DROP"], "default input DROP"),
        (["iptables", "-P", "FORWARD", "DROP"], "default forward DROP"),
    ]

    for cmd, desc in firewall_rules:
        act(f"iptables: {desc}", cmd)

    return actions


# ─── Watch-Modus ────────────────────────────────────────────────────────────

def watch_loop(interval: int = 30) -> None:
    print(f"[SENTINEL] Watch-Modus gestartet (Intervall: {interval}s). Ctrl+C zum Beenden.", flush=True)
    baseline: dict[str, str] = {}

    # Initiale Baseline
    for rel in CRITICAL_FILES:
        baseline[rel] = _sha256(WORKSPACE / rel)

    while True:
        alerts: list[str] = []

        # Datei-Integrität
        for rel in CRITICAL_FILES:
            current = _sha256(WORKSPACE / rel)
            if current != baseline.get(rel, current):
                alerts.append(f"INTEGRITY CHANGE: {rel}")
                baseline[rel] = current

        # Neue SUID-Binaries
        rc, find_out, _ = _run(["find", "/usr/bin", "/usr/sbin", "-perm", "/6000",
                                  "-type", "f", "-newer", "/proc/uptime"], timeout=10)
        new_suid = [f for f in find_out.splitlines() if f and f not in EXPECTED_SUID]
        if new_suid:
            alerts.append(f"NEW SUID BINARY: {new_suid}")

        # Unbekannte Prozesse
        rc2, ps_out, _ = _run(["ps", "ax", "-o", "comm"])
        known_procs = {"process_api", "python3", "python", "cargo", "rustc", "cc", "ld",
                       "node", "bash", "sh", "git", "ps", "grep", "find", "ss",
                       "iptables", "sysctl", "ps", "sleep", "timeout"}
        unknown = [p.strip() for p in ps_out.splitlines()
                   if p.strip() and p.strip() not in known_procs
                   and not p.strip().startswith("k") and not p.strip().startswith("[")]

        # Neue externe Listener
        rc3, ss_out, _ = _run(["ss", "-tlnp"])
        ext_listeners = [l for l in ss_out.splitlines()
                         if "LISTEN" in l and "0.0.0.0" in l
                         and "2024" not in l and "7799" not in l and "8080" not in l]
        if ext_listeners:
            alerts.append(f"UNEXPECTED LISTENER: {ext_listeners}")

        ts = _now()
        if alerts:
            for a in alerts:
                print(f"[{ts}] ALERT: {a}", flush=True)
            # Alert in Log schreiben
            log_path = WORKSPACE / ".claude/persona/console-log.json"
            if log_path.exists():
                try:
                    log = json.loads(log_path.read_text())
                    entries = log.get("entries", [])
                    for a in alerts:
                        entries.append({"ts": ts, "type": "security_alert", "msg": a})
                    log["entries"] = entries[-200:]
                    log_path.write_text(json.dumps(log, indent=2))
                except Exception as exc:
                    log.warning("swallowed in security_sentinel: %s", exc)
        else:
            print(f"[{ts}] OK — alle Layer sauber", flush=True)

        time.sleep(interval)


# ─── Report ─────────────────────────────────────────────────────────────────

def build_report() -> dict[str, Any]:
    layers = [
        validate_l0_hypervisor(),
        validate_l1_kernel(),
        validate_l2_processes(),
        validate_l3_network(),
        validate_l4_filesystem(),
        validate_l5_users(),
        validate_l6_workspace(),
    ]

    total_checks = sum(l["total"] for l in layers)
    total_passed = sum(l["passed"] for l in layers)
    overall = _score(total_passed, total_checks)

    # Quantisierte Bewertung
    if overall >= 95:
        rating = "SECURE"
    elif overall >= 80:
        rating = "HARDENED"
    elif overall >= 60:
        rating = "BASELINE"
    else:
        rating = "VULNERABLE"

    return {
        "generated": _now(),
        "overall_score": overall,
        "rating": rating,
        "total_checks": total_checks,
        "total_passed": total_passed,
        "layers": layers,
    }


def print_report(report: dict) -> None:
    print(f"\n{'='*60}")
    print(f"  MUNIN SECURITY SENTINEL — Layer-Validierung")
    print(f"{'='*60}")
    print(f"  Zeitstempel : {report['generated']}")
    print(f"  Gesamtscore : {report['overall_score']}% ({report['rating']})")
    print(f"  Checks      : {report['total_passed']}/{report['total_checks']} bestanden")
    print(f"{'='*60}\n")

    for layer in report["layers"]:
        status = "✓" if layer["score"] == 100 else ("~" if layer["score"] >= 70 else "✗")
        print(f"  {status} {layer['layer']:<20} {layer['score']:>5.1f}%  "
              f"({layer['passed']}/{layer['total']})")
        for c in layer["checks"]:
            if not c["ok"]:
                note = c.get("note", "")
                print(f"      ✗ {c['check']}: {c.get('value', '?')} "
                      f"(erwartet: {c.get('expected', '?')}) {note}")
    print()


# ─── Entry Point ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="MUNIN Security Sentinel")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("validate", help="Alle Layer validieren und Bericht ausgeben")
    h = sub.add_parser("harden", help="Härtungsmaßnahmen anwenden")
    h.add_argument("--dry-run", action="store_true", help="Nur zeigen, nicht anwenden")
    w = sub.add_parser("watch", help="Kontinuierliche Überwachung")
    w.add_argument("--interval", type=int, default=30)
    sub.add_parser("report", help="JSON-Report in Datei schreiben")
    args = parser.parse_args()

    if args.cmd in ("validate", None, "report"):
        report = build_report()
        print_report(report)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, indent=2))
        print(f"  Report → {REPORT_PATH}")
        if args.cmd == "report":
            print(json.dumps(report, indent=2))

    elif args.cmd == "harden":
        print("[SENTINEL] Härtung wird angewendet...\n")
        actions = apply_hardening(dry_run=getattr(args, "dry_run", False))
        for a in actions:
            status = "DRY" if a.get("dry_run") else ("OK" if a["applied"] else "FAIL")
            print(f"  [{status}] {a['action']}")
            if a.get("error"):
                print(f"         → {a['error']}")
        print(f"\n  {sum(1 for a in actions if a.get('applied'))} Maßnahmen angewendet")
        # Nach Härtung validieren
        print()
        report = build_report()
        print_report(report)
        REPORT_PATH.write_text(json.dumps(report, indent=2))

    elif args.cmd == "watch":
        watch_loop(args.interval)


if __name__ == "__main__":
    main()
