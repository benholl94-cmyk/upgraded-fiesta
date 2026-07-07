#!/usr/bin/env sh
# real_nosandbox_production_ai_platform_installer.sh
# Local no-key AI API platform installer. Uses only Python standard library.
# It installs a local HTTP service exposing /health, /v1/models, and /v1/chat/completions.
# It does not bypass browser/OS security. Run it manually in your shell.

set -eu

INSTALL_ROOT="${INSTALL_ROOT:-$HOME/.no_key_ai_platform}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-18791}"
START_SERVER="${START_SERVER:-0}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

APP_DIR="$INSTALL_ROOT/app"
BIN_DIR="$INSTALL_ROOT/bin"
DATA_DIR="$INSTALL_ROOT/data"
LOG_DIR="$INSTALL_ROOT/logs"
RUN_DIR="$INSTALL_ROOT/run"
CONFIG_DIR="$INSTALL_ROOT/config"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: python3 is required but not found." >&2
  exit 10
fi

mkdir -p "$APP_DIR" "$BIN_DIR" "$DATA_DIR" "$LOG_DIR" "$RUN_DIR" "$CONFIG_DIR"

INSTANCE_ID="$($PYTHON_BIN - <<'PY'
import uuid
print('nokey-ai-' + uuid.uuid4().hex)
PY
)"

cat > "$APP_DIR/no_key_ai_api_server.py" <<'PY'
#!/usr/bin/env python3
import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

SERVICE_NAME = "no-key-local-ai-api-platform"
MODEL_ID = "no-key-local-rule-v1"
INSTANCE_ID = os.environ.get("NO_KEY_AI_INSTANCE_ID", "nokey-ai-runtime")


def _json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _estimate_tokens(text):
    if not text:
        return 0
    return max(1, len(text.split()))


class Handler(BaseHTTPRequestHandler):
    server_version = "NoKeyAIPlatform/1.0"

    def _send(self, status, payload):
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except Exception as exc:
            raise ValueError(f"invalid_json: {exc}")

    def log_message(self, fmt, *args):
        ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        print(f"{ts} {self.address_string()} {fmt % args}", flush=True)

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/health":
            self._send(200, {
                "ok": True,
                "service": SERVICE_NAME,
                "mode": "no_key_local",
                "instance_id": INSTANCE_ID,
                "model": MODEL_ID,
                "time": int(time.time()),
            })
            return
        if path == "/v1/models":
            self._send(200, {
                "object": "list",
                "data": [{
                    "id": MODEL_ID,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "local-no-key",
                }]
            })
            return
        self._send(404, {"error": {"message": "not_found", "path": path}})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path != "/v1/chat/completions":
            self._send(404, {"error": {"message": "not_found", "path": path}})
            return
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send(400, {"error": {"message": str(exc)}})
            return

        messages = payload.get("messages") or []
        if not isinstance(messages, list):
            self._send(400, {"error": {"message": "messages must be a list"}})
            return
        user_texts = []
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    user_texts.append(content)
        prompt_text = "\n".join(user_texts).strip()
        if not prompt_text:
            prompt_text = "empty request"

        content = (
            "NO_KEY_LOCAL_PROVIDER: request accepted by the local no-key AI API platform. "
            "This is a deterministic local response, not a remote paid AI model. "
            f"Input summary: {prompt_text[:300]}"
        )
        completion_id = "chatcmpl-local-" + uuid.uuid4().hex
        prompt_tokens = _estimate_tokens(json.dumps(messages, ensure_ascii=False))
        completion_tokens = _estimate_tokens(content)
        self._send(200, {
            "id": completion_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": MODEL_ID,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            }
        })


def main():
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "18791"))
    print(f"{SERVICE_NAME} listening on http://{host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
PY
chmod +x "$APP_DIR/no_key_ai_api_server.py"

cat > "$BIN_DIR/no-key-ai-api" <<SH2
#!/usr/bin/env sh
export NO_KEY_AI_INSTANCE_ID="$INSTANCE_ID"
export HOST="\${HOST:-$HOST}"
export PORT="\${PORT:-$PORT}"
exec "$PYTHON_BIN" "$APP_DIR/no_key_ai_api_server.py" "\$@"
SH2
chmod +x "$BIN_DIR/no-key-ai-api"

cat > "$CONFIG_DIR/platform.json" <<JSON
{
  "service": "no-key-local-ai-api-platform",
  "instance_id": "$INSTANCE_ID",
  "install_root": "$INSTALL_ROOT",
  "host": "$HOST",
  "port": $PORT,
  "base_url": "http://$HOST:$PORT",
  "api_key_required": false,
  "external_ai_api_enabled": false,
  "model": "no-key-local-rule-v1"
}
JSON

cat > "$BIN_DIR/no-key-ai-health" <<SH3
#!/usr/bin/env sh
"$PYTHON_BIN" - <<'PY'
import json, os, urllib.request
host=os.environ.get('HOST','$HOST')
port=os.environ.get('PORT','$PORT')
url=f'http://{host}:{port}/health'
with urllib.request.urlopen(url, timeout=5) as r:
    print(r.read().decode())
PY
SH3
chmod +x "$BIN_DIR/no-key-ai-health"

cat > "$INSTALL_ROOT/INSTALL_REPORT.txt" <<REPORT
NO-KEY LOCAL AI API PLATFORM INSTALL REPORT
instance_id=$INSTANCE_ID
install_root=$INSTALL_ROOT
base_url=http://$HOST:$PORT
api_key_required=false
external_ai_api_enabled=false
server_launcher=$BIN_DIR/no-key-ai-api
health_check=$BIN_DIR/no-key-ai-health
REPORT

if [ "$START_SERVER" = "1" ]; then
  if [ -f "$RUN_DIR/server.pid" ] && kill -0 "$(cat "$RUN_DIR/server.pid")" 2>/dev/null; then
    echo "Server already running with PID $(cat "$RUN_DIR/server.pid")"
  else
    HOST="$HOST" PORT="$PORT" NO_KEY_AI_INSTANCE_ID="$INSTANCE_ID" nohup "$BIN_DIR/no-key-ai-api" > "$LOG_DIR/server.log" 2>&1 &
    echo $! > "$RUN_DIR/server.pid"
    sleep 1
  fi
fi

echo "INSTALL_OK=1"
echo "INSTALL_ROOT=$INSTALL_ROOT"
echo "BASE_URL=http://$HOST:$PORT"
echo "LAUNCHER=$BIN_DIR/no-key-ai-api"
echo "REPORT=$INSTALL_ROOT/INSTALL_REPORT.txt"
