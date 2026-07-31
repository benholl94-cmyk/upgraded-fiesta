# Makefile — single entry point fuer die 100%-production-grade-Wache.
#
# `make verify` ist die einzige Wahrheit: jede Sub-Bedingung muss gruen sein,
# damit der Exit-Code 0 ist. Die Sub-Targets sind einzeln aufrufbar, wenn
# ein Sprint nur einen Teil braucht (z.B. `make clippy-check` waehrend
# Refactoring). Wer ein neues Pflicht-Gate hinzufuegt, haengt es hier an.
#
# Designregeln:
# - Kein Target darf stillschweigend passieren. Jeder Test-Befehl hat -v oder
#   wird durch ein pytest-Test abgedeckt, das den Befehl selbst aufruft.
# - `cargo` und `python3` duerfen fehlen — dann exit 127, nicht 0.
# - `clippy -D warnings` ist hart: jede Warnung ist ein Fehler.

.PHONY: build test validate codex-setup codex-check run clean \
        verify fmt-check clippy-check test-workspace test-python \
        clarity rollback routes

# ---------------------------------------------------------------------------
# Bestehende Targets (unverändert, weil Workflows sie aufrufen)
# ---------------------------------------------------------------------------

build:
	cargo build --workspace

test:
	cargo test --workspace

validate:
	python3 scripts/validate_repo.py

codex-setup:
	bash .codex/setup.sh

codex-check:
	bash scripts/codex_fullstack_check.sh

run:
	docker compose up

clean:
	cargo clean
	docker compose down -v

# ---------------------------------------------------------------------------
# A.1 — `make verify` ist der Single-Command-Production-Grade-Gate
# ---------------------------------------------------------------------------
#
# Reihenfolge ist wichtig: billigste Checks zuerst (fmt), damit der
# schnelle Fehler zuerst kommt; cargo-Tests laenger, pytest parallel.
#
# Jedes Sub-Target ist:
#   - eigenstaendig lauffaehig (`make clippy-check` allein ist ok)
#   - idempotent (zweimal hintereinander gibt das gleiche Ergebnis)
#   - ohne Netz (CI und Lokal nutzen dieselbe Definition)

verify: fmt-check clippy-check test-workspace test-python validate clarity rollback routes

# Formatierung — billigster Check, schlaegt am schnellsten an.
fmt-check:
	cargo fmt --all -- --check

# Lints als harter Fehler. `all-targets` zieht auch Tests + Beispiele.
# Wer eine bestehende Warnung nicht fixen kann, erhoeht NICHT die
# Toleranz, sondern dokumentiert in crates/.../FIXME.md warum.
clippy-check:
	cargo clippy --workspace --all-targets -- -D warnings

# Alle Rust-Tests im Workspace. `cargo test` laeuft sowohl Unit- als auch
# Integrationstests; das ist der langsamste Schritt.
test-workspace:
	cargo test --workspace

# Python-Wachen. -q unterdrueckt Per-Test-Output; Fehler werden voll
# gelistet. Tests, die Pre-Commit-Hooks (Cargo.lock, .env) brauchen,
# markieren das selbst mit pytest.skip wenn noetig.
test-python:
	python3 -m pytest tests/ -q

# Strukturvalidierung — prueft, dass alle Pflichtdateien da sind
# (CLAUDE.md, HANDOFF.md, AGENTS.md, alle Workflows, Configs, …).
validate:
	python3 scripts/validate_repo.py

# Readiness-Gate: bricht ab, wenn etwas den Betrieb wirklich blockiert
# (fehlender Owner-Token, nicht-beschreibbarer Storage-Pfad). Externe
# Hindernisse (Bot-Tokens, Cloud-Konto) zaehlen als EXTERN und blockieren
# NICHT — siehe hugin_clarity.py:336-346.
clarity:
	python3 scripts/hugin_clarity.py --start

# Auto-Rollback-Logik: ALLE 9 GitHub-Conclusios muessen ein definiertes
# Ergebnis liefern. Diese Tests sind die lebende Spezifikation der
# Allowlist (siehe scripts/auto_rollback_ctx.py).
rollback:
	python3 -m pytest tests/test_auto_rollback.py -v

# Statische Wachen ueber Workflow-YAML-Parsebarkeit und ueber die in
# Wave 1 versprochenen Lieferungen. Wenn eine dieser Wachen faellt,
# ist eine bewusste Aenderung rueckgaengig gemacht worden.
routes:
	python3 -m pytest tests/test_workflows_parse.py tests/test_wave1_smoke.py -v
