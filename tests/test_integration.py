"""End-to-end: the real copiclaude, in a real pseudo-terminal, driving fake agents.

Runs on Linux and macOS (pty) and Windows (ConPTY via pywinpty) using copiclaude's
own pty layer as the test harness.
"""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from copiclaude.detect import strip_ansi
from copiclaude.ptyproc import spawn_pty

from conftest import FAKE_AGENT

SRC = str(Path(__file__).resolve().parent.parent / "src")
TIMEOUT = 30


def write_config(project, **extra):
    state = project / ".copiclaude"
    state.mkdir(exist_ok=True)
    config = {
        "claude": {"command": [sys.executable, FAKE_AGENT, "claude"]},
        "copilot": {"command": [sys.executable, FAKE_AGENT, "copilot"]},
    }
    config.update(extra)
    (state / "config.json").write_text(json.dumps(config))


def read_state(project):
    return json.loads((project / ".copiclaude" / "state.json").read_text())


def child_env(extra=None):
    env = dict(os.environ)
    env.update(PYTHONPATH=SRC, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", TERM="xterm-256color")
    env.pop("COPICLAUDE", None)
    env.update(extra or {})
    return env


class Session:
    def __init__(self, project, env=None):
        self.project = project
        self.env = child_env(env)
        self.proc = spawn_pty([sys.executable, "-m", "copiclaude"], str(project), self.env, 30, 120)
        self.raw = bytearray()
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self):
        while True:
            data = self.proc.read()
            if not data:
                return
            self.raw += data

    def text(self):
        return strip_ansi(self.raw.decode("utf-8", errors="replace"))

    def expect(self, needle, count=1, timeout=TIMEOUT):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.text().count(needle) >= count:
                return
            if self.proc.poll() is not None:
                time.sleep(0.3)  # let the reader thread drain the final output
                if self.text().count(needle) >= count:
                    return
                pytest.fail("copiclaude exited (code %s) before %r appeared. Output:\n%s"
                            % (self.proc.poll(), needle, self.text()[-3000:]))
            time.sleep(0.05)
        pytest.fail("timed out waiting for %r (x%d). Output so far:\n%s" % (needle, count, self.text()[-3000:]))

    def send(self, data):
        self.proc.write(data if isinstance(data, bytes) else data.encode())

    def wait_exit(self, timeout=TIMEOUT):
        deadline = time.time() + timeout
        while time.time() < deadline:
            code = self.proc.poll()
            if code is not None:
                self._thread.join(2)
                return code
            time.sleep(0.05)
        pytest.fail("copiclaude did not exit. Output:\n%s" % self.text()[-3000:])

    def close(self):
        try:
            self.proc.terminate(1.0)
        finally:
            self.proc.close()


@pytest.fixture
def session_factory(project_dir):
    sessions = []

    def make(env=None):
        s = Session(project_dir, env)
        sessions.append(s)
        return s

    yield make
    for s in sessions:
        s.close()


def settle():
    time.sleep(1.4)  # longer than the launch guard that ignores the switch key right after a start


def test_runs_the_agent_and_propagates_its_exit_code(project_dir, session_factory):
    write_config(project_dir)
    s = session_factory()
    s.expect("FAKE-claude READY")
    assert "--session-id" in s.text()  # brand-new session
    s.send("hello\r")
    s.expect("echo:hello")
    s.send("exit\r")
    assert s.wait_exit() == 7


def test_ctrl_k_switches_and_hands_over(project_dir, session_factory):
    write_config(project_dir)
    s = session_factory()
    s.expect("FAKE-claude READY")
    settle()
    s.send(b"\x0b")
    s.expect("FAKE-copilot READY")
    out = s.text()
    assert "Continuing from a previous assistant session." in out and "-i" in out
    handoff = (project_dir / ".copiclaude" / "HANDOFF.md").read_text()
    assert "# Handoff: claude -> copilot" in handoff and "manually" in handoff
    assert read_state(project_dir)["current_agent"] == "copilot"
    assert not (project_dir / "CLAUDE.md").exists() and not (project_dir / "AGENTS.md").exists()
    settle()
    s.send("\x1b[107;5u")  # the same key as the kitty keyboard protocol reports it
    s.expect("FAKE-claude READY", count=2)
    assert read_state(project_dir)["switch_count"] == 2
    s.send("exit\r")
    assert s.wait_exit() == 7


