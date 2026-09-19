"""Configuration, per-project state and on-disk helpers.

Configuration is layered: built-in defaults < user-level file < project file.
State is machine-written; if it is corrupt it is set aside and rebuilt, whereas
a corrupt *config* is reported to the user and never overwritten.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

AGENTS = ("claude", "copilot")
OTHER = {"claude": "copilot", "copilot": "claude"}
EFFORTS = {
    "claude": ("low", "medium", "high", "xhigh", "max"),
    "copilot": ("none", "minimal", "low", "medium", "high", "xhigh", "max"),
}
AUTO_SWITCH_MODES = ("ask", "always", "off")


class ConfigError(Exception):
    """The user's configuration is unusable. The message is user-facing."""


def is_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def global_config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "copiclaude"


# --------------------------------------------------------------------------- config


@dataclass
class AgentConfig:
    command: List[str]
    model: str = ""
    effort: str = ""
    args: List[str] = field(default_factory=list)


@dataclass
class Config:
    default_agent: str = "claude"
    auto_switch: str = "ask"
    auto_continue: bool = False
    switch_key: str = "ctrl+k"
    claude: AgentConfig = field(default_factory=lambda: AgentConfig(["claude"]))
    copilot: AgentConfig = field(default_factory=lambda: AgentConfig(["copilot"]))
    warnings: List[str] = field(default_factory=list)

    def agent(self, name: str) -> AgentConfig:
        return self.claude if name == "claude" else self.copilot

    def to_dict(self) -> Dict[str, Any]:
        def agent_dict(cfg: AgentConfig) -> Dict[str, Any]:
            return {
                "command": cfg.command[0] if len(cfg.command) == 1 else cfg.command,
                "model": cfg.model,
                "effort": cfg.effort,
                "args": cfg.args,
            }

        return {
            "default_agent": self.default_agent,
            "auto_switch": self.auto_switch,
            "auto_continue": self.auto_continue,
            "switch_key": self.switch_key,
            "claude": agent_dict(self.claude),
            "copilot": agent_dict(self.copilot),
        }


_TOP_KEYS = {"default_agent", "auto_switch", "auto_continue", "switch_key", "claude", "copilot"}
_AGENT_KEYS = {"command", "model", "effort", "args"}


def _apply_agent(name: str, raw: Any, cfg: AgentConfig, source: str, warnings: List[str]) -> None:
    if not isinstance(raw, dict):
        raise ConfigError("%s: '%s' must be an object" % (source, name))
    for key in raw:
        if key not in _AGENT_KEYS:
            warnings.append("%s: unknown key '%s.%s' ignored" % (source, name, key))
    if "command" in raw:
        command = raw["command"]
        if isinstance(command, str) and command.strip():
            cfg.command = [command]
        elif isinstance(command, list) and command and all(isinstance(c, str) and c for c in command):
            cfg.command = list(command)
        else:
            raise ConfigError("%s: '%s.command' must be a non-empty string or list of strings" % (source, name))
    for key in ("model", "effort"):
        if key in raw:
            if not isinstance(raw[key], str):
                raise ConfigError("%s: '%s.%s' must be a string" % (source, name, key))
            setattr(cfg, key, raw[key].strip())
    if cfg.effort and cfg.effort not in EFFORTS[name]:
        raise ConfigError(
            "%s: '%s.effort' must be one of %s (or empty)" % (source, name, ", ".join(EFFORTS[name]))
        )
    if "args" in raw:
        args = raw["args"]
        if not (isinstance(args, list) and all(isinstance(a, str) for a in args)):
            raise ConfigError("%s: '%s.args' must be a list of strings" % (source, name))
        cfg.args = list(args)


