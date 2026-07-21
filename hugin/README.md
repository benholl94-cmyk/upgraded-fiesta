# HUGIN × OpenClaw

**HUGIN** — mobile AI control surface (single HTML file, offline-capable)  
**OpenClaw** — external agent runtime with real tools (file, web, memory, cron)

```
   iPhone / Browser              Host / VPS
 ┌─────────────────┐  HTTPS/WS  ┌──────────────────────────┐
 │  hugin.html     │ ─────────▶ │  OpenClaw Gateway :18789  │
 │  (one file)     │  Bearer=   │  • Agent + Tools          │
 │  Router         │  Token     │    (File/Web/Memory)      │
 │  Reflex Kernel  │            │  • Cron / TaskFlow        │
 └─────────────────┘            │  • Model: Cerebras (free) │
          │                     └──────────────────────────┘
          ▼ Fallback chain
 OpenClaw → Groq → Google → Cerebras → OpenRouter → Mistral → Local(WebGPU) → Reflex
```

## Files

| File | Role |
|---|---|
| `hugin.html` | Mobile control surface + router + offline Reflex kernel. One file. |
| `hugin-openclaw-setup.sh` | Sets up OpenClaw as $0 work engine, prints connection details. |

## Setup (3 steps)

**1 · Install OpenClaw** (on a host/VPS that can stay running):
```sh
npm install -g openclaw        # requires Node.js
```

**2 · Configure work engine** (free Cerebras key from cloud.cerebras.ai):
```sh
CEREBRAS_API_KEY=csk-… sh hugin-openclaw-setup.sh
```

The script configures the model, tools, gateway token (idempotent — reuses token on re-run), and an example daily automation. Prints **Gateway URL + Token** at the end.

**3 · Connect HUGIN**: Open `hugin.html` → ⚙ → *Work Engine — OpenClaw* → enter URL + Token → "Connect OpenClaw".

For complex tasks, HUGIN's router now automatically chooses OpenClaw (full agent). Simple tasks stay local/fast. If the gateway is unreachable, the fallback chain covers all the way to the always-available Reflex kernel.

## Mobile access to a loopback gateway

Default bind is `loopback` (local only). From iPhone:
- **Recommended:** Tailscale/VPN — then use `http://<tailnet-ip>:18789` directly.
- **Fallback:** SSH tunnel on the host, then enter `http://127.0.0.1:18789` in HUGIN:
  ```sh
  ssh -N -L 18789:127.0.0.1:18789 user@host
  ```
  The SSH tunnel does not bypass gateway auth — the token is still required.

For LAN access (same network as iPhone):
```sh
HUGIN_BIND=lan sh hugin-openclaw-setup.sh
```

## Automations (via OpenClaw)

```sh
# Scheduled
openclaw cron add "0 8 * * *" "agent 'Summarize open tasks for today in 5 bullets.'"

# Event-driven
openclaw hooks add

# Multi-step
openclaw tasks flow list   # docs: /automation/taskflow

# Channels (Telegram/WhatsApp/Slack …)
openclaw channels add
```

## Security

- Keys in HUGIN are stored locally (FNV-1a sealed, Dual-Slot A/B) and sent only to the respective provider — no server, no middleman.
- Gateway token is stored in `~/.openclaw/hugin_gateway_token` (chmod 600), reused on re-run.
- Token as plaintext URL is only safe for loopback/private/VPN (OpenClaw enforces this).
- Cerebras free tier is for development/personal use; see provider for rate limits.

## Provider chain (HUGIN routing)

1. **OpenClaw** — full agent with tools (complex tasks)
2. **Groq** — fast inference
3. **Google Gemini** — multimodal
4. **Cerebras** — direct API
5. **OpenRouter** — aggregator
6. **Mistral** — EU-hosted
7. **Custom** — any OpenAI-compatible endpoint
8. **Local (WebGPU)** — on-device, requires Safari 26+ / iOS 26 or Chrome with WebGPU
9. **Reflex** — always available, offline, no key required (calculator, unit converter, date/time, encoding)
