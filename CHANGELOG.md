# Changelog

## 0.2.0

Rewritten in Python as an installable package; runs on Linux, macOS and Windows.

### Fixed
- The fallback handoff no longer dumps raw terminal output (with escape codes and old
  prompts) into `CLAUDE.md`/`AGENTS.md`, where the next agent read it as instructions.
  The handoff is now built from git and the agent's session file and lives only in
  `.copiclaude/`. `copiclaude clean` removes blocks written by 0.1.
- Usage-limit detection no longer fires on any mention of "rate limit": it needs a
  specific message, then silence, then (by default) your confirmation. It reads the
  agent's structured session errors first and copes with TUI repaints that use cursor
  moves instead of spaces.
- Never types into the agent any more. Asking it to write a summary could press Enter
  on a permission dialog; the agent is stopped with signals instead of `/exit`.
- Stopping an agent kills its whole process group (tools, MCP servers), not just the
  top process, and restores the terminal modes it left on (mouse, bracketed paste,
  kitty keyboard protocol, alternate screen, cursor).
- `--resume` on a session that never received a message (Claude: "No conversation
  found") is avoided by checking the session exists, with a retry as a safety net.
- Refuses to switch to an agent that is not installed instead of killing the current one.
- Agents are started with SIGPIPE restored and the terminal size set before launch.
- Corrupt `state.json` is set aside instead of silently reset; a corrupt `config.json`
  is reported and never overwritten. Writes are atomic.
- Two copiclaude instances in one project are refused (OS-level lock, no stale locks).
- State is anchored to the project root, not the current directory; running in a home
  directory asks first.
- The switch key is recognised in its legacy, kitty-protocol and modifyOtherKeys forms
  (including key-release events and lock-key modifiers) and never inside a paste.
- Exit codes of the agent are propagated (128+N for signals).

### Added
- Windows and macOS support (ConPTY through `pywinpty` on Windows).
- `copiclaude switch`, `status --json`, `doctor`, `clean`, `config --show/--user`.
- Configurable switch key, `auto_switch` (`ask`/`always`/`off`), `auto_continue`,
  per-agent `command`/`args`, user-level config, English and Spanish messages.
- End-to-end tests against stand-in agents on all three platforms.

### Changed
- Handoff is delivered as the first message to the next agent instead of by editing
  project files. Config files from 0.1 keep working; `state.json` is migrated.

## 0.1.0

Initial launcher.