def test_limit_message_asks_first_then_switches_on_confirmation(project_dir, session_factory):
    write_config(project_dir)
    s = session_factory()
    s.expect("FAKE-claude READY")
    s.send("limit\r")
    s.expect("looks out of quota")
    assert "FAKE-copilot" not in s.text()  # asked, did not act
    s.send(b"\x0b")
    s.expect("FAKE-copilot READY")
    state = read_state(project_dir)
    assert "claude" in state["last_quota_at"]
    assert "usage limit" in (project_dir / ".copiclaude" / "HANDOFF.md").read_text()


def test_ignoring_the_proposal_keeps_the_agent_running(project_dir, session_factory):
    write_config(project_dir)
    s = session_factory()
    s.expect("FAKE-claude READY")
    s.send("limit\r")
    s.expect("looks out of quota")
    s.send("x\r")  # any other key dismisses it and is still delivered to the agent
    s.expect("echo:x")
    s.send("exit\r")
    assert s.wait_exit() == 7
    assert "FAKE-copilot" not in s.text()


def test_merely_talking_about_limits_never_switches(project_dir, session_factory):
    write_config(project_dir)
    s = session_factory()
    s.expect("FAKE-claude READY")
    s.send("talk\r")
    time.sleep(3)
    s.send("exit\r")
    assert s.wait_exit() == 7
    assert "FAKE-copilot" not in s.text()


def test_always_mode_switches_without_asking(project_dir, session_factory):
    write_config(project_dir, auto_switch="always")
    s = session_factory()
    s.expect("FAKE-claude READY")
    s.send("limit\r")
    s.expect("FAKE-copilot READY")
    assert "looks out of quota" not in s.text()


def test_off_mode_never_reacts(project_dir, session_factory):
    write_config(project_dir, auto_switch="off")
    s = session_factory()
    s.expect("FAKE-claude READY")
    s.send("limit\r")
    time.sleep(3)
    assert "looks out of quota" not in s.text() and "FAKE-copilot" not in s.text()
    s.send("exit\r")
    assert s.wait_exit() == 7


def test_switch_command_from_another_terminal(project_dir, session_factory):
    write_config(project_dir)
    s = session_factory()
    s.expect("FAKE-claude READY")
    settle()
    done = subprocess.run([sys.executable, "-m", "copiclaude", "switch"], cwd=str(project_dir), env=child_env(),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=30)
    assert done.returncode == 0, done.stderr
    s.expect("FAKE-copilot READY")
    assert "requested" in s.text()


def test_missing_agent_is_a_clear_error(project_dir, session_factory):
    write_config(project_dir, claude={"command": "definitely-not-installed-xyz"})
    s = session_factory()
    s.expect("was not found")
    assert s.wait_exit() == 127


def test_switching_target_missing_keeps_the_current_agent_alive(project_dir, session_factory):
    write_config(project_dir, copilot={"command": "definitely-not-installed-xyz"})
    s = session_factory()
    s.expect("FAKE-claude READY")
    settle()
    s.send(b"\x0b")
    s.expect("cannot switch")
    s.send("still here\r")
    s.expect("echo:still here")  # the agent was not killed
    s.send("exit\r")
    assert s.wait_exit() == 7


@pytest.mark.skipif(os.name == "nt", reason="terminal-mode bookkeeping is VT/POSIX behaviour")
def test_terminal_modes_the_killed_agent_left_on_are_reset(project_dir, session_factory):
    write_config(project_dir)
    s = session_factory()
    s.expect("FAKE-claude READY")
    s.send("modes\r")
    s.expect("modes on")
    settle()
    mark = len(s.raw)
    s.send(b"\x0b")
    s.expect("FAKE-copilot READY")
    after = bytes(s.raw[mark:])
    for seq in (b"\x1b[?1049l", b"\x1b[?2004l", b"\x1b[?1000l"):
        assert seq in after


def test_first_launch_form_is_retried_the_other_way_when_the_cli_refuses_it(project_dir, session_factory):
    write_config(project_dir)
    s = session_factory({"FAKE_FAIL_ON": "--session-id"})
    s.expect("retrying as a resumed session")
    s.expect("FAKE-claude READY", count=2)
    assert "--resume" in s.text()


def test_a_second_instance_is_refused(project_dir, session_factory):
    write_config(project_dir)
    s = session_factory()
    s.expect("FAKE-claude READY")
    other = session_factory()
    other.expect("already running")
    assert other.wait_exit() == 1
