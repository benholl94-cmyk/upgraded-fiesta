#!/usr/bin/env python3
# ruff: noqa: E402
"""
hugin_oracle.py — MUNIN Provider Security Gate
===============================================
Externe AI-Provider (Gemini, OpenAI, etc.) als reine Daten-Query-Skills.
Kein Repo-Code, kein Secret verlässt das Gate ungeprüft.

Architektur:
  Master-Befehl → Sanitizer → Provider-Adapter → Audit-Log → Response

Sicherheitsregeln (unverhandelbar):
  - Kein Raw-Code aus dem Repo in Provider-Prompts
  - Kein Secret/Token im Prompt oder Response-Log
  - Jede Anfrage wird geloggt (wer, was, wann, welcher Provider)
  - Provider-Antworten werden auf Exfiltrations-Muster geprüft
  - Kein Provider kann mehr als sein zugewiesenes Skill-Scope abfragen

Verwendung:
  python3 scripts/hugin_oracle.py query --provider gemini --skill research "Frage hier"
  python3 scripts/hugin_oracle.py query --provider openai --skill code-review "Code-Snippet"
  python3 scripts/hugin_oracle.py list-skills
  python3 scripts/hugin_oracle.py audit-log [--tail 20]
  python3 scripts/hugin_oracle.py test-gate
"""
import abc
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import logging
log = logging.getLogger(__name__)

# ── Pfade ──────────────────────────────────────────────────────────────────
REPO_ROOT   = Path(__file__).parent.parent
AUDIT_LOG   = REPO_ROOT / "logs" / "oracle-audit.jsonl"
CONFIG_FILE = REPO_ROOT / ".claude" / "persona" / "oracle-config.json"

# ── ANSI ──────────────────────────────────────────────────────────────────
C = {"B": "\033[1m", "CY": "\033[96m", "GR": "\033[92m",
     "YL": "\033[93m", "RD": "\033[91m", "DM": "\033[2m", "R": "\033[0m"}


# ════════════════════════════════════════════════════════════════════════════
# SKILL-DEFINITIONEN — jeder Provider bekommt nur seinen Scope
# ════════════════════════════════════════════════════════════════════════════

SKILL_SCOPES = {
    "research": {
        "description": "Öffentliches Wissen abfragen — keine Repo-Daten",
        "allowed_content": ["questions", "concepts", "public_facts"],
        "forbidden_patterns": [r"token", r"api[_-]?key", r"secret", r"password"],
        "max_prompt_chars": 2000,
        "max_response_chars": 8000,
    },
    "code-review": {
        "description": "Isolierten Code-Snippet reviewen — kein Kontext aus Repo",
        "allowed_content": ["code_snippet", "algorithm_question"],
        "forbidden_patterns": [r"HM_OWNER_TOKEN", r"\.env", r"api[_-]?key",
                                r"secret", r"password", r"token\s*="],
        "max_prompt_chars": 4000,
        "max_response_chars": 12000,
    },
    "brainstorm": {
        "description": "Ideen generieren — rein konzeptuell, kein Repo-Inhalt",
        "allowed_content": ["concepts", "architecture_ideas", "feature_ideas"],
        "forbidden_patterns": [r"token", r"api[_-]?key", r"secret"],
        "max_prompt_chars": 1500,
        "max_response_chars": 6000,
    },
    "codex-patch": {
        "description": "Patch-Aufgabe an einen Coding-Agenten — sieht bewusst "
                       "Repo-Code, aber nur die vom Orchestrator einzeln "
                       "benannten Dateien (agents/orchestrator.py → build_task)",
        "allowed_content": ["code_snippet", "file_context", "task_instruction"],
        # Bewusst enger gefasst als bei 'code-review': Code enthaelt legitim die
        # Woerter token/key/secret (Variablennamen, Kommentare). Ein Blocken auf
        # das blosse Wort wuerde jede echte Aufgabe abweisen und den Scope damit
        # nutzlos machen. Geblockt werden deshalb *Wertzuweisungen* und echte
        # Key-Formen, nicht Vokabular.
        "forbidden_patterns": [
            r"HM_OWNER_TOKEN\s*=\s*\S+",
            r"(api[_-]?key|secret|password|token)\s*[=:]\s*['\"][^'\"]{12,}['\"]",
            r"sk-[A-Za-z0-9]{20,}",
            r"gh[pousr]_[A-Za-z0-9]{30,}",
            r"AIza[0-9A-Za-z_\-]{30,}",
            r"-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----",
        ],
        "max_prompt_chars": 24000,
        "max_response_chars": 32000,
    },
    "translate": {
        "description": "Text übersetzen — kein Code mit Secrets",
        "allowed_content": ["text", "documentation"],
        "forbidden_patterns": [r"token\s*=\s*\S+", r"key\s*=\s*\S{20,}"],
        "max_prompt_chars": 3000,
        "max_response_chars": 5000,
    },
}

