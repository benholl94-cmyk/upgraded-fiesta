export type EndpointState = "unknown" | "online" | "offline" | "degraded" | "zero_staked";

export interface EndpointConfig {
  id: string;
  label: string;
  baseUrl: string;
  healthPath: string;
  taskPath: string;
  priority: number;
}

export interface PlatformConfig {
  platformName: string;
  requestTimeoutMs: number;
  maxAttemptsPerDispatch: number;
  zeroStakedStatus: string;
  endpoints: EndpointConfig[];
}

export interface EndpointHealth {
  endpoint: EndpointConfig;
  state: EndpointState;
  httpStatus?: number;
  latencyMs: number;
  reason: string;
  checkedAt: string;
}

export interface DispatchRequest {
  taskType: string;
  objective: string;
  payload: unknown;
}

export interface DispatchResult {
  endpoint: EndpointConfig;
  ok: boolean;
  httpStatus?: number;
  state: EndpointState;
  response: unknown;
  attempts: EndpointHealth[];
}

const defaultConfig: PlatformConfig = {
  platformName: "Heavy Metal AI Control Plane",
  requestTimeoutMs: 8000,
  maxAttemptsPerDispatch: 3,
  zeroStakedStatus: "zero_staked",
  endpoints: [
    { id: "primary", label: "Primary Gateway", baseUrl: "/api", healthPath: "/health", taskPath: "/tasks", priority: 1 },
    { id: "gateway-local", label: "Local Gateway", baseUrl: "http://127.0.0.1:8080", healthPath: "/health", taskPath: "/tasks", priority: 2 },
    { id: "gateway-fallback", label: "Fallback Gateway", baseUrl: "/gateway", healthPath: "/health", taskPath: "/tasks", priority: 3 }
  ]
};

export async function loadPlatformConfig(): Promise<PlatformConfig> {
  try {
    const response = await fetch("/platform-config.json", { cache: "no-store" });
    if (!response.ok) return defaultConfig;
    const config = (await response.json()) as PlatformConfig;
    if (!Array.isArray(config.endpoints) || config.endpoints.length === 0) return defaultConfig;
    return {
      ...defaultConfig,
      ...config,
      endpoints: [...config.endpoints].sort((a, b) => a.priority - b.priority)
    };
  } catch {
    return defaultConfig;
  }
}

