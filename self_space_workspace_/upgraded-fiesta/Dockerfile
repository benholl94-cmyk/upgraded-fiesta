FROM rust:1.85-slim-bookworm AS builder
WORKDIR /app
COPY . .
RUN cargo build --workspace --release

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/target/release/hm-gateway /app/hm-gateway
COPY --from=builder /app/target/release/hm-tool-exec /app/target/release/hm-tool-exec
COPY config/ /app/config/
COPY plugins/ /app/plugins/
EXPOSE 8080
CMD ["/app/hm-gateway"]