# ════════════════════════════════════════════════════════════════════════════
# PROVIDER-ADAPTER — alle Adapter-Klassen sind identisch strukturiert
# ════════════════════════════════════════════════════════════════════════════

class ProviderAdapter(abc.ABC):
    """Basisklasse. Jeder Provider implementiert call()."""

    name: str = "base"
    env_key: str = ""

    def get_token(self) -> str:
        tok = os.environ.get(self.env_key, "")
        if not tok:
            raise RuntimeError(
                f"Provider '{self.name}' benötigt ${self.env_key} — nicht gesetzt.\n"
                f"Setze ihn lokal: export {self.env_key}=<dein-key>\n"
                f"NIEMALS in .env-Dateien committen."
            )
        return tok

    @abc.abstractmethod
    def call(self, prompt: str, skill: str) -> str: ...

    def _http_post(self, url: str, headers: dict, body: dict) -> dict:
        data = json.dumps(body).encode()
        req  = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:300]}")


class GeminiAdapter(ProviderAdapter):
    name    = "gemini"
    env_key = "HUGIN_GEMINI_KEY"

    def call(self, prompt: str, skill: str) -> str:
        tok = self.get_token()
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-1.5-flash:generateContent?key={tok}"
        )
        body = {"contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 2048, "temperature": 0.3}}
        resp = self._http_post(url, {"Content-Type": "application/json"}, body)
        try:
            return resp["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Gemini-Antwort unerwartet: {e} | {resp}")


class OpenAIAdapter(ProviderAdapter):
    name    = "openai"
    env_key = "HUGIN_OPENAI_KEY"

    def call(self, prompt: str, skill: str) -> str:
        tok  = self.get_token()
        url  = "https://api.openai.com/v1/chat/completions"
        body = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": f"Du bist ein Spezialist für: {skill}. "
                 "Antworte präzise. Gib niemals Credentials oder Tokens zurück."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 2048,
            "temperature": 0.3,
        }
        resp = self._http_post(
            url,
            {"Content-Type": "application/json", "Authorization": f"Bearer {tok}"},
            body,
        )
        return resp["choices"][0]["message"]["content"]


class MistralAdapter(ProviderAdapter):
    name    = "mistral"
    env_key = "HUGIN_MISTRAL_KEY"

    def call(self, prompt: str, skill: str) -> str:
        tok  = self.get_token()
        url  = "https://api.mistral.ai/v1/chat/completions"
        body = {
            "model": "mistral-small-latest",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2048,
        }
        resp = self._http_post(
            url,
            {"Content-Type": "application/json", "Authorization": f"Bearer {tok}"},
            body,
        )
        return resp["choices"][0]["message"]["content"]


class OllamaAdapter(ProviderAdapter):
    """Key-freier lokaler Provider via Ollama (http://localhost:11434).
    Kein API-Key erforderlich — vollständig lokal, Zero-Trust-konform.
    Modell: env HUGIN_LOCAL_MODEL (default: llama3.2 → mistral → gemma2).
    """
    name    = "local"
    env_key = ""

    OLLAMA_URL = "http://localhost:11434"

    def _detect_model(self) -> str:
        override = os.environ.get("HUGIN_LOCAL_MODEL", "")
        if override:
            return override
        try:
            req  = urllib.request.Request(f"{self.OLLAMA_URL}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as r:
                data   = json.loads(r.read())
                models = [m["name"].split(":")[0] for m in data.get("models", [])]
            for preferred in ("llama3.2", "llama3", "mistral", "gemma2", "qwen2.5"):
                if preferred in models:
                    return preferred
            if models:
                return models[0]
        except Exception as e:
            log.warning("swallowed in hugin_oracle: %s", exc)
            print(f"[hugin/local] Ollama model detection failed: {e}", file=sys.stderr)
        return "llama3.2"  # Fallback — überschreibe mit HUGIN_LOCAL_MODEL

    def is_available(self) -> bool:
        try:
            urllib.request.urlopen(
                urllib.request.Request(f"{self.OLLAMA_URL}/api/tags"),
                timeout=2,
            )
            return True
        except Exception as exc:
            log.warning("swallowed in hugin_oracle: %s", exc)
            return False

    def call(self, prompt: str, skill: str) -> str:
        if not self.is_available():
            raise RuntimeError(
                "Ollama nicht erreichbar (localhost:11434).\n"
                "Start: ollama serve\n"
                "Dann Modell laden: ollama pull llama3.2\n"
                "Oder setze HUGIN_LOCAL_MODEL=<modell-name>"
            )
        model = self._detect_model()
        body  = {
            "model": model,
            "prompt": f"[{skill}] {prompt}",
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 2048},
        }
        resp = self._http_post(
            f"{self.OLLAMA_URL}/api/generate",
            {"Content-Type": "application/json"},
            body,
        )
        return resp.get("response", str(resp))

    def get_token(self) -> str:
        return ""  # kein Token erforderlich


