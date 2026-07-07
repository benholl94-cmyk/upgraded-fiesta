.PHONY: build test validate codex-setup codex-check run clean

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
