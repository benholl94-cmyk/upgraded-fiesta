from __future__ import annotations

import json
import pathlib
import subprocess
import sys

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "generate_knowledge_graph_seed.py"


def _run() -> dict:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return json.loads(proc.stdout)


def test_graph_has_nodes_and_edges():
    graph = _run()
    assert graph["node_count"] == len(graph["nodes"])
    assert graph["edge_count"] == len(graph["edges"])
    assert graph["node_count"] > 0
    assert graph["edge_count"] > 0


def test_every_edge_endpoint_is_a_real_node_id():
    graph = _run()
    node_ids = {node["id"] for node in graph["nodes"]}
    for edge in graph["edges"]:
        assert edge["source"] in node_ids, f"dangling edge source: {edge}"
        assert edge["target"] in node_ids, f"dangling edge target: {edge}"


def test_node_ids_are_unique():
    graph = _run()
    ids = [node["id"] for node in graph["nodes"]]
    assert len(ids) == len(set(ids)), "duplicate node ids"


def test_hm_gateway_depends_on_matches_its_real_cargo_toml():
    graph = _run()
    deps = {
        edge["target"]
        for edge in graph["edges"]
        if edge["source"] == "crate:hm-gateway" and edge["relation"] == "depends_on"
    }
    assert deps == {
        "crate:hm-core",
        "crate:hm-storage",
        "crate:hm-plugins",
        "crate:hm-memory",
        "crate:hm-agent",
        "crate:hm-auth",
    }


def test_ops_tool_plugin_registers_hm_tool_exec():
    graph = _run()
    registers = [
        edge for edge in graph["edges"]
        if edge["source"] == "plugin:ops-tool" and edge["relation"] == "registers"
    ]
    assert registers == [{"source": "plugin:ops-tool", "target": "crate:hm-tool-exec", "relation": "registers"}]


def test_stub_crates_match_known_placeholders():
    graph = _run()
    stub_labels = {n["label"] for n in graph["nodes"] if n["type"] == "crate" and n["status"] == "stub"}
    # These are the crates established by direct source inspection elsewhere
    # in this repo's history (CLAUDE.md) as intentional 1-8 line placeholders.
    expected_stubs = {
        "hm-core", "hm-cli", "hm-cron", "hm-sessions",
        "hm-tool-browser", "hm-tool-media", "hm-tool-web",
        "hm-channel-telegram", "hm-channel-discord", "hm-channel-slack", "hm-channel-whatsapp",
    }
    assert stub_labels == expected_stubs


def test_hm_tool_exec_is_not_a_stub():
    graph = _run()
    node = next(n for n in graph["nodes"] if n["id"] == "crate:hm-tool-exec")
    assert node["status"] == "real"


def test_skills_are_discovered_with_descriptions():
    graph = _run()
    skill_ids = {n["id"] for n in graph["nodes"] if n["type"] == "skill"}
    assert "skill:xcode-alternative" in skill_ids
    assert "skill:pr-bot-triage" in skill_ids
    for node in graph["nodes"]:
        if node["type"] == "skill":
            assert node["description"], f"skill {node['id']} missing description"


def test_out_flag_writes_file(tmp_path: pathlib.Path) -> None:
    out_path = tmp_path / "seed.json"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--out", str(out_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.returncode == 0
    assert out_path.is_file()
    data = json.loads(out_path.read_text())
    assert data["node_count"] > 0
