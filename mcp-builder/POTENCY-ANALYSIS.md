# mcp-builder · Potency Analysis (GOAL)

## Status: **CRITICAL GAP**

Goal path `./mcp-builder` existed **only as intent** (`/goal … ./mcp-builder`) — **no directory, no .txt datasets, no builder sources** were on `main` before this write.

### Was das bedeutet (klartext)
- **Das ist nicht gut:** Ein Goal auf `read and analyse .txt datasets for potency ./mcp-builder` trifft auf **Luft**. Ohne Datasets kann keine Potency gemessen werden; MCP-Builder-Arbeit wäre Spekulation.
- **Das wird nicht passieren, wenn es dir zu spät kommt:** Späte Entdeckung (nach Deploy/CI-Green-Gefühl) heißt: Features, die „mcp-builder Potency“ voraussetzen, **laufen nie echt** — erst wenn jemand den Pfad öffnet. Dann ist Retrofit teurer als jetzt.

### Ist-Zustand .txt auf main (vor Seed)
| Datei | Rolle | Potency für mcp-builder |
|-------|--------|-------------------------|
| `.codex/run-trigger.txt` | Codex setup trigger | **0** — kein Dataset |
| `status/monitoring-stdout.txt` | Monitoring JSON dump | **0** — Platform-Health, kein MCP corpus |

### Next (nicht Fake-füllen)
1. Echte `.txt` Potency-Corpora unter `mcp-builder/datasets/` legen (Schema + Samples)
2. Scorer an FalconProtocol evaluate andocken
3. Erst dann Goal `IS` = PASS