PROVIDERS: dict[str, ProviderAdapter] = {
    "gemini":  GeminiAdapter(),
    "openai":  OpenAIAdapter(),
    "mistral": MistralAdapter(),
    "local":   OllamaAdapter(),
}


# ════════════════════════════════════════════════════════════════════════════
# SECURITY GATE
# ════════════════════════════════════════════════════════════════════════════

class SecurityGate:
    """Einziger Durchgangspunkt für alle Provider-Aufrufe."""

    def sanitize_input(self, prompt: str, skill: str) -> str:
        """Prompt auf verbotene Muster prüfen und truncaten."""
        scope = SKILL_SCOPES.get(skill)
        if not scope:
            raise ValueError(f"Unbekannter Skill '{skill}'. Erlaubt: {list(SKILL_SCOPES)}")

        # Verbotene Muster im Prompt
        for pattern in scope["forbidden_patterns"]:
            if re.search(pattern, prompt, re.IGNORECASE):
                raise ValueError(
                    f"Sicherheitsgate: Prompt enthält verbotenes Muster '{pattern}'. "
                    f"Skill '{skill}' darf dies nicht empfangen."
                )

        # Länge begrenzen
        max_len = scope["max_prompt_chars"]
        if len(prompt) > max_len:
            prompt = prompt[:max_len] + "\n[TRUNCATED BY GATE]"

        return prompt

    def sanitize_output(self, response: str, skill: str) -> str:
        """Response auf Exfiltrations-Muster prüfen."""
        scope = SKILL_SCOPES[skill]

        # Provider darf keine Credentials zurückgeben
        for pattern in scope["forbidden_patterns"]:
            if re.search(pattern, response, re.IGNORECASE):
                # Nicht blocken, aber redaktieren und warnen
                response = re.sub(
                    pattern, "[REDACTED-BY-GATE]", response, flags=re.IGNORECASE
                )

        max_len = scope["max_response_chars"]
        if len(response) > max_len:
            response = response[:max_len] + "\n[RESPONSE TRUNCATED BY GATE]"

        return response

    def audit(self, provider: str, skill: str, prompt: str,
              response: str, error: str | None, duration_ms: int) -> None:
        """Jeden Aufruf unveränderlich loggen."""
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts":          datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "provider":    provider,
            "skill":       skill,
            "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest()[:16],
            "prompt_len":  len(prompt),
            "response_len": len(response) if response else 0,
            "error":       error,
            "duration_ms": duration_ms,
        }
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def query(self, provider_name: str, skill: str, prompt: str) -> str:
        provider = PROVIDERS.get(provider_name)
        if not provider:
            raise ValueError(
                f"Unbekannter Provider '{provider_name}'. "
                f"Verfügbar: {list(PROVIDERS)}"
            )

        # Input-Gate
        clean_prompt = self.sanitize_input(prompt, skill)

        t0    = time.monotonic()
        error = None
        response = ""
        try:
            response = provider.call(clean_prompt, skill)
            # Output-Gate
            response = self.sanitize_output(response, skill)
        except Exception as e:
            log.warning("swallowed in hugin_oracle: %s", exc)
            error    = str(e)
            response = ""
            raise
        finally:
            duration_ms = int((time.monotonic() - t0) * 1000)
            self.audit(provider_name, skill, clean_prompt, response, error, duration_ms)

        return response


GATE = SecurityGate()


# ════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════

