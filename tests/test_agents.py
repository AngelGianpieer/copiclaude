import json

from copiclaude.agents import AGENT_IMPLS, PROMPT_PREFIX, SignalWatcher
from copiclaude.store import AgentConfig

SID = "11111111-2222-4333-8444-555555555555"
CLAUDE, COPILOT = AGENT_IMPLS["claude"], AGENT_IMPLS["copilot"]


def jl(*records):
    return "".join(json.dumps(r) + "\n" for r in records)


def claude_file(home, sid=SID):
    d = home / ".claude" / "projects" / "-some-project"
    d.mkdir(parents=True, exist_ok=True)
    return d / (sid + ".jsonl")


def copilot_file(home, sid=SID):
    d = home / ".copilot" / "session-state" / sid
    d.mkdir(parents=True, exist_ok=True)
    return d / "events.jsonl"


# ---------------------------------------------------------------- argv


def test_claude_new_and_resume_argv():
    cfg = AgentConfig(["claude"], model="sonnet", effort="high", args=["--add-dir", "x"])
    assert CLAUDE.build_argv(cfg, ["/bin/claude"], SID, False, None) == [
        "/bin/claude", "--session-id", SID, "--model", "sonnet", "--effort", "high", "--add-dir", "x"]
    assert CLAUDE.build_argv(cfg, ["/bin/claude"], SID, True, "hi there")[:3] == ["/bin/claude", "--resume", SID]


def test_claude_prompt_comes_before_user_args_so_variadic_flags_cannot_swallow_it():
    cfg = AgentConfig(["claude"], args=["--add-dir", "a", "b"])
    argv = CLAUDE.build_argv(cfg, ["c"], SID, False, "PROMPT")
    assert argv.index("PROMPT") < argv.index("--add-dir")


def test_copilot_argv():
    cfg = AgentConfig(["copilot"], model="auto", effort="high", args=["--allow-all"])
    assert COPILOT.build_argv(cfg, ["/bin/copilot"], SID, True, "PROMPT") == [
        "/bin/copilot", "--session-id", SID, "--model", "auto", "--reasoning-effort", "high", "--allow-all", "-i", "PROMPT"]


def test_wrapper_command_keeps_its_leading_args():
    cfg = AgentConfig(["python", "fake.py", "claude"])
    head = CLAUDE.resolve(cfg)
    assert head[1:] == ["fake.py", "claude"]


def test_resolve_missing_command():
    assert CLAUDE.resolve(AgentConfig(["definitely-not-installed-xyz"])) is None


# ---------------------------------------------------------------- session discovery


def test_claude_session_exists_only_once_the_file_does(isolated_env):
    assert not CLAUDE.session_exists(SID)
    claude_file(isolated_env).write_text("{}\n")
    assert CLAUDE.session_exists(SID)


def test_session_lookup_rejects_non_uuid_ids(isolated_env):
    assert not CLAUDE.session_exists("../../etc/passwd")
    assert not COPILOT.session_exists("*")
    assert CLAUDE.transcript("*") is None


def test_copilot_session_exists(isolated_env):
    assert not COPILOT.session_exists(SID)
    copilot_file(isolated_env).write_text("{}\n")
    assert COPILOT.session_exists(SID)


# ---------------------------------------------------------------- context


def test_claude_context_extracts_human_prompts_and_last_reply(isolated_env):
    claude_file(isolated_env).write_text(jl(
        {"type": "user", "message": {"role": "user", "content": "first task"}, "origin": {"kind": "human"}},
        {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": "done one"}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}},
        {"type": "user", "message": {"content": "<system-reminder>ignore</system-reminder>"}},
        {"type": "user", "message": {"content": "side", "role": "user"}, "isSidechain": True},
        {"type": "user", "message": {"content": "<div> is misaligned, why?"}, "origin": {"kind": "human"}},
        {"type": "user", "message": {"content": PROMPT_PREFIX + " Read the file"}},
        {"type": "user", "message": {"content": "second task"}, "origin": {"kind": "human"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "working on two"}]}},
        {"type": "assistant", "isApiErrorMessage": True, "message": {"content": [{"type": "text", "text": "limit"}]}},
    ) + "not json at all\n")
    ctx = CLAUDE.read_context(SID)
    assert ctx.found and ctx.prompts == ["first task", "<div> is misaligned, why?", "second task"]
    assert ctx.last_reply == "working on two"


