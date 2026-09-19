"""What is specific to each assistant: how to launch it, where it keeps its
session, how to read that session, and how "out of quota" looks.

The session files are read best-effort. Their formats are the CLIs' own and may
change, so every reader degrades to "nothing found" instead of raising.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Pattern, Tuple

from .detect import phrase
from .store import AgentConfig, is_uuid

# The first user turn we inject ourselves; recognised so it is never echoed back
# into the next handoff as if the user had typed it.
PROMPT_PREFIX = "Continuing from a previous assistant session."

MAX_TAIL_BYTES = 2_000_000


def _compile(*phrases: str) -> List[Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in phrases]


class Context:
    """What the leaving agent was doing, as recovered from its session file."""

    def __init__(self) -> None:
        self.prompts: List[str] = []
        self.last_reply: str = ""
        self.found: bool = False


def tail_lines(path: Path, max_bytes: int = MAX_TAIL_BYTES) -> List[str]:
    try:
        size = path.stat().st_size
        with open(str(path), "rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
                handle.readline()  # drop a probably-partial first line
            data = handle.read()
    except OSError:
        return []
    return data.decode("utf-8", errors="replace").splitlines()


def _loads(line: str) -> Optional[dict]:
    try:
        value = json.loads(line)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _clean(text: str) -> str:
    return text.strip()


def _is_ours(text: str) -> bool:
    return text.startswith(PROMPT_PREFIX)


# Claude Code records slash commands, hook output and background notices as "user" turns.
_SYSTEM_TURN = re.compile(r"^<(?:command-|local-command|system-reminder|task-notification|bash-|user-prompt-submit-hook)")


class Agent:
    name = ""
    label = ""
    quota_patterns: List[Pattern[str]] = []

    # -- launching -------------------------------------------------------
    def build_argv(
        self, cfg: AgentConfig, head: List[str], session_id: str, resume: bool, prompt: Optional[str]
    ) -> List[str]:
        """``head`` is the resolved executable (plus any fixed leading args)."""
        raise NotImplementedError

    def resolve(self, cfg: AgentConfig) -> Optional[List[str]]:
        """Absolute-path argv prefix for the executable, or None if it is not installed."""
        head = cfg.command[0]
        found = shutil.which(head) if not os.path.dirname(head) else (head if os.path.exists(head) else None)
        if not found:
            return None
        return [found] + cfg.command[1:]

    # -- sessions --------------------------------------------------------
    def transcript(self, session_id: str) -> Optional[Path]:
        raise NotImplementedError

    def session_exists(self, session_id: str) -> bool:
        return is_uuid(session_id) and self.transcript(session_id) is not None

    def read_context(self, session_id: str, max_prompts: int = 5) -> Context:
        raise NotImplementedError

    def signal_from_line(self, line: str) -> Optional[str]:
        """A structured "quota/limit" error recorded by the agent, or None."""
        raise NotImplementedError

    def iter_records(self, session_id: str) -> Iterator[dict]:
        path = self.transcript(session_id) if is_uuid(session_id) else None
        if path is None:
            return iter(())
        return (rec for rec in (_loads(l) for l in tail_lines(path)) if rec)


class ClaudeAgent(Agent):
    name = "claude"
    label = "Claude Code"
    quota_patterns = _compile(
        r"you'?ve\s*hit\s*your\s*(?:\w+\s*)?(?:usage\s*)?limit",
        r"(?:5-?hour|session|weekly|usage|opus|sonnet)\s*limit\s*reached",
        r"limit\s*reached\s*[∙·•|\-]+\s*resets?",
        r"claude\s*(?:ai\s*)?usage\s*limit",
        r"limit.{0,60}resets?\s*(?:at|in)\s*\d",
        r"rate_limit_error",
        r"api\s*error:?\s*429",
    )

    def build_argv(self, cfg, head, session_id, resume, prompt):
        argv = list(head)
        argv += ["--resume", session_id] if resume else ["--session-id", session_id]
        if cfg.model:
            argv += ["--model", cfg.model]
        if cfg.effort:
            argv += ["--effort", cfg.effort]
        if prompt:
            argv.append(prompt)
        argv += cfg.args
        return argv

    def _root(self) -> Path:
        return Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude")) / "projects"

    def transcript(self, session_id):
        if not is_uuid(session_id):
            return None
        for path in self._root().glob("*/%s.jsonl" % session_id):
            return path
        return None

    def read_context(self, session_id, max_prompts=5):
        ctx = Context()
        prompts: List[str] = []
        reply = ""
        for rec in self.iter_records(session_id):
            ctx.found = True
            if rec.get("isSidechain"):
                continue
            message = rec.get("message")
            if not isinstance(message, dict):
                continue
            if rec.get("type") == "user" and isinstance(message.get("content"), str):
                origin = rec.get("origin")
                if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
                    continue
                text = _clean(message["content"])
                if text and not _SYSTEM_TURN.match(text) and not _is_ours(text):
                    prompts.append(text)
            elif rec.get("type") == "assistant" and not rec.get("isApiErrorMessage"):
                blocks = message.get("content")
                if isinstance(blocks, list):
                    text = _clean("\n".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"))
                    if text:
                        reply = text
        ctx.prompts = prompts[-max_prompts:]
        ctx.last_reply = reply
        return ctx

    def signal_from_line(self, line):
        rec = _loads(line)
        if not rec or rec.get("type") != "assistant" or not rec.get("isApiErrorMessage"):
            return None
        message = rec.get("message") if isinstance(rec.get("message"), dict) else {}
        blocks = message.get("content")
        text = ""
        if isinstance(blocks, list):
            text = " ".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
        elif isinstance(blocks, str):
            text = blocks
        kind = str(rec.get("error") or "")
        if kind in ("rate_limit", "billing_error", "quota") or any(p.search(text) for p in self.quota_patterns):
            return (text or kind).strip()[:200]
        return None


class CopilotAgent(Agent):
    name = "copilot"
    label = "GitHub Copilot CLI"
    quota_patterns = _compile(
        phrase("next model call is final"),
        r"session\s*limits?\s*reached",
        r"quota\s*(?:exceeded|exhausted|reached)",
        r"(?:premium\s*)?requests?\s*quota",
        r"you'?ve\s*(?:reached|hit|exceeded)\s*your\s*.{0,40}(?:limit|quota)",
        r"rate\s*limit(?:ed|\s*exceeded|\s*reached)",
    )

    def build_argv(self, cfg, head, session_id, resume, prompt):
        argv = list(head)
        argv += ["--session-id", session_id]  # resumes if it exists, creates it otherwise
        if cfg.model:
            argv += ["--model", cfg.model]
        if cfg.effort:
            argv += ["--reasoning-effort", cfg.effort]
        argv += cfg.args
        if prompt:
            argv += ["-i", prompt]
        return argv

    def _dir(self, session_id: str) -> Path:
        return Path(os.environ.get("COPILOT_HOME") or (Path.home() / ".copilot")) / "session-state" / session_id

    def transcript(self, session_id):
        if not is_uuid(session_id):
            return None
        path = self._dir(session_id) / "events.jsonl"
        return path if path.is_file() else None

    def read_context(self, session_id, max_prompts=5):
        ctx = Context()
        prompts: List[str] = []
        reply = ""
        for rec in self.iter_records(session_id):
            ctx.found = True
            data = rec.get("data") if isinstance(rec.get("data"), dict) else {}
            if rec.get("type") == "user.message":
                text = _clean(str(data.get("content") or ""))
                if text and not _is_ours(text):
                    prompts.append(text)
            elif rec.get("type") == "assistant.message":
                text = _clean(str(data.get("content") or ""))
                if text:
                    reply = text
        ctx.prompts = prompts[-max_prompts:]
        ctx.last_reply = reply
        return ctx

    def signal_from_line(self, line):
        rec = _loads(line)
        if not rec:
            return None
        kind = str(rec.get("type") or "")
        if not (kind.endswith("failure") or kind.endswith("failed") or kind.endswith("error")):
            return None
        data = rec.get("data") if isinstance(rec.get("data"), dict) else {}
        call = data.get("modelCall") if isinstance(data.get("modelCall"), dict) else {}
        text = " ".join(str(x) for x in (data.get("error"), call.get("error"), data.get("message")) if x)
        if call.get("status") == 429 or any(p.search(text) for p in self.quota_patterns):
            return (text or "HTTP 429").strip()[:200]
        return None


AGENT_IMPLS: Dict[str, Agent] = {"claude": ClaudeAgent(), "copilot": CopilotAgent()}


class SignalWatcher:
    """Tails the agent's own session file for structured quota errors.

    Only records appended after the agent was launched are considered, so old
    errors from a previous run cannot trigger a switch.
    """

    def __init__(self, agent: Agent, session_id: str) -> None:
        self.agent = agent
        self.session_id = session_id
        self._path: Optional[Path] = None
        self._offset = 0
        self._partial = b""
        existing = agent.transcript(session_id)
        if existing is not None:
            self._path = existing
            try:
                self._offset = existing.stat().st_size
            except OSError:
                self._offset = 0

    def poll(self) -> Optional[str]:
        if self._path is None:
            self._path = self.agent.transcript(self.session_id)
            if self._path is None:
                return None
            self._offset = 0
        try:
            size = self._path.stat().st_size
            if size < self._offset:  # truncated/rotated
                self._offset, self._partial = 0, b""
            if size == self._offset:
                return None
            with open(str(self._path), "rb") as handle:
                handle.seek(self._offset)
                chunk = handle.read(min(size - self._offset, MAX_TAIL_BYTES))
        except OSError:
            return None
        self._offset += len(chunk)
        data = self._partial + chunk
        lines = data.split(b"\n")
        self._partial = lines.pop()  # incomplete trailing line, completed on a later poll
        for raw in lines:
            reason = self.agent.signal_from_line(raw.decode("utf-8", errors="replace"))
            if reason:
                return reason
        return None


def new_session_id() -> str:
    return str(uuid.uuid4())
