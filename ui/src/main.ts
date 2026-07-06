import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import {
  checkEndpoint,
  dispatchWithRotation,
  listMemoryWithRotation,
  loadPlatformConfig,
  rememberMemoryWithRotation,
  searchMemoryWithRotation,
  type DispatchResult,
  type EndpointHealth,
  type MemoryRecord,
  type MemorySearchHit,
  type PlatformConfig
} from "./endpoint-rotation";

function parsePayload(input: string): unknown {
  if (input.trim().length === 0) return {};
  return JSON.parse(input);
}

function App(): React.ReactElement {
  const [config, setConfig] = useState<PlatformConfig | null>(null);
  const [health, setHealth] = useState<EndpointHealth[]>([]);
  const [taskType, setTaskType] = useState("analyze");
  const [objective, setObjective] = useState("Validate production readiness");
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

  useEffect(() => {
    loadPlatformConfig().then(setConfig).catch((err: unknown) => setError(err instanceof Error ? err.message : "config_load_failed"));
  }, []);

  useEffect(() => {
    if (!config) return;
    listMemoryWithRotation(config).then(setMemoryRecords).catch(() => undefined);
  }, [config]);

  const activeEndpoint = useMemo(() => config?.endpoints[0], [config]);

  async function runHealthCheck(): Promise<void> {
    if (!config) return;
    setBusy(true);
    setError(null);
    try {
      const checks = [] as EndpointHealth[];
      for (const endpoint of config.endpoints) {
        checks.push(await checkEndpoint(config, endpoint));
      }
      setHealth(checks);
    } catch (err) {
      setError(err instanceof Error ? err.message : "health_check_failed");
    } finally {
      setBusy(false);
    }
  }

  async function runDispatch(): Promise<void> {
    if (!config) return;
    setBusy(true);
    setError(null);
    try {
      const response = await dispatchWithRotation(config, {
        taskType,
        objective,
        payload: parsePayload(payload)
      });
      setResult(response);
      setHealth(response.attempts);
    } catch (err) {
      setError(err instanceof Error ? err.message : "dispatch_failed");
    } finally {
      setBusy(false);
    }
  }

  async function runRemember(): Promise<void> {
    if (!config || memoryText.trim().length === 0) return;
    setMemoryBusy(true);
    setMemoryError(null);
    try {
      await rememberMemoryWithRotation(config, memoryText);
      setMemoryText("");
      setMemoryRecords(await listMemoryWithRotation(config));
    } catch (err) {
      setMemoryError(err instanceof Error ? err.message : "memory_store_failed");
    } finally {
      setMemoryBusy(false);
    }
  }

  async function runMemorySearch(): Promise<void> {
    if (!config || memoryQuery.trim().length === 0) return;
    setMemoryBusy(true);
    setMemoryError(null);
    try {
      setMemoryResults(await searchMemoryWithRotation(config, memoryQuery, 5));
    } catch (err) {
      setMemoryError(err instanceof Error ? err.message : "memory_search_failed");
    } finally {
      setMemoryBusy(false);
    }
  }

  return React.createElement(
    "main",
    { className: "shell" },
    React.createElement("section", { className: "hero" },
      React.createElement("p", { className: "eyebrow" }, "Production AI Development Environment"),
      React.createElement("h1", null, config?.platformName ?? "Heavy Metal AI Control Plane"),
      React.createElement("p", { className: "heroText" }, "Fixed REST endpoint rotation with zero_staked failover, health checks, and task dispatch telemetry."),
      React.createElement("div", { className: "statusGrid" },
        React.createElement("div", null, React.createElement("span", null, "Active endpoint"), React.createElement("strong", null, activeEndpoint?.label ?? "loading")),
        React.createElement("div", null, React.createElement("span", null, "Timeout"), React.createElement("strong", null, `${config?.requestTimeoutMs ?? 0} ms`)),
        React.createElement("div", null, React.createElement("span", null, "Failover state"), React.createElement("strong", null, config?.zeroStakedStatus ?? "zero_staked"))
      )
    ),
    React.createElement("section", { className: "panel" },
      React.createElement("h2", null, "Task dispatch"),
      React.createElement("label", null, "Task type", React.createElement("select", { value: taskType, onChange: (event) => setTaskType(event.target.value) },
        ["analyze", "build", "test", "deploy", "generate", "document", "monitor"].map((item) => React.createElement("option", { key: item, value: item }, item))
      )),
      React.createElement("label", null, "Objective", React.createElement("textarea", { value: objective, onChange: (event) => setObjective(event.target.value), rows: 3 })),
      React.createElement("label", null, "JSON payload", React.createElement("textarea", { value: payload, onChange: (event) => setPayload(event.target.value), rows: 7, spellCheck: false })),
      React.createElement("div", { className: "actions" },
        React.createElement("button", { onClick: runHealthCheck, disabled: busy || !config }, "Health check"),
        React.createElement("button", { onClick: runDispatch, disabled: busy || !config || objective.trim().length === 0 }, "Dispatch with rotation")
      ),
      error ? React.createElement("pre", { className: "error" }, error) : null
    ),
    React.createElement("section", { className: "panel" },
      React.createElement("h2", null, "Endpoint telemetry"),
      React.createElement("div", { className: "endpointList" },
        health.length === 0 ? React.createElement("p", null, "No telemetry yet.") : health.map((item, index) => React.createElement("article", { key: `${item.endpoint.id}-${index}`, className: `endpoint ${item.state}` },
          React.createElement("strong", null, item.endpoint.label),
          React.createElement("span", null, item.state),
          React.createElement("small", null, `${item.reason} · ${item.latencyMs} ms`)
        ))
      )
    ),
    React.createElement("section", { className: "panel" },
      React.createElement("h2", null, "Last dispatch result"),
      React.createElement("pre", null, JSON.stringify(result ?? { status: "idle" }, null, 2))
    ),
    React.createElement("section", { className: "panel" },
      React.createElement("h2", null, "Memory"),
      React.createElement("label", null, "Remember something", React.createElement("textarea", {
        value: memoryText,
        onChange: (event) => setMemoryText(event.target.value),
        rows: 2,
        placeholder: "Text to store and make searchable"
      })),
      React.createElement("div", { className: "actions" },
        React.createElement("button", { onClick: runRemember, disabled: memoryBusy || !config || memoryText.trim().length === 0 }, "Remember")
      ),
      React.createElement("label", null, "Search memory", React.createElement("textarea", {
        value: memoryQuery,
        onChange: (event) => setMemoryQuery(event.target.value),
        rows: 1,
        placeholder: "What are you looking for?"
      })),
      React.createElement("div", { className: "actions" },
        React.createElement("button", { onClick: runMemorySearch, disabled: memoryBusy || !config || memoryQuery.trim().length === 0 }, "Search")
      ),
      memoryError ? React.createElement("pre", { className: "error" }, memoryError) : null,
      React.createElement("div", { className: "endpointList" },
        memoryResults.length > 0
          ? memoryResults.map((hit) => React.createElement("article", { key: hit.record.id, className: "endpoint online" },
              React.createElement("strong", null, hit.record.text),
              React.createElement("span", null, `score ${hit.score.toFixed(3)}`)
            ))
          : React.createElement("p", null, `${memoryRecords.length} memories stored. Search results appear here.`)
      )
    )
  );
}

const root = document.getElementById("root");
if (!root) throw new Error("root element missing");
createRoot(root).render(React.createElement(App));