def cmd_query(args) -> None:
    print(f"{C['DM']}Oracle-Gate → {args.provider} [{args.skill}]{C['R']}")
    try:
        result = GATE.query(args.provider, args.skill, args.prompt)
        print(f"\n{C['B']}── Antwort ({args.provider}){C['R']}")
        print(result)
        print(f"\n{C['GR']}✓{C['R']} Aufruf geloggt in {AUDIT_LOG.relative_to(REPO_ROOT)}")
    except ValueError as e:
        print(f"{C['RD']}Gate-Fehler:{C['R']} {e}", file=sys.stderr)
        sys.exit(2)
    except RuntimeError as e:
        print(f"{C['RD']}Provider-Fehler:{C['R']} {e}", file=sys.stderr)
        sys.exit(3)


def cmd_list_skills(_args) -> None:
    print(f"\n{C['B']}── Oracle-Skills{C['R']}")
    for name, scope in SKILL_SCOPES.items():
        print(f"  {C['CY']}{name}{C['R']}: {scope['description']}")
        print(f"    {C['DM']}Max Prompt: {scope['max_prompt_chars']} Zeichen{C['R']}")
    print()


def cmd_audit_log(args) -> None:
    if not AUDIT_LOG.exists():
        print("Kein Audit-Log vorhanden.")
        return
    lines = AUDIT_LOG.read_text(encoding="utf-8").strip().split("\n")
    tail  = getattr(args, "tail", 20) or 20
    for line in lines[-tail:]:
        try:
            e = json.loads(line)
            status = f"{C['RD']}ERR{C['R']}" if e.get("error") else f"{C['GR']}OK{C['R']}"
            print(f"  {e['ts']} [{status}] {e['provider']}/{e['skill']} "
                  f"{e['prompt_len']}→{e['response_len']}c {e['duration_ms']}ms")
        except json.JSONDecodeError:
            print(f"  [corrupt] {line[:80]}")


def cmd_test_gate(_args) -> None:
    """Gate-Selbsttest ohne echte API-Calls."""
    print(f"\n{C['B']}── Gate-Selbsttest{C['R']}")
    tests = [
        ("sauber",     "research",    "Was ist die Hauptstadt von Deutschland?", True),
        ("mit Token",  "research",    "Mein api_key ist abc123", False),
        ("langer Text","brainstorm",  "x" * 2001, True),  # wird truncated, nicht geblockt
        ("code safe",  "code-review", "def add(a, b): return a + b", True),
        ("code secret","code-review", "HM_OWNER_TOKEN=secret123", False),
    ]
    passed = 0
    for label, skill, prompt, should_pass in tests:
        try:
            result = GATE.sanitize_input(prompt, skill)
            if should_pass:
                print(f"  {C['GR']}✓{C['R']} {label}")
                passed += 1
            else:
                print(f"  {C['RD']}✗{C['R']} {label} — hätte geblockt werden sollen!")
        except ValueError as e:
            if not should_pass:
                print(f"  {C['GR']}✓{C['R']} {label} — korrekt geblockt: {e}")
                passed += 1
            else:
                print(f"  {C['RD']}✗{C['R']} {label} — fälschlicherweise geblockt: {e}")
    print(f"\n  {passed}/{len(tests)} Tests bestanden.")

    # Local-Provider Status
    local = PROVIDERS["local"]
    if local.is_available():
        model = local._detect_model()
        print(f"  {C['GR']}✓ local (Ollama){C['R']} erreichbar — Modell: {model}")
        print(f"    Nutzung: python3 scripts/hugin_oracle.py query --provider local --skill research \"Frage\"")
    else:
        print(f"  {C['YL']}○ local (Ollama){C['R']} nicht aktiv — Start: ollama serve && ollama pull llama3.2")
    print()
    if passed < len(tests):
        sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="MUNIN Oracle — Provider Security Gate",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")

    q = sub.add_parser("query", help="Provider abfragen")
    q.add_argument("--provider", required=True, choices=list(PROVIDERS),
                   help="Welcher Provider (gemini/openai/mistral)")
    q.add_argument("--skill", required=True, choices=list(SKILL_SCOPES),
                   help="Skill-Scope für diesen Call")
    q.add_argument("prompt", help="Die Frage/Aufgabe")

    sub.add_parser("list-skills", help="Verfügbare Skills anzeigen")

    al = sub.add_parser("audit-log", help="Letzten Audit-Einträge anzeigen")
    al.add_argument("--tail", type=int, default=20, help="Letzte N Einträge")

    sub.add_parser("test-gate", help="Gate-Selbsttest (kein API-Call)")

    return p


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(0)
    dispatch = {
        "query":       cmd_query,
        "list-skills": cmd_list_skills,
        "audit-log":   cmd_audit_log,
        "test-gate":   cmd_test_gate,
    }
    dispatch[args.cmd](args)


if __name__ == "__main__":
    main()