def test_claude_context_keeps_only_the_most_recent_prompts(isolated_env):
    claude_file(isolated_env).write_text(jl(*[
        {"type": "user", "message": {"content": "p%d" % i}} for i in range(9)]))
    assert CLAUDE.read_context(SID, max_prompts=3).prompts == ["p6", "p7", "p8"]


def test_context_for_unknown_session_is_empty(isolated_env):
    for agent in (CLAUDE, COPILOT):
        ctx = agent.read_context(SID)
        assert not ctx.found and ctx.prompts == [] and ctx.last_reply == ""


def test_copilot_context(isolated_env):
    copilot_file(isolated_env).write_text(jl(
        {"type": "session.start", "data": {}},
        {"type": "user.message", "data": {"content": "do the thing", "transformedContent": "<datetime>do the thing"}},
        {"type": "assistant.message", "data": {"content": "", "toolRequests": [{}]}},
        {"type": "assistant.message", "data": {"content": "the thing is done"}},
        {"type": "user.message", "data": {"content": PROMPT_PREFIX + " Read"}},
    ))
    ctx = COPILOT.read_context(SID)
    assert ctx.prompts == ["do the thing"] and ctx.last_reply == "the thing is done"


# ---------------------------------------------------------------- structured quota signals


def test_claude_signal_from_api_error_records():
    err = {"type": "assistant", "isApiErrorMessage": True, "error": "rate_limit",
           "message": {"content": [{"type": "text", "text": "You've hit your limit - resets 3pm"}]}}
    assert "hit your limit" in CLAUDE.signal_from_line(json.dumps(err))
    assert CLAUDE.signal_from_line(json.dumps({**err, "error": "", "message": {"content": [{"type": "text", "text": "Claude AI usage limit reached|123"}]}}))


def test_claude_signal_ignores_normal_messages_and_other_errors():
    normal = {"type": "assistant", "message": {"content": [{"type": "text", "text": "You've hit your limit is the message you saw"}]}}
    assert CLAUDE.signal_from_line(json.dumps(normal)) is None
    other = {"type": "assistant", "isApiErrorMessage": True, "message": {"content": [{"type": "text", "text": "invalid request"}]}}
    assert CLAUDE.signal_from_line(json.dumps(other)) is None
    assert CLAUDE.signal_from_line("garbage") is None


def test_copilot_signal_from_429_and_text():
    fail = {"type": "model.model_call_failure", "data": {"modelCall": {"status": 429, "error": "too many"}}}
    assert COPILOT.signal_from_line(json.dumps(fail))
    turn = {"type": "model.turn_failed", "data": {"error": "402 You've reached your monthly quota"}}
    assert COPILOT.signal_from_line(json.dumps(turn))


def test_copilot_signal_ignores_unrelated_failures():
    # the real failure recorded on a developer machine: a 400 about reasoning effort
    bad = {"type": "model.model_call_failure", "data": {"modelCall": {"status": 400,
           "error": '{"message":"reasoning_effort \\"medium\\" was provided, but model does not support reasoning effort"}'}}}
    assert COPILOT.signal_from_line(json.dumps(bad)) is None
    assert COPILOT.signal_from_line(json.dumps({"type": "assistant.message", "data": {"content": "rate limit exceeded is an error"}})) is None


def test_watcher_only_sees_records_written_after_launch(isolated_env):
    path = claude_file(isolated_env)
    old = {"type": "assistant", "isApiErrorMessage": True, "error": "rate_limit", "message": {"content": []}}
    path.write_text(jl(old))
    watcher = SignalWatcher(CLAUDE, SID)
    assert watcher.poll() is None  # the old error predates this launch
    with open(path, "a") as fh:
        fh.write(json.dumps(old))  # a new record, but the line is still incomplete
    assert watcher.poll() is None
    with open(path, "a") as fh:
        fh.write("\n")
    assert watcher.poll()


def test_watcher_finds_a_session_file_created_after_launch(isolated_env):
    watcher = SignalWatcher(CLAUDE, SID)
    assert watcher.poll() is None
    claude_file(isolated_env).write_text(jl(
        {"type": "assistant", "isApiErrorMessage": True, "error": "rate_limit", "message": {"content": []}}))
    assert watcher.poll()
