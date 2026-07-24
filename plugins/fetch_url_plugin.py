#!/usr/bin/env python3
"""fetch-url plugin — fetches a URL, strips HTML to plain text, optionally stores in hm-memory.

Payload fields:
  url        (required) URL to fetch
  store      (bool, default false) POST extracted text to hm-memory
  max_chars  (int, default 8000) truncation limit
  tags       (list[str]) memory tags if storing
"""

from __future__ import annotations

import html.parser
import json
import os
import sys
import urllib.error
import urllib.request

MAX_CHARS_DEFAULT = 8000
GATEWAY_URL = os.environ.get("HM_GATEWAY_URL", "http://localhost:8080")
OWNER_TOKEN = os.environ.get("HM_OWNER_TOKEN", "")

_SKIP_TAGS = {"script", "style", "noscript", "nav", "footer", "header", "aside", "iframe"}


class _TextExtractor(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            stripped = data.strip()
            if stripped:
                self.parts.append(stripped)

    def result(self) -> str:
        return " ".join(self.parts)


def _fetch_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "hm-gateway-bot/1.0 (knowledge-ingestion)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_type = resp.headers.get("Content-Type", "")
        raw = resp.read(1_024 * 1_024).decode("utf-8", errors="replace")

    if "html" in content_type.lower():
        extractor = _TextExtractor()
        extractor.feed(raw)
        return extractor.result()

    # JSON or plain text — return as-is
    return raw


def _store_in_memory(url: str, text: str, tags: list[str]) -> bool:
    if not OWNER_TOKEN:
        return False
    body = json.dumps({
        "content": f"[source: {url}]\n\n{text}",
        "tags": ["fetch-url"] + tags,
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


def _respond(ok: bool, result: dict, message: str) -> None:
    sys.stdout.write(json.dumps({"ok": ok, "result": result, "message": message}) + "\n")
    sys.stdout.flush()


def main() -> int:
    request = json.loads(sys.stdin.readline())
    payload = request.get("payload") or {}
    url: str = payload.get("url") or ""
    store: bool = bool(payload.get("store", False))
    max_chars: int = int(payload.get("max_chars", MAX_CHARS_DEFAULT))
    tags: list[str] = payload.get("tags") or []

    if not url:
        _respond(False, {"reason": "missing url in payload"}, "fetch-url: no url given")
        return 0

    print(json.dumps({"disclosure": {"fetching_url": url, "store": store}}), file=sys.stderr)
    sys.stderr.flush()

    try:
        text = _fetch_text(url)[:max_chars]
    except urllib.error.HTTPError as e:
        _respond(False, {"http_status": e.code, "url": url}, f"HTTP {e.code} fetching {url}")
        return 0
    except urllib.error.URLError as e:
        _respond(False, {"reason": str(e.reason), "url": url}, f"URL error fetching {url}")
        return 0
    except Exception as e:
        _respond(False, {"reason": str(e), "url": url}, "fetch-url unexpected error")
        return 0

    stored = _store_in_memory(url, text, tags) if store else False

    _respond(
        True,
        {"url": url, "chars": len(text), "text": text[:500], "stored": stored},
        "fetch-url ok",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
