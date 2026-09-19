import json

import pytest

from copiclaude import store
from copiclaude.store import Config, ConfigError, apply_config, load_config, load_state, save_state


def test_defaults():
    cfg = Config()
    assert (cfg.default_agent, cfg.auto_switch, cfg.auto_continue, cfg.switch_key) == ("claude", "ask", False, "ctrl+k")
    assert cfg.claude.command == ["claude"] and cfg.copilot.command == ["copilot"]


def test_layers_project_overrides_user(tmp_path):
    user, proj = tmp_path / "u.json", tmp_path / "p.json"
    user.write_text(json.dumps({"default_agent": "copilot", "claude": {"model": "sonnet"}, "auto_switch": "always"}))
    proj.write_text(json.dumps({"claude": {"effort": "high"}, "auto_switch": "off"}))
    cfg, found = load_config(proj, user)
    assert found == {"user": True, "project": True}
    assert cfg.default_agent == "copilot"
    assert (cfg.claude.model, cfg.claude.effort) == ("sonnet", "high")
    assert cfg.auto_switch == "off"


def test_missing_files_are_fine(tmp_path):
    cfg, found = load_config(tmp_path / "nope.json", tmp_path / "nope2.json")
    assert found == {"user": False, "project": False}
    assert cfg.default_agent == "claude"


def test_old_0_1_config_still_loads(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"default_agent": "claude", "claude": {"model": "sonnet", "effort": "medium"},
                                "copilot": {"model": "auto", "effort": "high"}}))
    cfg, _ = load_config(path)
    assert cfg.copilot.effort == "high" and cfg.claude.model == "sonnet"


@pytest.mark.parametrize(
    "raw",
    [
        {"default_agent": "gemini"},
        {"auto_switch": "sometimes"},
        {"auto_continue": "yes"},
        {"switch_key": "f5"},
        {"switch_key": "ctrl+c"},
        {"claude": {"effort": "extreme"}},
        {"copilot": {"effort": "xhigh2"}},
        {"claude": {"command": ""}},
        {"claude": {"command": [1]}},
        {"claude": {"args": "--x"}},
        {"claude": "sonnet"},
        ["not", "an", "object"],
    ],
)
def test_invalid_values_are_reported(raw):
    with pytest.raises(ConfigError):
        apply_config(Config(), raw, "test")


def test_unknown_keys_warn_but_do_not_fail():
    cfg = Config()
    apply_config(cfg, {"colour": "red", "claude": {"modle": "x"}}, "src")
    assert len(cfg.warnings) == 2


def test_command_may_be_a_list_for_wrappers():
    cfg = Config()
    apply_config(cfg, {"claude": {"command": ["python", "fake.py", "claude"], "args": ["--x"]}}, "src")
    assert cfg.claude.command == ["python", "fake.py", "claude"] and cfg.claude.args == ["--x"]


def test_broken_config_json_is_an_error_and_is_never_overwritten(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ not json")
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "invalid JSON" in str(exc.value)
    assert path.read_text() == "{ not json"


def test_config_with_bom_loads(tmp_path):
    path = tmp_path / "c.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"default_agent": "copilot"}).encode())
    assert load_config(path)[0].default_agent == "copilot"


def test_config_round_trip(tmp_path):
    cfg = Config()
    cfg.claude.model = "opus"
    cfg.copilot.command = ["a", "b"]
    path = tmp_path / "out.json"
    store.save_config_file(path, cfg)
    again, _ = load_config(path)
    assert again.claude.model == "opus" and again.copilot.command == ["a", "b"]


# ---------------------------------------------------------------- state

UUID_A = "11111111-2222-4333-8444-555555555555"
UUID_B = "66666666-7777-4888-9999-000000000000"


def test_state_round_trip(tmp_path):
    path = tmp_path / "state.json"
    state = load_state(path)
    state.current_agent, state.sessions = "copilot", {"claude": UUID_A, "copilot": UUID_B}
    state.switch_count, state.last_quota_at, state.handoff_pending = 3, {"claude": 12.5}, True
    save_state(path, state)
    again = load_state(path)
    assert again.to_dict() == state.to_dict()


def test_state_migrates_0_1_layout(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"current_agent": "copilot", "claude_session_id": UUID_A,
                                "copilot_session_id": UUID_B, "switch_count": 1}))
    state = load_state(path)
    assert state.sessions == {"claude": UUID_A, "copilot": UUID_B}
    assert (state.current_agent, state.switch_count) == ("copilot", 1)


def test_corrupt_state_is_set_aside_not_silently_lost(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{oops")
    state = load_state(path)
    assert state.sessions == {} and state.warnings
    assert not path.exists()
    assert list(tmp_path.glob("state.json.corrupt-*"))[0].read_text() == "{oops"


def test_state_ignores_garbage_values(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"current_agent": "nope", "sessions": {"claude": "../../etc/passwd", "copilot": 5},
                                "switch_count": "many", "last_quota_at": {"claude": "x"}}))
    state = load_state(path)
    assert state.current_agent is None and state.sessions == {}
    assert state.switch_count == 0 and state.last_quota_at == {}


def test_atomic_write_leaves_no_temp_files(tmp_path):
    target = tmp_path / "d" / "f.txt"
    store.atomic_write(target, "hello")
    assert target.read_text() == "hello"
    assert [p.name for p in target.parent.iterdir()] == ["f.txt"]
