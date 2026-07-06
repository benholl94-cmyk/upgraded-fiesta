#!/usr/bin/env node
// Live verification for Phase 5 of docs/xcloud-platform-plan.md: proves the
// UI's real, shipped endpoint-rotation logic (ui/src/endpoint-rotation.ts,
// imported here unmodified -- not reimplemented or mocked) actually fails
// over from one real hm-gateway process to a second real hm-gateway process
// when the first is killed.
//
// Disclosed scope: both instances run on this same host (different ports,
// different HM_STORAGE_ROOT directories, independent processes) -- this is
// not a multi-region/multi-provider deployment (that's Phase 2, and requires
// real cloud accounts this environment doesn't have). What this *does* prove
// live: the rotation algorithm itself, unmodified, correctly detects a dead
// gateway and dispatches to a healthy one instead, using real HTTP requests
// and real process kills, not simulated responses.
//
// Usage: node scripts/verify_multi_instance_failover.mjs
// Requires: a debug build of hm-gateway at target/debug/hm-gateway
// (`cargo build -p hm-gateway`), run from the repo root.

import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

globalThis.window = globalThis;
class MemoryStorage {
  #store = new Map();
  getItem(key) {
    return this.#store.has(key) ? this.#store.get(key) : null;
  }
  setItem(key, value) {
    this.#store.set(key, value);
  }
  removeItem(key) {
    this.#store.delete(key);
  }
}
globalThis.localStorage = new MemoryStorage();

const { setOwnerToken, checkEndpoint, dispatchWithRotation } = await import(
  "../ui/src/endpoint-rotation.ts"
);

const REPO_ROOT = new URL("..", import.meta.url).pathname;
const OWNER_TOKEN = "verify-failover-owner-token";
const PORT_A = 18801;
const PORT_B = 18802;

function startGateway(port, storageRoot) {
  const child = spawn("./target/debug/hm-gateway", [], {
    cwd: REPO_ROOT,
    env: {
      ...process.env,
      HM_GATEWAY_BIND: `127.0.0.1:${port}`,
      HM_OWNER_TOKEN: OWNER_TOKEN,
      HM_STORAGE_ROOT: storageRoot,
      HM_MEMORY_KEY: "memory/index.json",
      HM_RATE_LIMIT_PER_MINUTE: "0",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  return child;
}

function waitForListening(child, label) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error(`${label} did not report listening within 5s`)),
      5000
    );
    child.stdout.on("data", (chunk) => {
      if (chunk.toString().includes("listening on")) {
        clearTimeout(timeout);
        resolve();
      }
    });
    child.once("exit", (code) => {
      clearTimeout(timeout);
      reject(new Error(`${label} exited early with code ${code}`));
    });
  });
}

function killAndWaitForExit(child) {
  return new Promise((resolve) => {
    child.once("exit", () => resolve());
    child.kill("SIGTERM");
  });
}

async function main() {
  setOwnerToken(OWNER_TOKEN);

  const storageA = mkdtempSync(join(tmpdir(), "hm-failover-a-"));
  const storageB = mkdtempSync(join(tmpdir(), "hm-failover-b-"));
  const gatewayA = startGateway(PORT_A, storageA);
  const gatewayB = startGateway(PORT_B, storageB);

  const results = { steps: [] };

  try {
    await Promise.all([
      waitForListening(gatewayA, "gateway-a"),
      waitForListening(gatewayB, "gateway-b"),
    ]);

    const config = {
      platformName: "verify-multi-instance-failover",
      requestTimeoutMs: 3000,
      maxAttemptsPerDispatch: 2,
      zeroStakedStatus: "zero_staked",
      endpoints: [
        {
          id: "gateway-a",
          label: "Gateway A",
          baseUrl: `http://127.0.0.1:${PORT_A}`,
          healthPath: "/health",
          taskPath: "/tasks",
          priority: 1,
        },
        {
          id: "gateway-b",
          label: "Gateway B",
          baseUrl: `http://127.0.0.1:${PORT_B}`,
          healthPath: "/health",
          taskPath: "/tasks",
          priority: 2,
        },
      ],
    };

    const [healthA1, healthB1] = await Promise.all([
      checkEndpoint(config, config.endpoints[0]),
      checkEndpoint(config, config.endpoints[1]),
    ]);
    results.steps.push({
      step: "both_instances_up",
      gatewayA: { state: healthA1.state, httpStatus: healthA1.httpStatus },
      gatewayB: { state: healthB1.state, httpStatus: healthB1.httpStatus },
    });
    if (healthA1.state !== "online" || healthB1.state !== "online") {
      throw new Error("both real gateways must be healthy before proving failover");
    }

    const dispatch1 = await dispatchWithRotation(config, {
      taskType: "echo",
      objective: "verify-failover-before-kill",
      payload: { note: "should land on gateway-a (priority 1)" },
    });
    results.steps.push({
      step: "dispatch_with_both_up",
      pickedEndpoint: dispatch1.endpoint.id,
      ok: dispatch1.ok,
      httpStatus: dispatch1.httpStatus,
    });
    if (dispatch1.endpoint.id !== "gateway-a" || !dispatch1.ok) {
      throw new Error("expected dispatch to prefer gateway-a while both are healthy");
    }

    await killAndWaitForExit(gatewayA);

    const dispatch2 = await dispatchWithRotation(config, {
      taskType: "echo",
      objective: "verify-failover-after-kill",
      payload: { note: "gateway-a is dead; must fail over to gateway-b" },
    });
    results.steps.push({
      step: "dispatch_after_killing_gateway_a",
      pickedEndpoint: dispatch2.endpoint.id,
      ok: dispatch2.ok,
      httpStatus: dispatch2.httpStatus,
      attempts: dispatch2.attempts.map((a) => ({ id: a.endpoint.id, state: a.state })),
    });
    if (dispatch2.endpoint.id !== "gateway-b" || !dispatch2.ok) {
      throw new Error(
        `real failover did not occur: expected gateway-b to serve the request, got ${JSON.stringify(dispatch2)}`
      );
    }

    results.verified = true;
    console.log(JSON.stringify(results, null, 2));
  } finally {
    await killAndWaitForExit(gatewayA).catch(() => {});
    await killAndWaitForExit(gatewayB).catch(() => {});
    rmSync(storageA, { recursive: true, force: true });
    rmSync(storageB, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error("FAILOVER VERIFICATION FAILED:", error);
  process.exit(1);
});
