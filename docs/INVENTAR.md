# Inventar

**Erzeugt von `scripts/hugin_inventar.py --index`. Nicht von Hand aendern.** Jede Zeile ist gerechnet: erreichbar heisst, dass eine andere Datei im Repo diesen Teil nennt; geprueft heisst, dass eine Datei unter `tests/` ihn nennt.

- Teile gesamt: **131**
- geschlossen: **113**
- offen: **18**
- extern: **0**

## Offen — mit dem Befehl, der es schliesst

| Teil | Grund | Befehl |
|---|---|---|
| `scripts/_migrate_to_log.py` | nichts im Repo nennt diesen Teil | `entweder anbinden (Test, Workflow oder Doku) oder entfernen: git rm scripts/_migrate_to_log.py` |
| `scripts/ashell_fullstack_up.py` | keine Testdatei nennt diesen Teil | `tests/ um einen Fall fuer ashell_fullstack_up.py ergaenzen` |
| `scripts/ashell_remote_channel.py` | nichts im Repo nennt diesen Teil | `entweder anbinden (Test, Workflow oder Doku) oder entfernen: git rm scripts/ashell_remote_channel.py` |
| `scripts/ashell_signal_client_setup.py` | keine Testdatei nennt diesen Teil | `tests/ um einen Fall fuer ashell_signal_client_setup.py ergaenzen` |
| `scripts/generate_crate_readmes.py` | keine Testdatei nennt diesen Teil | `tests/ um einen Fall fuer generate_crate_readmes.py ergaenzen` |
| `scripts/hardware_console.py` | keine Testdatei nennt diesen Teil | `tests/ um einen Fall fuer hardware_console.py ergaenzen` |
| `scripts/hugin_limits.py` | keine Testdatei nennt diesen Teil | `tests/ um einen Fall fuer hugin_limits.py ergaenzen` |
| `scripts/hugin_push.py` | keine Testdatei nennt diesen Teil | `tests/ um einen Fall fuer hugin_push.py ergaenzen` |
| `scripts/mobile_rust_check.py` | nichts im Repo nennt diesen Teil | `entweder anbinden (Test, Workflow oder Doku) oder entfernen: git rm scripts/mobile_rust_check.py` |
| `scripts/rotation-daemon.py` | keine Testdatei nennt diesen Teil | `tests/ um einen Fall fuer rotation-daemon.py ergaenzen` |
| `scripts/signal_cli_smoke_test.py` | keine Testdatei nennt diesen Teil | `tests/ um einen Fall fuer signal_cli_smoke_test.py ergaenzen` |
| `scripts/write_visibility_report.py` | keine Testdatei nennt diesen Teil | `tests/ um einen Fall fuer write_visibility_report.py ergaenzen` |
| `scripts/write_visible_status.py` | keine Testdatei nennt diesen Teil | `tests/ um einen Fall fuer write_visible_status.py ergaenzen` |
| `.github/workflows/build-ui.yml` | nichts im Repo nennt diesen Teil | `entweder anbinden (Test, Workflow oder Doku) oder entfernen: git rm .github/workflows/build-ui.yml` |
| `.github/workflows/codeql.yml` | nichts im Repo nennt diesen Teil | `entweder anbinden (Test, Workflow oder Doku) oder entfernen: git rm .github/workflows/codeql.yml` |
| `.github/workflows/platform-monitoring.yml` | nichts im Repo nennt diesen Teil | `entweder anbinden (Test, Workflow oder Doku) oder entfernen: git rm .github/workflows/platform-monitoring.yml` |
| `docs/hugin-companion-hud.md` | nichts im Repo nennt diesen Teil | `entweder anbinden (Test, Workflow oder Doku) oder entfernen: git rm docs/hugin-companion-hud.md` |
| `docs/multi-agent.md` | nichts im Repo nennt diesen Teil | `entweder anbinden (Test, Workflow oder Doku) oder entfernen: git rm docs/multi-agent.md` |

## doku — 14

| Teil | Zustand | geprueft | beschrieben |
|---|---|---|---|
| `docs/GENERATED_HEAVY_METAL_WORKSPACE_DEPLOY.md` | geschlossen | nein | nein |
| `docs/INVENTAR.md` | geschlossen | ja | ja |
| `docs/SIGNAL_CLI_GATEWAY_BOOTSTRAP.md` | geschlossen | nein | nein |
| `docs/architecture.md` | geschlossen | nein | ja |
| `docs/env-vars.md` | geschlossen | ja | nein |
| `docs/file-manifest.md` | geschlossen | nein | nein |
| `docs/fullstack-up.md` | geschlossen | nein | nein |
| `docs/hugin-companion-hud.md` | offen | nein | nein |
| `docs/migration.md` | geschlossen | nein | nein |
| `docs/multi-agent.md` | offen | nein | nein |
| `docs/production-api-contract.md` | geschlossen | ja | ja |
| `docs/self-made-github-app.md` | geschlossen | nein | nein |
| `docs/ui-control-plane-implementation.md` | geschlossen | nein | nein |
| `docs/xcloud-platform-plan.md` | geschlossen | nein | ja |

