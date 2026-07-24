#!/usr/bin/env bash
# Ollama-Stack einrichten und testen
set -e

echo "=== Ollama-Setup für hm-gateway ==="

# 1. Ollama installieren (falls nicht vorhanden)
if ! command -v ollama &>/dev/null; then
  echo "[1] Ollama installieren..."
  curl -fsSL https://ollama.ai/install.sh | sh
else
  echo "[1] Ollama bereits installiert: $(ollama --version 2>/dev/null || echo 'ok')"
fi

# 2. Modell laden
MODEL="${HM_OLLAMA_MODEL:-llama3}"
echo "[2] Modell laden: $MODEL"
ollama pull "$MODEL"

# 3. Ollama-Server starten (Background)
echo "[3] Ollama-Server starten..."
ollama serve &>/tmp/ollama.log &
OLLAMA_PID=$!
sleep 2
echo "    PID: $OLLAMA_PID"

# 4. Smoke-Test
echo "[4] Smoke-Test ollama_plugin..."
echo '{"task_id":"test-001","task_type":"ollama-chat","payload":{"prompt":"Antworte nur mit: OLLAMA_OK"}}' \
  | python3 plugins/ollama_plugin.py

# 5. Claude-Tool-Test (ohne API-Key nur Gate-Test)
echo ""
echo "[5] Claude-Tool Gate-Test..."
python3 scripts/hugin_oracle.py test-gate

echo ""
echo "=== Setup abgeschlossen ==="
echo ""
echo "Gateway starten:"
echo "  export HM_OWNER_TOKEN=\$(cat .claude/persona/.dev-token 2>/dev/null || echo 'dev-token')"
echo "  export HM_OLLAMA_MODEL=$MODEL"
echo "  export HM_CLAUDE_TOOL=true          # Claude als Werkzeug aktivieren"
echo "  export ANTHROPIC_API_KEY=sk-...     # für Claude-Tool"
echo "  cargo run -p hm-gateway"
echo ""
echo "Task schicken:"
echo "  curl -X POST http://localhost:8080/tasks \\"
echo "    -H 'Authorization: Bearer \$HM_OWNER_TOKEN' \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"task_type\":\"ollama-chat\",\"payload\":{\"prompt\":\"Erkläre mir Rust Ownership\"}}'"