def apply_config(cfg: Config, raw: Any, source: str) -> None:
    """Merge a parsed JSON document into ``cfg`` (mutates), validating as it goes."""
    if not isinstance(raw, dict):
        raise ConfigError("%s: top level must be a JSON object" % source)
    for key in raw:
        if key not in _TOP_KEYS:
            cfg.warnings.append("%s: unknown key '%s' ignored" % (source, key))
    if "default_agent" in raw:
        if raw["default_agent"] not in AGENTS:
            raise ConfigError("%s: 'default_agent' must be 'claude' or 'copilot'" % source)
        cfg.default_agent = raw["default_agent"]
    if "auto_switch" in raw:
        if raw["auto_switch"] not in AUTO_SWITCH_MODES:
            raise ConfigError("%s: 'auto_switch' must be one of %s" % (source, ", ".join(AUTO_SWITCH_MODES)))
        cfg.auto_switch = raw["auto_switch"]
    if "auto_continue" in raw:
        if not isinstance(raw["auto_continue"], bool):
            raise ConfigError("%s: 'auto_continue' must be true or false" % source)
        cfg.auto_continue = raw["auto_continue"]
    if "switch_key" in raw:
        from .keys import parse_key  # local import: keys has no dependency on this module

        try:
            parse_key(raw["switch_key"])
        except ValueError as exc:
            raise ConfigError("%s: 'switch_key': %s" % (source, exc))
        cfg.switch_key = raw["switch_key"]
    for name in AGENTS:
        if name in raw:
            _apply_agent(name, raw[name], cfg.agent(name), source, cfg.warnings)


def read_json_file(path: Path) -> Optional[Any]:
    """Parse a JSON file. Missing -> None. Unparseable -> ConfigError."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ConfigError("%s: cannot read (%s)" % (path, exc))
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ConfigError("%s: invalid JSON (%s). Fix or delete the file." % (path, exc))


def load_config(project_config: Path, user_config: Optional[Path] = None) -> Tuple[Config, Dict[str, bool]]:
    """Return the effective config and which layers were found."""
    cfg = Config()
    found = {"user": False, "project": False}
    layers = []
    if user_config is not None:
        layers.append(("user", user_config))
    layers.append(("project", project_config))
    for label, path in layers:
        raw = read_json_file(path)
        if raw is not None:
            apply_config(cfg, raw, str(path))
            found[label] = True
    return cfg, found


def save_config_file(path: Path, cfg: Config) -> None:
    atomic_write(path, json.dumps(cfg.to_dict(), indent=2) + "\n")


# --------------------------------------------------------------------------- state


@dataclass
class State:
    current_agent: Optional[str] = None
    sessions: Dict[str, str] = field(default_factory=dict)
    switch_count: int = 0
    last_quota_at: Dict[str, float] = field(default_factory=dict)
    handoff_pending: bool = False
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_agent": self.current_agent,
            "sessions": self.sessions,
            "switch_count": self.switch_count,
            "last_quota_at": self.last_quota_at,
            "handoff_pending": self.handoff_pending,
        }


def _state_from_raw(raw: Any) -> State:
    if not isinstance(raw, dict):
        raise ValueError("state is not an object")
    state = State()
    if raw.get("current_agent") in AGENTS:
        state.current_agent = raw["current_agent"]
    sessions = raw.get("sessions")
    if isinstance(sessions, dict):
        for name in AGENTS:
            if is_uuid(sessions.get(name)):
                state.sessions[name] = sessions[name]
    for name in AGENTS:  # 0.1 layout: claude_session_id / copilot_session_id
        legacy = raw.get(name + "_session_id")
        if name not in state.sessions and is_uuid(legacy):
            state.sessions[name] = legacy
    if isinstance(raw.get("switch_count"), int) and not isinstance(raw.get("switch_count"), bool):
        state.switch_count = max(0, raw["switch_count"])
    quota = raw.get("last_quota_at")
    if isinstance(quota, dict):
        for name in AGENTS:
            if isinstance(quota.get(name), (int, float)) and not isinstance(quota.get(name), bool):
                state.last_quota_at[name] = float(quota[name])
    state.handoff_pending = raw.get("handoff_pending") is True
    return state


def load_state(path: Path) -> State:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return State()
    except OSError as exc:
        state = State()
        state.warnings.append("cannot read %s (%s); starting with a clean state" % (path, exc))
        return state
    try:
        return _state_from_raw(json.loads(text))
    except ValueError as exc:
        backup = path.with_name("%s.corrupt-%d" % (path.name, int(time.time())))
        try:
            os.replace(path, backup)
            where = "saved as %s" % backup.name
        except OSError:
            where = "could not be moved aside"
        state = State()
        state.warnings.append("%s was corrupt (%s) and %s; starting with a clean state" % (path.name, exc, where))
        return state


def save_state(path: Path, state: State) -> None:
    atomic_write(path, json.dumps(state.to_dict(), indent=2) + "\n")
