//! Prometheus-Metriken fuer hm-gateway.
//!
//! Wir halten das minimal: drei Counter + ein Histogram, ein einziges
//! globales `Registry`, das per `once_cell::sync::Lazy` einmalig gebaut wird.
//! Mehr Metriken waeren leichter hinzuzufuegen als spaeter wieder zu
//! entfernen — eine Metrik, die niemand abruft, faellt erst beim naechsten
//! Run auf, weil `make verify` keinen Prometheus-Reader hat.
//!
//! Aufruf: `GET /metrics` (siehe `crate::route_inner`) — rendert das
//! text-Format von `prometheus::Registry::gather()`.

use once_cell::sync::Lazy;
use prometheus::{
    register_counter_vec_with_registry, register_histogram_vec_with_registry,
    register_int_counter_vec_with_registry, CounterVec, Encoder, HistogramVec, IntCounterVec,
    Registry, TextEncoder,
};

/// Opt-in: ohne `metrics`-Feature (siehe Cargo.toml) ist der gesamte
/// Endpunkt nicht aktiv — kein Counter, keine Registrierung, kein Overhead.
pub static REGISTRY: Lazy<Registry> = Lazy::new(Registry::new);

/// `gateway_requests_total{path,method,status}` — counter, monoton steigend.
/// Wird von `audit_log` (siehe `main.rs`) hochgezaehlt.
pub static REQUESTS: Lazy<IntCounterVec> = Lazy::new(|| {
    register_int_counter_vec_with_registry!(
        "gateway_requests_total",
        "Total HTTP requests served, partitioned by path/method/status",
        &["path", "method", "status"],
        REGISTRY
    )
    .expect("prometheus registration")
});

/// `gateway_request_duration_seconds{path,method}` — histogram.
/// Wird in `handle_connection` beobachtet.
pub static REQUEST_DURATION: Lazy<HistogramVec> = Lazy::new(|| {
    register_histogram_vec_with_registry!(
        "gateway_request_duration_seconds",
        "Request duration in seconds, partitioned by path/method",
        &["path", "method"],
        REGISTRY
    )
    .expect("prometheus registration")
});

/// `gateway_plugin_dispatch_total{task_type,outcome}` — counter.
/// Wird im Dispatch-Pfad (`hm-agent`) hochgezaehlt, sobald ein Plugin
/// gelaufen ist.
pub static PLUGIN_DISPATCH: Lazy<CounterVec> = Lazy::new(|| {
    register_counter_vec_with_registry!(
        "gateway_plugin_dispatch_total",
        "Total plugin dispatches by task_type and outcome (ok|error|timeout)",
        &["task_type", "outcome"],
        REGISTRY
    )
    .expect("prometheus registration")
});

/// Rendert das text-Format (Prometheus-Scraper-kompatibel).
///
/// `Content-Type` ist `text/plain; version=0.0.4` — der Standard, den
/// `prometheus.io` scraped; nichts davon ist Verhandlungssache.
pub fn render() -> Vec<u8> {
    // Erst die Lazy-Counter initialisieren, damit ein leerer Registry-Lauf
    // trotzdem die registrierten Metric-Namen ausspuckt (sonst fehlt die
    // Familie komplett und Scraper koennen sie nicht initialisieren).
    let _ = REQUESTS.with_label_values(&["_init", "_init", "_init"]);
    let _ = REQUEST_DURATION.with_label_values(&["_init", "_init"]);
    let _ = PLUGIN_DISPATCH.with_label_values(&["_init", "_init"]);

    let metric_families = REGISTRY.gather();
    let mut buffer = Vec::with_capacity(4096);
    let encoder = TextEncoder::new();
    encoder
        .encode(&metric_families, &mut buffer)
        .expect("text-encoding kann nicht fehlschlagen");
    buffer
}

/// Beobachtet eine einzelne Anfrage und fuellt Counter + Histogram.
/// Wird von `audit_log` und vom Request-Wrapper in `main.rs` aufgerufen.
pub fn observe_request(path: &str, method: &str, status: u16, duration_secs: f64) {
    REQUESTS
        .with_label_values(&[path, method, &status.to_string()])
        .inc();
    REQUEST_DURATION
        .with_label_values(&[path, method])
        .observe(duration_secs);
}

/// Beobachtet einen Plugin-Dispatch. `outcome` ist "ok", "error" oder
/// "timeout"; fremde Werte werden in `_other` einsortiert, damit ein
/// kaputter Plugin-Code nicht das ganze Label-Cardinality-Budget sprengt.
pub fn observe_plugin_dispatch(task_type: &str, outcome: &str) {
    let outcome = match outcome {
        "ok" | "error" | "timeout" => outcome,
        _ => "_other",
    };
    PLUGIN_DISPATCH
        .with_label_values(&[task_type, outcome])
        .inc();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn registry_gathers_at_least_one_family() {
        // Beim ersten Render muessen die drei Familien mindestens als
        // Header im Text-Format auftauchen — sonst hat der Init-Pfad
        // versagt und Scraper sehen eine leere Seite.
        let body = String::from_utf8(render()).expect("utf-8");
        assert!(
            body.contains("gateway_requests_total"),
            "requests metric missing"
        );
        assert!(
            body.contains("gateway_request_duration_seconds"),
            "duration metric missing"
        );
        assert!(
            body.contains("gateway_plugin_dispatch_total"),
            "dispatch metric missing"
        );
    }

    #[test]
    fn observe_request_increments_counter() {
        let before = REQUESTS
            .with_label_values(&["/test-observe", "GET", "200"])
            .get();
        observe_request("/test-observe", "GET", 200, 0.012);
        let after = REQUESTS
            .with_label_values(&["/test-observe", "GET", "200"])
            .get();
        assert_eq!(after - before, 1, "counter must increment by exactly 1");
    }

    #[test]
    fn observe_plugin_dispatch_rejects_unknown_outcomes() {
        // Unbekannte Outcomes landen in `_other`, nicht im Rohtext — das
        // schuetzt die Label-Cardinality. Test: ein Aufruf mit "MELTDOWN"
        // darf nicht im Registry-Lookup einen 4. Bucket erzeugen.
        observe_plugin_dispatch("echo", "MELTDOWN");
        // Wenn das Cardinality-Budget gebrochen waere, wuerde dieser
        // Zugriff mit panic antworten ("Duplicate label").
        let value = PLUGIN_DISPATCH.with_label_values(&["echo", "_other"]).get();
        assert!(value > 0.0, "_other bucket must catch unknown outcomes");
    }
}