## konfig — 12

| Teil | Zustand | geprueft | beschrieben |
|---|---|---|---|
| `config/agents.json` | geschlossen | ja | ja |
| `config/budget.json` | geschlossen | ja | nein |
| `config/codeam.json` | geschlossen | nein | nein |
| `config/corpus.json` | geschlossen | ja | nein |
| `config/cron.json` | geschlossen | nein | ja |
| `config/heavy-metal.json` | geschlossen | nein | ja |
| `config/kern-persona.json` | geschlossen | nein | nein |
| `config/knowledge-feeds.json` | geschlossen | nein | ja |
| `config/llm-providers.json` | geschlossen | nein | nein |
| `config/model.json` | geschlossen | ja | ja |
| `config/plugins.json` | geschlossen | ja | ja |
| `config/router-skills.json` | geschlossen | nein | nein |

## krate — 20

| Teil | Zustand | geprueft | beschrieben |
|---|---|---|---|
| `crates/hm-agent` | geschlossen | ja | ja |
| `crates/hm-auth` | geschlossen | ja | ja |
| `crates/hm-channels/hm-channel-discord` | geschlossen | ja | ja |
| `crates/hm-channels/hm-channel-slack` | geschlossen | ja | ja |
| `crates/hm-channels/hm-channel-telegram` | geschlossen | ja | ja |
| `crates/hm-channels/hm-channel-whatsapp` | geschlossen | ja | ja |
| `crates/hm-cli` | geschlossen | ja | ja |
| `crates/hm-core` | geschlossen | ja | ja |
| `crates/hm-cron` | geschlossen | ja | ja |
| `crates/hm-gateway` | geschlossen | ja | ja |
| `crates/hm-memory` | geschlossen | ja | ja |
| `crates/hm-plugins` | geschlossen | ja | ja |
| `crates/hm-sdk` | geschlossen | ja | ja |
| `crates/hm-sessions` | geschlossen | ja | ja |
| `crates/hm-storage` | geschlossen | ja | ja |
| `crates/hm-tools/hm-tool-browser` | geschlossen | ja | ja |
| `crates/hm-tools/hm-tool-exec` | geschlossen | ja | ja |
| `crates/hm-tools/hm-tool-media` | geschlossen | ja | ja |
| `crates/hm-tools/hm-tool-web` | geschlossen | ja | ja |
| `crates/hm-vector` | geschlossen | ja | ja |

## plugin — 8

| Teil | Zustand | geprueft | beschrieben |
|---|---|---|---|
| `plugins/autonomy_pulse_plugin.py` | geschlossen | ja | ja |
| `plugins/channel_send_plugin.py` | geschlossen | ja | ja |
| `plugins/claude_tool_plugin.py` | geschlossen | ja | ja |
| `plugins/echo_plugin.py` | geschlossen | ja | ja |
| `plugins/fetch_url_plugin.py` | geschlossen | ja | nein |
| `plugins/llm_chat_plugin.py` | geschlossen | ja | ja |
| `plugins/ollama_plugin.py` | geschlossen | ja | ja |
| `plugins/router_plugin.py` | geschlossen | ja | nein |

## skill — 8

| Teil | Zustand | geprueft | beschrieben |
|---|---|---|---|
| `.claude/skills/dev-loop` | geschlossen | nein | nein |
| `.claude/skills/direct-write` | geschlossen | nein | nein |
| `.claude/skills/git-config` | geschlossen | nein | nein |
| `.claude/skills/munin` | geschlossen | ja | ja |
| `.claude/skills/munin-link` | geschlossen | ja | ja |
| `.claude/skills/pr-bot-triage` | geschlossen | ja | ja |
| `.claude/skills/repo-steward` | geschlossen | nein | ja |
| `.claude/skills/xcode-alternative` | geschlossen | ja | ja |

## skript — 50

