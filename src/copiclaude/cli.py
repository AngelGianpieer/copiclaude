"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__, handoff
from .agents import AGENT_IMPLS
from .i18n import language, t
from .keys import parse_key
from .project import LockError, Project, ProjectLock, find_root, is_risky_root
from .store import (
    AGENTS,
    AUTO_SWITCH_MODES,
    EFFORTS,
    Config,
    ConfigError,
    global_config_dir,
    load_config,
    load_state,
    read_json_file,
    save_config_file,
)

def _err(text: str) -> None:
    print("copiclaude: " + text, file=sys.stderr)


def _project() -> Project:
    # Agents always start in the project root: Claude Code keys its saved sessions by
    # directory, so starting from a subdirectory would make `--resume` lose the session.
    root = find_root(Path.cwd())
    return Project(root, root)


def _user_config() -> Path:
    return global_config_dir() / "config.json"


def _load(project: Project):
    return load_config(project.config_file, _user_config())


def _confirm(question: str) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        return input("%s [y/N] " % question).strip().lower() in ("y", "yes", "s", "si", "sí")
    except EOFError:
        return False


# ------------------------------------------------------------------------ run


def cmd_run(args: argparse.Namespace) -> int:
    from .supervisor import Supervisor
    from .terminal import make_terminal

    if os.environ.get("COPICLAUDE") == "1":
        _err(t("nested"))
        return 2
    project = _project()
    if is_risky_root(project.root) and not args.yes:
        question = t("risky_root", root=project.root)
        if not sys.stdin.isatty():
            _err(t("risky_root_refused", root=project.root))
            return 2
        if not _confirm(question):
            return 1
    try:
        config, _found = _load(project)
    except ConfigError as exc:
        _err(t("config_error", error=exc))
        return 2
    state = load_state(project.state_file)
    for text in config.warnings + state.warnings:
        _err(t("warning", text=text))
    if args.agent:
        state.current_agent = args.agent
    terminal = make_terminal()
    if not terminal.is_tty():
        _err(t("need_tty"))
        return 2
    legacy = handoff.find_legacy_blocks(project.root)
    if legacy:
        _err(t("legacy_found", files=", ".join(p.name for p in legacy)))
    try:
        with ProjectLock(project):
            supervisor = Supervisor(project, config, state, terminal, start_agent=args.agent)

            def stop(signum, frame):  # noqa: ANN001
                supervisor.stop_requested = True

            for name in ("SIGTERM", "SIGHUP", "SIGBREAK"):
                if hasattr(signal, name):
                    signal.signal(getattr(signal, name), stop)
            return supervisor.run()
    except LockError as exc:
        _err(t("already_running", pid=exc.pid) if exc.pid else t("already_running_unknown"))
        return 1


# --------------------------------------------------------------------- status


def cmd_status(args: argparse.Namespace) -> int:
    project = _project()
    try:
        config, found = _load(project)
    except ConfigError as exc:
        _err(t("config_error", error=exc))
        return 2
    state = load_state(project.state_file)
    info = {
        "version": __version__,
        "project": str(project.root),
        "state_dir": str(project.state_dir),
        "running": ProjectLock.is_held(project) if project.state_dir.exists() else False,
        "config_layers": found,
        "config": config.to_dict(),
        "state": state.to_dict(),
        "agents": {
            name: (AGENT_IMPLS[name].resolve(config.agent(name)) or [None])[0] for name in AGENTS
        },
    }
    if args.json:
        print(json.dumps(info, indent=2))
        return 0
    print(t("status_title", version=__version__))
    print("  project:   %s" % info["project"])
    print("  running:   %s" % ("yes" if info["running"] else "no"))
    print("  agent:     %s (default %s)" % (state.current_agent or "-", config.default_agent))
    print("  switches:  %d" % state.switch_count)
    print("  auto:      %s, key %s" % (config.auto_switch, config.switch_key))
    for name in AGENTS:
        print("  %-9s  %s" % (name + ":", info["agents"][name] or t("doctor_missing")))
    return 0


# --------------------------------------------------------------------- config


def _ask(prompt: str, default: str, valid) -> str:  # noqa: ANN001
    while True:
        suffix = " [%s]" % default if default else ""
        value = input("%s%s: " % (prompt, suffix)).strip() or default
        if valid(value):
            return value
        print(t("wizard_invalid"))


def _key_ok(value: str) -> bool:
    try:
        parse_key(value)
    except ValueError:
        return False
    return True


