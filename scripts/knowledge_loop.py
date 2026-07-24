#!/usr/bin/env python3
"""knowledge_loop — autonome Wissens-Ingestion aus konfigurierten Feeds.

Läuft als hm-plugins-Protocol-Subprocess (task_type: knowledge-loop) oder direkt via CLI.
Liest config/knowledge-feeds.json, fetched jede URL, speichert Text in hm-memory.
Trackt zuletzt geholte Timestamps in config/knowledge-loop-state.json.

Usage:
  python3 scripts/knowledge_loop.py           # CLI-Modus
  python3 scripts/knowledge_loop.py status    # zeigt letzten Lauf
  (als Plugin: stdin-Zeile JSON, stdout-Zeile JSON-Response)
"""

from __future__ import annotations

import html.parser
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FEEDS_FILE = REPO_ROOT / "config" / "knowledge-feeds.json"
STATE_FILE = REPO_ROOT / "config" / "knowledge-loop-state.json"
LOG_FILE = REPO_ROOT / "logs" / "knowledge-loop.json"

GATEWAY_URL = os.environ.get("HM_GATEWAY_URL", "http://localhost:8080")
OWNER_TOKEN = os.environ.get("HM_OWNER_TOKEN", "")

MAX_CHARS_DEFAULT = 4000
FETCH_TIMEOUT = 20
MIN_INTERVAL_SECS = 1800  # don't re-fetch same URL more than once per 30 min

_SKIP_TAGS = {"script", "style", "noscript", "nav", "footer", "header", "aside", "iframe"}


class _TextExtractor(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            s = data.strip()
            if s:
                self.parts.append(s)

    def result(self) -> str:
        return " ".join(self.parts)


def _fetch_text(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "hm-knowledge-loop/1.0"},
    )
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        ct = resp.headers.get("Content-Type", "").lower()
        raw = resp.read(512 * 1024).decode("utf-8", errors="replace")
    if "html" in ct:
        ex = _TextExtractor()
        ex.feed(raw)
        return ex.result()
    # JSON → pretty-print key values for readability
    if "json" in ct:
        try:
            return json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
    return raw


def _load_feeds() -> list[dict]:
    try:
        return json.loads(FEEDS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _store_memory(url: str, name: str, text: str, tags: list[str]) -> bool:
    if not OWNER_TOKEN:
        return False
    body = json.dumps({
        "content": f"[{name}]\n[source: {url}]\n\n{text}",
        "tags": ["knowledge-loop"] + tags,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{GATEWAY_URL}/memory",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OWNER_TOKEN}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except Exception:
        return False


def _append_log(run: dict) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log: list = []
    if LOG_FILE.exists():
        try:
            log = json.loads(LOG_FILE.read_text())
        except json.JSONDecodeError:
            log = []
    log.append(run)
    log = log[-100:]
    LOG_FILE.write_text(json.dumps(log, indent=2))


def run_loop() -> list[dict]:
    """Fetch all feeds, store in memory, return per-feed results."""
    feeds = _load_feeds()
    state = _load_state()
    now = time.time()
    results = []

    for feed in feeds:
        url = feed.get("url", "")
        name = feed.get("name", url)
        tags = feed.get("tags") or []
        max_chars = int(feed.get("max_chars", MAX_CHARS_DEFAULT))
        enabled = feed.get("enabled", True)

        if not url or not enabled:
            results.append({"name": name, "skipped": True, "reason": "disabled or no url"})
            continue

        last_fetch = state.get(url, 0)
        if now - last_fetch < MIN_INTERVAL_SECS:
            results.append({"name": name, "skipped": True,
                            "reason": f"fetched {int(now - last_fetch)}s ago"})
            continue

        print(f"  fetching: {name} ({url})", file=sys.stderr)
        try:
            text = _fetch_text(url)[:max_chars]
            stored = _store_memory(url, name, text, tags)
            state[url] = now
            results.append({
                "name": name, "url": url, "chars": len(text),
                "stored": stored, "ok": True,
            })
        except urllib.error.HTTPError as e:
            results.append({"name": name, "url": url, "ok": False, "detail": f"HTTP {e.code}"})
        except urllib.error.URLError as e:
            results.append({"name": name, "url": url, "ok": False, "detail": str(e.reason)})
        except Exception as e:
            results.append({"name": name, "url": url, "ok": False, "detail": str(e)})

    _save_state(state)
    run_record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "results": results}
    _append_log(run_record)
    return results


def status() -> None:
    if LOG_FILE.exists():
        log = json.loads(LOG_FILE.read_text())
        if log:
            last = log[-1]
            print(f"Last run: {last['ts']}")
            for r in last["results"]:
                icon = "✓" if r.get("ok") else ("⊘" if r.get("skipped") else "✗")
                detail = r.get("detail") or r.get("reason") or f"{r.get('chars', 0)} chars"
                print(f"  {icon} {r['name']}: {detail}")
            return
    print("No log found.")
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
        print(f"State has {len(state)} tracked URLs.")


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"

    if cmd == "status":
        status()
        return 0

    if cmd in ("run", "loop"):
        results = run_loop()
        ok_count = sum(1 for r in results if r.get("ok"))
        print(f"knowledge-loop: {ok_count}/{len(results)} feeds ingested")
        return 0

    # hm-plugins protocol
    if cmd == "plugin":
        _line = sys.stdin.readline()
        results = run_loop()
        ok_count = sum(1 for r in results if r.get("ok"))
        sys.stdout.write(json.dumps({
            "ok": True,
            "result": {"ingested": ok_count, "total": len(results), "results": results},
            "message": "knowledge-loop complete",
        }) + "\n")
        sys.stdout.flush()
        return 0

    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
