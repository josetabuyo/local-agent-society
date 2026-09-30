"""`.las-agent.json`'s `sessions` section (cli/agent_config.py, docs/adr/0005):
where a plain send lands among an agent's connected sessions, the cc, and
one descriptor per runtime — defaults filled in, patches merged one level
deep."""
import json

from cli.agent_config import (DEFAULT_RUNTIMES, default_sessions_config, merge_config_patch, read_agent_config, runtime_descriptor,
                              sessions_config, write_agent_config)


def test_defaults_target_the_last_used_session_without_cc_and_describe_the_three_runtimes():
    cfg = default_sessions_config()
    assert cfg["target"] == "default" and cfg["cc_default"] is False
    assert set(cfg["runtimes"]) == {"claude", "codex", "shell"}
    assert cfg["runtimes"]["shell"]["intelligent"] is False and cfg["runtimes"]["shell"]["accepts"] == ["command"]
    assert cfg["runtimes"]["claude"]["intelligent"] is True and "message" in cfg["runtimes"]["claude"]["accepts"]
    cfg["runtimes"]["shell"]["scope"] = "mutated"
    assert DEFAULT_RUNTIMES["shell"]["scope"] != "mutated", "each call hands out its own copy"


def test_sessions_config_fills_defaults_and_merges_a_partial_runtime_descriptor():
    declared = {"sessions": {"target": "shell", "runtimes": {"shell": {"scope": "runs the deploy script only"}, "ollama": {"intelligent": True}}}}
    cfg = sessions_config(declared)
    assert cfg["target"] == "shell" and cfg["cc_default"] is False
    assert cfg["runtimes"]["shell"] == {"intelligent": False, "accepts": ["command"], "scope": "runs the deploy script only"}
    assert cfg["runtimes"]["ollama"] == {"intelligent": True}
    assert cfg["runtimes"]["claude"]["scope"], "untouched runtimes keep their default descriptor"
    assert sessions_config(None)["target"] == "default"
    assert sessions_config({"sessions": {"target": ""}})["target"] == "default", "an empty target is no target"


def test_runtime_descriptor_assumes_an_unknown_runtime_is_intelligent():
    assert runtime_descriptor({}, "shell")["intelligent"] is False
    assert runtime_descriptor({}, "something-new") == {"intelligent": True, "accepts": ["message", "command"], "scope": ""}


def test_merge_config_patch_replaces_top_level_keys_but_merges_sessions_and_its_runtimes():
    config = {"name": "Robo", "voice": "Samantha", "sessions": {"target": "default", "cc_default": False, "runtimes": {"shell": {"intelligent": False, "scope": "old"}}}}
    merged = merge_config_patch(config, {"voice": "Daniel", "sessions": {"target": "all", "runtimes": {"shell": {"scope": "new"}, "codex": {"scope": "x"}}}})
    assert merged["voice"] == "Daniel" and merged["name"] == "Robo"
    assert merged["sessions"]["target"] == "all" and merged["sessions"]["cc_default"] is False
    assert merged["sessions"]["runtimes"]["shell"] == {"intelligent": False, "scope": "new"}
    assert merged["sessions"]["runtimes"]["codex"] == {"scope": "x"}
    assert config["sessions"]["target"] == "default", "the input is not mutated"
    assert merge_config_patch({}, {"sessions": {"cc_default": True}}) == {"sessions": {"cc_default": True}}


def test_read_and_write_round_trip_and_a_broken_file_reads_as_empty(tmp_path):
    file = tmp_path / ".las-agent.json"
    write_agent_config(file, {"name": "Robo", "sessions": {"target": "shell"}})
    assert json.loads(file.read_text())["sessions"]["target"] == "shell"
    assert file.read_text().endswith("\n")
    assert read_agent_config(file)["name"] == "Robo"
    file.write_text("{not json")
    assert read_agent_config(file) == {}
    assert read_agent_config(tmp_path / "missing.json") == {}
