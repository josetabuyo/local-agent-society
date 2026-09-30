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
    seeded = merge_config_patch({}, {"sessions": {"cc_default": True}})["sessions"]
    assert seeded["cc_default"] is True and seeded["target"] == "default" and "runtimes" in seeded, "a first patch seeds the whole section"


def test_read_and_write_round_trip_and_a_broken_file_reads_as_empty(tmp_path):
    file = tmp_path / ".las-agent.json"
    write_agent_config(file, {"name": "Robo", "sessions": {"target": "shell"}})
    assert json.loads(file.read_text())["sessions"]["target"] == "shell"
    assert file.read_text().endswith("\n")
    assert read_agent_config(file)["name"] == "Robo"
    file.write_text("{not json")
    assert read_agent_config(file) == {}
    assert read_agent_config(tmp_path / "missing.json") == {}


def test_sessions_config_ignores_a_hand_edited_file_of_the_wrong_shape():
    assert sessions_config({"sessions": "shell"})["target"] == "default"
    assert sessions_config({"sessions": {"runtimes": ["shell"], "target": "all"}})["target"] == "all"
    assert sessions_config({"sessions": {"runtimes": {"shell": "nope"}}})["runtimes"]["shell"]["accepts"] == ["command"]
    assert sessions_config("garbage")["target"] == "default"


def test_strict_read_refuses_a_broken_file_but_not_a_missing_one(tmp_path):
    from cli.agent_config import BrokenAgentConfig, accepts_only_commands, descriptor_for
    import pytest
    file = tmp_path / ".las-agent.json"
    assert read_agent_config(file, strict=True) == {}, "missing: nothing to protect"
    file.write_text('{"name": "Robo",}')
    with pytest.raises(BrokenAgentConfig):
        read_agent_config(file, strict=True)
    file.write_text('[1, 2]')
    with pytest.raises(BrokenAgentConfig):
        read_agent_config(file, strict=True)
    policy = sessions_config({})
    assert accepts_only_commands(descriptor_for(policy, "shell")) is True
    assert accepts_only_commands(descriptor_for(policy, "claude")) is False
    assert accepts_only_commands({"accepts": "command"}) is False


def test_the_first_sessions_patch_seeds_the_whole_section_with_its_descriptors():
    merged = merge_config_patch({"name": "Robo"}, {"sessions": {"target": "shell"}})
    assert merged["sessions"]["target"] == "shell" and merged["sessions"]["cc_default"] is False
    assert set(merged["sessions"]["runtimes"]) == {"claude", "codex", "shell"}
    again = merge_config_patch(merged, {"sessions": {"cc_default": True}})
    assert again["sessions"]["target"] == "shell", "a later patch merges, it does not reseed"
