FROM rust:1.85-slim-bookworm AS builder
WORKDIR /app
COPY . .
RUN cargo build --workspace --release

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
# Non-root user. uid 65532 = standard "nobody" in distroless images.
# hm-gateway braucht keine Privilegien -- bind:8080 ist unprivileged.
RUN groupadd -r hm && useradd -r -g hm -u 65532 hm \
    && mkdir -p /app /data/storage \
    && chown -R hm:hm /app /data/storage
WORKDIR /app
COPY --from=builder /app/target/release/hm-gateway /app/hm-gateway
COPY --from=builder /app/target/release/hm-tool-exec /app/target/release/hm-tool-exec
COPY config/ /app/config/
COPY plugins/ /app/plugins/
COPY scripts/ /app/scripts/
# agents/ traegt agents.brain -- das Gehirn hinter POST /chat. Ohne dieses
# Verzeichnis startet das Gateway normal und JEDER Chat-Aufruf antwortet
# "brain not startable: No such file or directory": eine Route, die im
# Checkout funktioniert und im Container tot ist. Dieselbe Fehlerklasse, die
# hier schon einmal die Plugin-Dispatch im Image gekostet hat.
COPY agents/ /app/agents/
# .claude/ ist Datenquelle, nicht Konfiguration: der Kernel schliesst aus
# dem Ledger (.claude/continuity/ledger.json), und die Regelschicht des
# Kerns liegt in config/kern-persona.json. Fehlt das Ledger, antwortet der
# Kern ohne Belege statt gar nicht -- deshalb kopiert, nicht vorausgesetzt.
COPY .claude/continuity/ /app/.claude/continuity/
COPY .claude/persona/ /app/.claude/persona/
# Der Chat-Pfad startet `python3 -m agents.brain` mit diesem Arbeitsverzeichnis.
ENV HM_BRAIN_REPO=/app
EXPOSE 8080
USER hm
CMD ["/app/hm-gateway"]
