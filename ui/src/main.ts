import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import {
  checkEndpoint,
  dispatchWithRotation,
  getOwnerToken,
  listMemoryWithRotation,
  loadLiveStatus,
  loadPlatformConfig,
  rememberMemoryWithRotation,
  searchMemoryWithRotation,
  setOwnerToken,
  type DispatchResult,
  type EndpointHealth,
  type LiveStatus,
  type MemoryRecord,
  type MemorySearchHit,
  type PlatformConfig
} from "./endpoint-rotation";

const E = React.createElement;

function parsePayload(input: string): unknown {
  if (input.trim().length === 0) return {};
  return JSON.parse(input);
}

function App(): React.ReactElement {
  const [config, setConfig] = useState<PlatformConfig | null>(null);
  const [health, setHealth] = useState<EndpointHealth[]>([]);
  const [taskType, setTaskType] = useState("analyze");
  const [objective, setObjective] = useState("Produktionsbereitschaft validieren");
  const [payload, setPayload] = useState("{}");
  const [result, setResult] = useState<DispatchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [memoryText, setMemoryText] = useState("");
  const [memoryQuery, setMemoryQuery] = useState("");
  const [memoryRecords, setMemoryRecords] = useState<MemoryRecord[]>([]);
  const [memoryResults, setMemoryResults] = useState<MemorySearchHit[]>([]);
  const [memoryBusy, setMemoryBusy] = useState(false);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [ownerTokenInput, setOwnerTokenInput] = useState(() => getOwnerToken());
  const [tokenSaved, setTokenSaved] = useState(false);
  const [liveStatus, setLiveStatus] = useState<LiveStatus | null>(null);

  useEffect(() => {
    loadPlatformConfig()
      .then(setConfig)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "config_load_failed"));
  }, []);

  // Live-Poll: lädt platform-status.json alle N ms — Daemon-Output direkt im Hero
  useEffect(() => {
    if (!config) return;
    const interval = config.liveStatusIntervalMs ?? 5000;
    let active = true;
    const poll = async (): Promise<void> => {
      const s = await loadLiveStatus(config);
      if (active) setLiveStatus(s);
    };
    void poll();
    const timer = window.setInterval(() => void poll(), interval);
    return () => { active = false; window.clearInterval(timer); };
  }, [config]);

  useEffect(() => {
    if (!config) return;
    listMemoryWithRotation(config).then(setMemoryRecords).catch(() => undefined);
  }, [config]);

  const activeEndpoint = useMemo(() => config?.endpoints[0], [config]);

  async function runHealthCheck(): Promise<void> {
    if (!config) return;
    setBusy(true); setError(null);
    try {
      const checks: EndpointHealth[] = [];
      for (const ep of config.endpoints) checks.push(await checkEndpoint(config, ep));
      setHealth(checks);
    } catch (err) {
      setError(err instanceof Error ? err.message : "health_check_failed");
    } finally { setBusy(false); }
  }

  async function runDispatch(): Promise<void> {
    if (!config) return;
    setBusy(true); setError(null);
    try {
      const response = await dispatchWithRotation(config, { taskType, objective, payload: parsePayload(payload) });
      setResult(response);
      setHealth(response.attempts);
    } catch (err) {
      setError(err instanceof Error ? err.message : "dispatch_failed");
    } finally { setBusy(false); }
  }

  function saveOwnerToken(): void {
    setOwnerToken(ownerTokenInput);
    setTokenSaved(true);
    window.setTimeout(() => setTokenSaved(false), 2000);
    if (config) listMemoryWithRotation(config).then(setMemoryRecords).catch(() => undefined);
  }

  async function runRemember(): Promise<void> {
    if (!config || memoryText.trim().length === 0) return;
    setMemoryBusy(true); setMemoryError(null);
    try {
      await rememberMemoryWithRotation(config, memoryText);
      setMemoryText("");
      setMemoryRecords(await listMemoryWithRotation(config));
    } catch (err) {
      setMemoryError(err instanceof Error ? err.message : "memory_store_failed");
    } finally { setMemoryBusy(false); }
  }

  async function runMemorySearch(): Promise<void> {
    if (!config || memoryQuery.trim().length === 0) return;
    setMemoryBusy(true); setMemoryError(null);
    try {
      setMemoryResults(await searchMemoryWithRotation(config, memoryQuery, 5));
    } catch (err) {
      setMemoryError(err instanceof Error ? err.message : "memory_search_failed");
    } finally { setMemoryBusy(false); }
  }

  // Aktiver Knoten: aus Daemon-Status wenn verfügbar, sonst erste config-Endpoint
  const liveActiveLabel = liveStatus
    ? (liveStatus.endpoints.find(ep => ep.id === liveStatus.activeId)?.label ?? liveStatus.activeId ?? "—")
    : (activeEndpoint?.label ?? "—");

  return E("main", { className: "shell" },

    /* ── Hero mit Live-Status ── */
    E("section", { className: "hero" },
      E("div", { className: "wordmark" },
        E("span", { className: "wordmark-glyph" }, "🜁"),
        E("span", { className: "wordmark-text" }, "HUGIN")
      ),
      E("h1", null, config?.platformName ?? "Steuerfeld"),
      E("p", { className: "heroText" },
        "Endpoint-Rotation mit Echtzeit-Failover · Aufgaben-Dispatch · Semantischer Speicher"
      ),
      E("div", { className: "statusGrid" },
        E("div", { className: "statCard" },
          E("span", null, "Aktiver Knoten"),
          E("strong", null, liveActiveLabel)
        ),
        E("div", { className: "statCard" },
          E("span", null, liveStatus ? "Rotations-Zyklus" : "Timeout"),
          E("strong", null, liveStatus ? `#${liveStatus.cycleCount}` : `${config?.requestTimeoutMs ?? 0} ms`)
        ),
        E("div", { className: "statCard" },
          E("span", null, liveStatus ? "Daemon aktiv" : "Failover"),
          E("strong", null, liveStatus
            ? new Date(liveStatus.updatedAt).toLocaleTimeString("de-DE")
            : (config?.zeroStakedStatus ?? "zero_staked")
          )
        )
      ),
      /* Live-Endpunktliste vom Daemon — erscheint sobald rotation-daemon.py läuft */
      liveStatus
        ? E("div", { className: "endpointList", style: { marginTop: "1rem" } },
            ...liveStatus.endpoints.map(ep =>
              E("article", { key: ep.id, className: `endpoint ${ep.state}` },
                E("strong", null, ep.label),
                E("span", null, ep.state),
                E("small", null, `${ep.reason} · ${ep.latencyMs} ms`)
              )
            )
          )
        : E("p", { style: { fontSize: "0.75rem", color: "#5e82a0", marginTop: "0.75rem" } },
            "Daemon inaktiv — starte: python3 scripts/rotation-daemon.py"
          )
    ),

    /* ── Owner token ── */
    E("section", { className: "panel" },
      E("h2", null, "Zugriffstoken"),
      E("label", null, "Bearer-Token",
        E("textarea", {
          value: ownerTokenInput,
          onChange: (ev: React.ChangeEvent<HTMLTextAreaElement>) => setOwnerTokenInput(ev.target.value),
          rows: 1, spellCheck: false,
          placeholder: "HM_OWNER_TOKEN des Gateways einfügen",
          style: { fontFamily: "monospace" }, autoComplete: "off"
        })
      ),
      E("div", { className: "actions" },
        E("button", { className: "primary", onClick: saveOwnerToken },
          tokenSaved ? "✓ Gespeichert" : "Token speichern"
        )
      ),
      E("p", { style: { fontSize: "0.75rem", color: "#5e82a0", marginTop: "0.5rem" } },
        "Nur in diesem Browser (localStorage) — als Authorization-Header bei jeder Anfrage."
      )
    ),

    /* ── Task dispatch ── */
    E("section", { className: "panel" },
      E("h2", null, "Aufgaben-Dispatch"),
      E("label", null, "Aufgabentyp",
        E("select", { value: taskType, onChange: (ev: React.ChangeEvent<HTMLSelectElement>) => setTaskType(ev.target.value) },
          ["analyze","build","test","deploy","generate","document","monitor"].map(t =>
            E("option", { key: t, value: t }, t)
          )
        )
      ),
      E("label", null, "Ziel",
        E("textarea", { value: objective, onChange: (ev: React.ChangeEvent<HTMLTextAreaElement>) => setObjective(ev.target.value), rows: 2 })
      ),
      E("label", null, "JSON-Payload",
        E("textarea", { value: payload, onChange: (ev: React.ChangeEvent<HTMLTextAreaElement>) => setPayload(ev.target.value), rows: 5, spellCheck: false })
      ),
      E("div", { className: "actions" },
        E("button", { onClick: runHealthCheck, disabled: busy || !config }, "Gesundheitscheck"),
        E("button", { className: "primary", onClick: runDispatch, disabled: busy || !config || objective.trim().length === 0 },
          busy ? "…" : "Dispatch"
        )
      ),
      error ? E("pre", { className: "error" }, error) : null
    ),

    /* ── Endpoint telemetry ── */
    E("section", { className: "panel" },
      E("h2", null, "Endpunkt-Telemetrie"),
      E("div", { className: "endpointList" },
        health.length === 0
          ? E("p", { style: { color: "#5e82a0", fontSize: "0.85rem" } }, "Noch keine Telemetrie — Gesundheitscheck starten.")
          : health.map((h, i) =>
              E("article", { key: `${h.endpoint.id}-${i}`, className: `endpoint ${h.state}` },
                E("strong", null, h.endpoint.label),
                E("span", null, h.state),
                E("small", null, `${h.reason} · ${h.latencyMs} ms`)
              )
            )
      )
    ),

    /* ── Result ── */
    E("section", { className: "panel" },
      E("h2", null, "Letztes Ergebnis"),
      E("pre", null, JSON.stringify(result ?? { status: "idle" }, null, 2))
    ),

    /* ── Memory ── */
    E("section", { className: "panel" },
      E("h2", null, "Semantischer Speicher"),
      E("label", null, "Speichern",
        E("textarea", {
          value: memoryText,
          onChange: (ev: React.ChangeEvent<HTMLTextAreaElement>) => setMemoryText(ev.target.value),
          rows: 2, placeholder: "Text zum Speichern und Durchsuchen"
        })
      ),
      E("div", { className: "actions" },
        E("button", { className: "primary", onClick: runRemember, disabled: memoryBusy || !config || memoryText.trim().length === 0 }, "Speichern")
      ),
      E("label", null, "Suche",
        E("textarea", {
          value: memoryQuery,
          onChange: (ev: React.ChangeEvent<HTMLTextAreaElement>) => setMemoryQuery(ev.target.value),
          rows: 1, placeholder: "Wonach suchst du?"
        })
      ),
      E("div", { className: "actions" },
        E("button", { onClick: runMemorySearch, disabled: memoryBusy || !config || memoryQuery.trim().length === 0 }, "Suchen")
      ),
      memoryError ? E("pre", { className: "error" }, memoryError) : null,
      E("div", { className: "endpointList" },
        memoryResults.length > 0
          ? memoryResults.map(hit =>
              E("article", { key: hit.record.id, className: "endpoint online" },
                E("strong", null, hit.record.text),
                E("span", null, `score ${hit.score.toFixed(3)}`)
              )
            )
          : E("p", { style: { color: "#5e82a0", fontSize: "0.85rem" } },
              `${memoryRecords.length} Einträge gespeichert. Suchergebnisse erscheinen hier.`
            )
      )
    )
  );
}

const root = document.getElementById("root");
if (!root) throw new Error("root element fehlt");
createRoot(root).render(E(App));
