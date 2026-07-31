#!/usr/bin/env python3
"""channel_send_plugin.py -- Nachrichten wirklich zustellen.

## Warum es diese Datei gibt

Vier Rust-Crates (`hm-channel-telegram/-discord/-slack/-whatsapp`) sahen aus
wie funktionierende Kanaele und sind es nicht: ihre `*_api_post`-Funktionen
brechen unbedingt mit *"… requires HTTPS. Add rustls or native-tls to this
crate"* ab. Der Workspace baut seinen HTTP-Verkehr absichtlich von Hand ohne
externe Crates — und TLS von Hand zu bauen ist keine vernuenftige Option.

Gleichzeitig zeigten die vier Task-Typen `telegram-message`, `discord-message`,
`slack-message`, `whatsapp-message` in `config/plugins.json` auf
`echo_plugin.py`. Wer eine Telegram-Nachricht ueber das Gateway schickte, bekam
sie zurueckgespiegelt; gesendet wurde nichts. Vorhandener Code, an nichts
angeschlossen, und eine Doku, die "sendet wirklich" behauptete.

Dieses Plugin schliesst die Luecke auf dem Weg, den das Repo ohnehin fuer
Erweiterungen vorsieht: ein Subprozess am hm-plugins-Protokoll. TLS kommt aus
`urllib` der Standardbibliothek — keine neue Abhaengigkeit, kein neues
Rust-Crate, sofort funktionsfaehig.

Die Rust-Crates bleiben, was sie sind: Adapter fuer **eingehende** Nachrichten
und Typdefinitionen. Das ist nicht wertlos, aber es ist auch nicht "sendet".

## Disziplin (wie ueberall hier)

Fehlt ein Token, wird **laut** verweigert — nie still nichts getan und nie ein
Erfolg gemeldet, den es nicht gab. Ein Kanal, der schweigend nicht sendet, ist
schlimmer als einer, der gar nicht existiert: man verlaesst sich auf ihn.

    echo '{"task_type":"telegram-message","objective":"",
           "payload":{"chat_id":123,"text":"hallo"}}' \\
      | python3 plugins/channel_send_plugin.py
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

import json
import os
import sys
import urllib.error
import urllib.request

TIMEOUT_S = 10

# Ein Kanal: welcher Token, wohin, und wie der Body aussieht. Als Tabelle,
# damit ein neuer Kanal ein Eintrag ist und kein neuer Codepfad.
KANAELE = {
    "telegram-message": {
        "env": "HM_TELEGRAM_BOT_TOKEN",
        "url": lambda t: f"https://api.telegram.org/bot{t}/sendMessage",
        "body": lambda p: {"chat_id": p.get("chat_id"), "text": p.get("text", "")},
        "auth": None,
        "pflicht": ("chat_id", "text"),
        "woher": "https://t.me/BotFather",
    },
    "discord-message": {
        "env": "HM_DISCORD_BOT_TOKEN",
        "url": lambda t: None,        # kanalabhaengig, siehe ziel_url
        "ziel_url": lambda p: f"https://discord.com/api/v10/channels/{p['channel_id']}/messages",
        "body": lambda p: {"content": p.get("text", "")},
        "auth": lambda t: f"Bot {t}",
        "pflicht": ("channel_id", "text"),
        "woher": "https://discord.com/developers/applications",
    },
    "slack-message": {
        "env": "HM_SLACK_BOT_TOKEN",
        "url": lambda t: "https://slack.com/api/chat.postMessage",
        "body": lambda p: {"channel": p.get("channel"), "text": p.get("text", "")},
        "auth": lambda t: f"Bearer {t}",
        "pflicht": ("channel", "text"),
        "woher": "https://api.slack.com/apps",
    },
    "whatsapp-message": {
        "env": "HM_WHATSAPP_BOT_TOKEN",
        "ziel_url": lambda p: (f"https://graph.facebook.com/v21.0/"
                               f"{p['phone_number_id']}/messages"),
        "body": lambda p: {"messaging_product": "whatsapp", "to": p.get("to"),
                           "type": "text", "text": {"body": p.get("text", "")}},
        "auth": lambda t: f"Bearer {t}",
        "pflicht": ("phone_number_id", "to", "text"),
        "woher": "https://developers.facebook.com/apps",
    },
}


def antwort(ok: bool, result=None, message: str = "") -> str:
    return json.dumps({"ok": ok, "result": result if result is not None else {},
                       "message": message}, ensure_ascii=False)


def basis_url(kanal: dict, token: str, payload: dict) -> str:
    if "ziel_url" in kanal:
        return kanal["ziel_url"](payload)
    return kanal["url"](token)


def senden(task_type: str, payload: dict) -> tuple[bool, dict, str]:
    kanal = KANAELE.get(task_type)
    if kanal is None:
        return False, {}, f"Kein Kanal fuer task_type {task_type!r}"

    token = os.environ.get(kanal["env"], "").strip()
    if not token:
        # Laut, mit Bezugsquelle. Ein leerer Erfolg waere die gefaehrliche
        # Variante: der Aufrufer glaubt, die Nachricht sei unterwegs.
        return False, {}, (f"${kanal['env']} nicht gesetzt — {task_type} wird "
                           f"NICHT gesendet. Token holen: {kanal['woher']}. "
                           f"Niemals committen.")

    fehlt = [f for f in kanal["pflicht"] if not payload.get(f)]
    if fehlt:
        return False, {}, (f"payload unvollstaendig, fehlt: {', '.join(fehlt)} "
                           f"(noetig fuer {task_type})")

    if os.environ.get("HM_CHANNEL_DRY_RUN", "").lower() in ("1", "true", "yes"):
        # Zum Pruefen der Verdrahtung ohne echten Versand. Ausdruecklich als
        # Trockenlauf markiert, damit niemand ihn fuer Zustellung haelt.
        return True, {"dry_run": True, "url": basis_url(kanal, token, payload)}, \
            "Trockenlauf — nichts gesendet"

    url = basis_url(kanal, token, payload)
    daten = json.dumps(kanal["body"](payload)).encode("utf-8")
    kopf = {"Content-Type": "application/json"}
    if kanal.get("auth"):
        kopf["Authorization"] = kanal["auth"](token)

    req = urllib.request.Request(url, data=daten, headers=kopf, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            roh = r.read().decode("utf-8", "replace")
            koerper = json.loads(roh) if roh.strip().startswith("{") else {"raw": roh[:400]}
            # Slack antwortet mit HTTP 200 UND {"ok": false} -- wer nur den
            # Statuscode prueft, meldet jeden Fehler als Erfolg.
            if isinstance(koerper, dict) and koerper.get("ok") is False:
                return False, koerper, f"{task_type}: Anbieter meldet Fehler"
            return True, koerper, f"{task_type} gesendet"
    except urllib.error.HTTPError as e:
        return False, {"status": e.code}, \
            f"{task_type}: HTTP {e.code} — {e.read().decode('utf-8', 'replace')[:200]}"
    except Exception as e:
        return False, {}, f"{task_type}: {type(e).__name__}: {e}"


def main() -> int:
    zeile = sys.stdin.readline()
    try:
        req = json.loads(zeile)
    except json.JSONDecodeError as e:
        print(antwort(False, message=f"Anfrage ist kein JSON: {e}"), flush=True)
        return 0
    ok, result, msg = senden(req.get("task_type", ""), req.get("payload") or {})
    print(antwort(ok, result, msg), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