function joinUrl(baseUrl: string, path: string): string {
  const base = baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl;
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${base}${suffix}`;
}

// A 2xx status alone doesn't prove a real gateway answered -- a static file
// server's SPA fallback (or a misconfigured reverse proxy) can return 200
// with an unrelated body for any unmatched path. Only treat the endpoint as
// "online" when the body is a recognizable status/state/health payload;
// anything else is "unknown", which callers must treat as not usable (same
// as offline), not silently trusted.
function detectState(value: unknown, zeroStakedStatus: string): EndpointState {
  if (!value || typeof value !== "object") return "unknown";
  const source = value as Record<string, unknown>;
  if (source.status === undefined && source.state === undefined && source.health === undefined) {
    return "unknown";
  }
  const raw = String(source.status ?? source.state ?? source.health ?? "online").toLowerCase();
  if (raw === zeroStakedStatus || raw === "zero-staked" || raw === "zero staked") return "zero_staked";
  if (raw === "degraded" || raw === "warning") return "degraded";
  if (raw === "offline" || raw === "down" || raw === "failed") return "offline";
  if (raw === "online" || raw === "ok" || raw === "up" || raw === "healthy") return "online";
  return "unknown";
}

const OWNER_TOKEN_STORAGE_KEY = "hm_owner_token";

// Reads the owner bearer token from localStorage, or "" if unset/unavailable.
export function getOwnerToken(): string {
  try {
    return window.localStorage.getItem(OWNER_TOKEN_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

// Persists the owner bearer token in localStorage (cleared if blank).
// Never sent anywhere except as the Authorization header on gateway requests.
export function setOwnerToken(token: string): void {
  try {
    const trimmed = token.trim();
    if (trimmed.length === 0) {
      window.localStorage.removeItem(OWNER_TOKEN_STORAGE_KEY);
    } else {
      window.localStorage.setItem(OWNER_TOKEN_STORAGE_KEY, trimmed);
    }
  } catch {
    // localStorage unavailable (private browsing, disabled storage, etc.) -- ignore.
  }
}

async function fetchJsonWithTimeout(url: string, init: RequestInit, timeoutMs: number): Promise<{ status: number; body: unknown }> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  const headers = new Headers(init.headers);
  const token = getOwnerToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  try {
    const response = await fetch(url, { ...init, headers, signal: controller.signal });
    const text = await response.text();
    let body: unknown = null;
    if (text.trim().length > 0) {
      try {
        body = JSON.parse(text);
      } catch {
        body = { raw: text };
      }
    }
    return { status: response.status, body };
  } finally {
    window.clearTimeout(timeout);
  }
}

export async function checkEndpoint(config: PlatformConfig, endpoint: EndpointConfig): Promise<EndpointHealth> {
  const started = performance.now();
  const checkedAt = new Date().toISOString();
  try {
    const result = await fetchJsonWithTimeout(joinUrl(endpoint.baseUrl, endpoint.healthPath), { method: "GET" }, config.requestTimeoutMs);
    const latencyMs = Math.round(performance.now() - started);
    if (result.status < 200 || result.status >= 300) {
      return { endpoint, state: "offline", httpStatus: result.status, latencyMs, reason: "non_2xx_health_response", checkedAt };
    }
    const state = detectState(result.body, config.zeroStakedStatus);
    return { endpoint, state, httpStatus: result.status, latencyMs, reason: state === "online" ? "healthy" : "rotation_required", checkedAt };
  } catch (error) {
    return { endpoint, state: "offline", latencyMs: Math.round(performance.now() - started), reason: error instanceof Error ? error.name : "request_failed", checkedAt };
  }
}

export interface MemoryRecord {
  id: string;
  text: string;
  created_at_unix: number;
}

export interface MemorySearchHit {
  record: MemoryRecord;
  score: number;
}

export async function rememberMemory(config: PlatformConfig, endpoint: EndpointConfig, text: string): Promise<MemoryRecord> {
  const result = await fetchJsonWithTimeout(
    joinUrl(endpoint.baseUrl, "/memory"),
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) },
    config.requestTimeoutMs
  );
  const body = (result.body ?? {}) as { record?: MemoryRecord; reason?: string };
  if (result.status < 200 || result.status >= 300 || !body.record) {
    throw new Error(body.reason ?? `memory_store_failed_${result.status}`);
  }
  return body.record;
}

export async function searchMemory(config: PlatformConfig, endpoint: EndpointConfig, query: string, topK = 5): Promise<MemorySearchHit[]> {
  const result = await fetchJsonWithTimeout(
    joinUrl(endpoint.baseUrl, "/memory/search"),
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query, topK }) },
    config.requestTimeoutMs
  );
  const body = (result.body ?? {}) as { results?: MemorySearchHit[]; reason?: string };
  if (result.status < 200 || result.status >= 300) {
    throw new Error(body.reason ?? `memory_search_failed_${result.status}`);
  }
  return body.results ?? [];
}

export async function listMemory(config: PlatformConfig, endpoint: EndpointConfig): Promise<MemoryRecord[]> {
  const result = await fetchJsonWithTimeout(joinUrl(endpoint.baseUrl, "/memory"), { method: "GET" }, config.requestTimeoutMs);
  const body = (result.body ?? {}) as { records?: MemoryRecord[]; reason?: string };
  if (result.status < 200 || result.status >= 300) {
    throw new Error(body.reason ?? `memory_list_failed_${result.status}`);
  }
  return body.records ?? [];
}

async function withEndpointRotation<T>(config: PlatformConfig, fn: (endpoint: EndpointConfig) => Promise<T>): Promise<T> {
  const endpoints = [...config.endpoints].sort((a, b) => a.priority - b.priority);
  let lastError: unknown = new Error("no_healthy_endpoint_available");
  for (const endpoint of endpoints) {
    const health = await checkEndpoint(config, endpoint);
    if (health.state !== "online") {
      lastError = new Error(health.reason);
      continue;
    }
    try {
      return await fn(endpoint);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError instanceof Error ? lastError : new Error("no_healthy_endpoint_available");
}

export function rememberMemoryWithRotation(config: PlatformConfig, text: string): Promise<MemoryRecord> {
  return withEndpointRotation(config, (endpoint) => rememberMemory(config, endpoint, text));
}

export function searchMemoryWithRotation(config: PlatformConfig, query: string, topK = 5): Promise<MemorySearchHit[]> {
  return withEndpointRotation(config, (endpoint) => searchMemory(config, endpoint, query, topK));
}

export function listMemoryWithRotation(config: PlatformConfig): Promise<MemoryRecord[]> {
  return withEndpointRotation(config, (endpoint) => listMemory(config, endpoint));
}

export async function dispatchWithRotation(config: PlatformConfig, request: DispatchRequest): Promise<DispatchResult> {
  const endpoints = [...config.endpoints].sort((a, b) => a.priority - b.priority);
  const attempts: EndpointHealth[] = [];
  const maxAttempts = Math.min(config.maxAttemptsPerDispatch, endpoints.length);

  for (const endpoint of endpoints.slice(0, maxAttempts)) {
    const health = await checkEndpoint(config, endpoint);
    attempts.push(health);
    if (health.state !== "online") continue;

    const result = await fetchJsonWithTimeout(
      joinUrl(endpoint.baseUrl, endpoint.taskPath),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...request, submittedAt: new Date().toISOString() })
      },
      config.requestTimeoutMs
    );
    const state = detectState(result.body, config.zeroStakedStatus);
    if (result.status >= 200 && result.status < 300 && state === "online") {
      return { endpoint, ok: true, httpStatus: result.status, state, response: result.body, attempts };
    }
    attempts.push({ endpoint, state, httpStatus: result.status, latencyMs: 0, reason: "dispatch_response_rotation_required", checkedAt: new Date().toISOString() });
  }

  return { endpoint: endpoints[0], ok: false, state: "offline", response: { error: "no_healthy_endpoint_available" }, attempts };
}
