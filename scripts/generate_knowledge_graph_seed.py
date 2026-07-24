#!/usr/bin/env python3
"""Live-generate a knowledge-graph seed from the actual current repo state.

Not a static/hand-authored graph: every node and edge here is introspected
from real files at run time (Cargo.toml workspace members and their
[dependencies] tables, config/plugins.json, .claude/skills/*/SKILL.md
frontmatter, docs/*.md), so re-running this after the repo changes
regenerates a graph that matches reality instead of drifting from it.

Node types: crate, plugin, skill, doc, component (a coarse top-level area:
rust-workspace / ghm-core / iphone-dev-platform / skills / docs).

Edge relations: depends_on (crate -> crate, from real Cargo.toml deps),
registers (plugin -> crate, when the plugin's command references a known
crate binary by name), contains (component -> crate/plugin/skill/doc).

Stdlib only (tomllib, json, pathlib) -- no external dependencies, no
network calls. Output is a single JSON document: {"nodes": [...], "edges": [...]}.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


# Crates declared as intentional placeholders in CLAUDE.md / docs/architecture.md.
# These have grown beyond a naïve line-count threshold (due to structural scaffolding)
# but are still non-functional stubs: no real external calls, no persistence.
# hm-cron and hm-sessions are excluded — they are now live, integrated into hm-gateway.
_KNOWN_STUBS = {
    "hm-core", "hm-cli",
    "hm-tool-browser", "hm-tool-media", "hm-tool-web",
    "hm-channel-telegram", "hm-channel-discord", "hm-channel-slack", "hm-channel-whatsapp",
}


def _crate_is_stub(crate_name: str) -> bool:
    """Return True for crates that CLAUDE.md / architecture.md declare as intentional placeholders."""
    return crate_name in _KNOWN_STUBS


def load_crate_nodes() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cargo_toml = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))
    members: list[str] = cargo_toml["workspace"]["members"]

    name_to_member: dict[str, str] = {}
    nodes: list[dict[str, Any]] = []
    for member in members:
        crate_dir = ROOT / member
        crate_toml_path = crate_dir / "Cargo.toml"
        crate_toml = tomllib.loads(crate_toml_path.read_text(encoding="utf-8"))
        name = crate_toml["package"]["name"]
        name_to_member[name] = member
        nodes.append({
            "id": f"crate:{name}",
            "type": "crate",
            "label": name,
            "path": member,
            "status": "stub" if _crate_is_stub(name) else "real",
        })

    edges: list[dict[str, Any]] = []
    for member in members:
        crate_toml = tomllib.loads((ROOT / member / "Cargo.toml").read_text(encoding="utf-8"))
        this_name = crate_toml["package"]["name"]
        deps = crate_toml.get("dependencies", {})
        for dep_name, dep_spec in deps.items():
            if isinstance(dep_spec, dict) and "path" in dep_spec:
                if dep_name in name_to_member:
                    edges.append({
                        "source": f"crate:{this_name}",
                        "target": f"crate:{dep_name}",
                        "relation": "depends_on",
                    })
    return nodes, edges


def load_plugin_nodes(crate_names: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manifest_path = ROOT / "config" / "plugins.json"
    if not manifest_path.is_file():
        return [], []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for entry in manifest.get("plugins", []):
        task_type = entry["task_type"]
        command = entry["command"]
        node_id = f"plugin:{task_type}"
        nodes.append({
            "id": node_id,
            "type": "plugin",
            "label": task_type,
            "command": command,
        })
        # If the command's basename matches a known crate name, this plugin
        # is really that crate compiled to a binary -- record the real link.
        binary_name = Path(command[0]).name if command else ""
        if binary_name in crate_names:
            edges.append({
                "source": node_id,
                "target": f"crate:{binary_name}",
                "relation": "registers",
            })
    return nodes, edges


def load_skill_nodes() -> list[dict[str, Any]]:
    skills_dir = ROOT / ".claude" / "skills"
    if not skills_dir.is_dir():
        return []

    nodes: list[dict[str, Any]] = []
    frontmatter_pattern = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        match = frontmatter_pattern.match(text)
        name = skill_md.parent.name
        description = ""
        if match:
            for line in match.group(1).splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("description:"):
                    description = line.split(":", 1)[1].strip()
        nodes.append({
            "id": f"skill:{name}",
            "type": "skill",
            "label": name,
            "description": description,
            "path": str(skill_md.parent.relative_to(ROOT)),
        })
    return nodes


def load_doc_nodes() -> list[dict[str, Any]]:
    docs_dir = ROOT / "docs"
    if not docs_dir.is_dir():
        return []

    nodes: list[dict[str, Any]] = []
    heading_pattern = re.compile(r"^#\s+(.+)$", re.MULTILINE)
    for doc_path in sorted(docs_dir.glob("*.md")):
        text = doc_path.read_text(encoding="utf-8")
        match = heading_pattern.search(text)
        title = match.group(1).strip() if match else doc_path.stem
        nodes.append({
            "id": f"doc:{doc_path.stem}",
            "type": "doc",
            "label": title,
            "path": str(doc_path.relative_to(ROOT)),
        })
    return nodes


def build_component_edges(
    crate_nodes: list[dict[str, Any]],
    skill_nodes: list[dict[str, Any]],
    doc_nodes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    component_nodes = [
        {"id": "component:rust-workspace", "type": "component", "label": "Rust workspace (Fullstack Heavy Metal)"},
        {"id": "component:skills", "type": "component", "label": "Claude Code Skills"},
        {"id": "component:docs", "type": "component", "label": "Documentation"},
    ]
    edges: list[dict[str, Any]] = []
    for node in crate_nodes:
        edges.append({"source": "component:rust-workspace", "target": node["id"], "relation": "contains"})
    for node in skill_nodes:
        edges.append({"source": "component:skills", "target": node["id"], "relation": "contains"})
    for node in doc_nodes:
        edges.append({"source": "component:docs", "target": node["id"], "relation": "contains"})
    return component_nodes, edges


def build_graph() -> dict[str, Any]:
    crate_nodes, crate_edges = load_crate_nodes()
    crate_names = {n["label"] for n in crate_nodes}
    plugin_nodes, plugin_edges = load_plugin_nodes(crate_names)
    skill_nodes = load_skill_nodes()
    doc_nodes = load_doc_nodes()
    component_nodes, component_edges = build_component_edges(crate_nodes, skill_nodes, doc_nodes)

    nodes = crate_nodes + plugin_nodes + skill_nodes + doc_nodes + component_nodes
    edges = crate_edges + plugin_edges + component_edges

    return {
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None, help="Write JSON to this path instead of stdout")
    args = parser.parse_args()

    graph = build_graph()
    output = json.dumps(graph, indent=2, sort_keys=True)

    if args.out:
        Path(args.out).write_text(output + "\n", encoding="utf-8")
        print(f"wrote {graph['node_count']} nodes, {graph['edge_count']} edges to {args.out}", file=sys.stderr)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