def cmd_config(args: argparse.Namespace) -> int:
    project = _project()
    target = _user_config() if args.user else project.config_file
    if args.show:
        try:
            config, found = _load(project)
        except ConfigError as exc:
            _err(t("config_error", error=exc))
            return 2
        print(json.dumps(config.to_dict(), indent=2))
        print("# layers: %s" % json.dumps(found), file=sys.stderr)
        return 0
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        _err(t("wizard_no_tty", path=target))
        return 2
    try:
        config, _found = _load(project)
    except ConfigError:
        config = Config()
    print(t("wizard_title", where=target))
    config.default_agent = _ask(t("wizard_default_agent"), config.default_agent, lambda v: v in AGENTS)
    for name in AGENTS:
        cfg = config.agent(name)
        cfg.model = _ask(t("wizard_model", agent=name), cfg.model, lambda v: True)
        cfg.effort = _ask(
            t("wizard_effort", agent=name, choices="/".join(EFFORTS[name])),
            cfg.effort,
            lambda v, n=name: v == "" or v in EFFORTS[n],
        )
    config.auto_switch = _ask(t("wizard_auto"), config.auto_switch, lambda v: v in AUTO_SWITCH_MODES)
    config.switch_key = _ask(t("wizard_key"), config.switch_key, _key_ok)
    if not args.user:
        project.ensure()
    save_config_file(target, config)
    print(t("wizard_saved", path=target))
    return 0


# --------------------------------------------------------- switch / clean / doctor


def cmd_switch(args: argparse.Namespace) -> int:
    project = _project()
    if not (project.state_dir.exists() and ProjectLock.is_held(project)):
        _err(t("switch_no_instance"))
        return 1
    project.request_file.write_text("1\n")
    print(t("switch_requested"))
    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    project = _project()
    changed = handoff.remove_legacy_blocks(project.root)
    if not changed:
        print(t("legacy_none"))
    for path in changed:
        print(t("legacy_cleaned", path=path))
    return 0


def _version_of(command: List[str]) -> str:
    try:
        proc = subprocess.run(
            command + ["--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            universal_newlines=True,
        )
    except (OSError, subprocess.SubprocessError):
        return "?"
    lines = (proc.stdout or "").strip().splitlines()
    return lines[0] if lines else "?"


def cmd_doctor(args: argparse.Namespace) -> int:
    project = _project()
    problems = 0

    def row(label: str, value: str, ok: bool = True) -> None:
        nonlocal problems
        problems += 0 if ok else 1
        print("  [%s] %-16s %s" % ("ok" if ok else "!!", label, value))

    print("copiclaude %s  (%s)" % (__version__, "es" if language() == "es" else "en"))
    row("python", "%s on %s %s" % (platform.python_version(), platform.system(), platform.machine()))
    row("project", str(project.root))
    from .terminal import make_terminal

    row("terminal", "interactive" if make_terminal().is_tty() else "not a TTY (needed to run)", make_terminal().is_tty())
    if os.name == "nt":
        try:
            import winpty  # noqa: F401

            row("pywinpty", "installed")
        except ImportError:
            row("pywinpty", "missing: pip install pywinpty", False)
    try:
        config, found = _load(project)
        row("config", "valid (user: %s, project: %s)" % (found["user"], found["project"]))
        for text in config.warnings:
            row("config warning", text, False)
    except ConfigError as exc:
        row("config", str(exc), False)
        config = Config()
    for name in AGENTS:
        head = AGENT_IMPLS[name].resolve(config.agent(name))
        row(name, ("%s  (%s)" % (head[0], _version_of(head))) if head else "not found in PATH", head is not None)
    row("git", shutil.which("git") or "not found (handoffs will omit repository state)", shutil.which("git") is not None)
    legacy = handoff.find_legacy_blocks(project.root)
    row("legacy blocks", ", ".join(p.name for p in legacy) + " (run: copiclaude clean)" if legacy else "none", not legacy)
    stale = read_json_file(project.state_file) if project.state_file.exists() else None
    row("state", "present" if stale is not None else "none yet")
    return 1 if problems else 0


# ----------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="copiclaude",
        description="Run Claude Code or GitHub Copilot CLI in this project and switch between them, "
        "carrying context across when one runs out of quota.",
    )
    parser.add_argument("--version", action="version", version="copiclaude " + __version__)
    parser.add_argument("--agent", choices=AGENTS, help="agent to start with (default: the one used last)")
    parser.add_argument("-y", "--yes", action="store_true", help="do not ask before using a home directory as the project")
    sub = parser.add_subparsers(dest="command", metavar="command")
    status = sub.add_parser("status", help="show the project's configuration and state")
    status.add_argument("--json", action="store_true")
    config = sub.add_parser("config", help="interactive setup (or --show)")
    config.add_argument("--user", action="store_true", help="write the user-level config instead of the project's")
    config.add_argument("--show", action="store_true", help="print the effective configuration")
    sub.add_parser("switch", help="ask the copiclaude running in this project to switch agent")
    sub.add_parser("clean", help="remove the handoff block older versions wrote into CLAUDE.md / AGENTS.md")
    sub.add_parser("doctor", help="check the installation")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        None: cmd_run,
        "status": cmd_status,
        "config": cmd_config,
        "switch": cmd_switch,
        "clean": cmd_clean,
        "doctor": cmd_doctor,
    }
    try:
        return handlers[args.command](args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