| Teil | Zustand | geprueft | beschrieben |
|---|---|---|---|
| `scripts/_log.py` | geschlossen | ja | ja |
| `scripts/_migrate_to_log.py` | offen | nein | nein |
| `scripts/ashell_fullstack_up.py` | offen | nein | nein |
| `scripts/ashell_remote_channel.py` | offen | nein | nein |
| `scripts/ashell_signal_client_setup.py` | offen | nein | nein |
| `scripts/auto_rollback.py` | geschlossen | ja | ja |
| `scripts/auto_rollback_ctx.py` | geschlossen | ja | ja |
| `scripts/autonomy_core.py` | geschlossen | ja | ja |
| `scripts/build_github_app_url.py` | geschlossen | ja | ja |
| `scripts/build_manifest.py` | geschlossen | ja | nein |
| `scripts/codeam_cli.py` | geschlossen | ja | ja |
| `scripts/dump_env_vars.py` | geschlossen | ja | ja |
| `scripts/generate_crate_readmes.py` | offen | nein | nein |
| `scripts/generate_hugin_icons.py` | geschlossen | ja | ja |
| `scripts/generate_knowledge_graph_seed.py` | geschlossen | ja | ja |
| `scripts/hardware_console.py` | offen | nein | ja |
| `scripts/hm_gateway_watchdog.py` | geschlossen | ja | ja |
| `scripts/hugin_bruecke.py` | geschlossen | ja | ja |
| `scripts/hugin_clarity.py` | geschlossen | ja | ja |
| `scripts/hugin_corpus.py` | geschlossen | ja | nein |
| `scripts/hugin_growth.py` | geschlossen | ja | nein |
| `scripts/hugin_inventar.py` | geschlossen | ja | ja |
| `scripts/hugin_keyring.py` | geschlossen | ja | ja |
| `scripts/hugin_limits.py` | offen | nein | nein |
| `scripts/hugin_local_model.py` | geschlossen | ja | ja |
| `scripts/hugin_model.py` | geschlossen | ja | nein |
| `scripts/hugin_oracle.py` | geschlossen | ja | ja |
| `scripts/hugin_push.py` | offen | nein | ja |
| `scripts/hugin_reflect.py` | geschlossen | ja | nein |
| `scripts/hugin_relay.py` | geschlossen | ja | nein |
| `scripts/hugin_selfheal.py` | geschlossen | ja | nein |
| `scripts/hugin_tool.py` | geschlossen | ja | nein |
| `scripts/hugin_zyklus.py` | geschlossen | ja | ja |
| `scripts/install_hooks.py` | geschlossen | ja | ja |
| `scripts/knowledge_loop.py` | geschlossen | ja | ja |
| `scripts/llm_key_manager.py` | geschlossen | ja | ja |
| `scripts/mobile_rust_check.py` | offen | nein | nein |
| `scripts/monitor_platform.py` | geschlossen | ja | ja |
| `scripts/munin_bridge.py` | geschlossen | ja | ja |
| `scripts/munin_continuity.py` | geschlossen | ja | ja |
| `scripts/munin_session.py` | geschlossen | ja | nein |
| `scripts/munin_supervisor.py` | geschlossen | ja | ja |
| `scripts/release_notes.py` | geschlossen | ja | ja |
| `scripts/repo_tracker.py` | geschlossen | ja | ja |
| `scripts/rotation-daemon.py` | offen | nein | nein |
| `scripts/security_sentinel.py` | geschlossen | ja | ja |
| `scripts/signal_cli_smoke_test.py` | offen | nein | ja |
| `scripts/validate_repo.py` | geschlossen | ja | ja |
| `scripts/write_visibility_report.py` | offen | nein | nein |
| `scripts/write_visible_status.py` | offen | nein | nein |

## workflow — 19

| Teil | Zustand | geprueft | beschrieben |
|---|---|---|---|
| `.github/workflows/auto-rollback.yml` | geschlossen | ja | ja |
| `.github/workflows/branch-cleanup.yml` | geschlossen | nein | ja |
| `.github/workflows/build-ui.yml` | offen | nein | nein |
| `.github/workflows/ci.yml` | geschlossen | ja | ja |
| `.github/workflows/codeql.yml` | offen | nein | nein |
| `.github/workflows/codex-setup.yml` | geschlossen | nein | nein |
| `.github/workflows/full-build-deploy.yml` | geschlossen | ja | nein |
| `.github/workflows/hugin-kern.yml` | geschlossen | nein | nein |
| `.github/workflows/hugin-pages.yml` | geschlossen | nein | ja |
| `.github/workflows/mobile-remote-channel.yml` | geschlossen | nein | nein |
| `.github/workflows/munin-link-hourly.yml` | geschlossen | ja | ja |
| `.github/workflows/platform-monitoring.yml` | offen | nein | nein |
| `.github/workflows/release.yml` | geschlossen | ja | ja |
| `.github/workflows/rust-ci.yml` | geschlossen | nein | ja |
| `.github/workflows/secret-scan.yml` | geschlossen | nein | nein |
| `.github/workflows/selbsterhalt.yml` | geschlossen | nein | ja |
| `.github/workflows/visible-monitoring.yml` | geschlossen | nein | nein |
| `.github/workflows/visible-status.yml` | geschlossen | nein | nein |
| `.github/workflows/zyklus.yml` | geschlossen | ja | ja |

