# CopiClaude

Run [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) or
[GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli)
in the same project and **switch between them without re-explaining anything**.
When one runs out of quota, press one key: the other starts in the same folder
with a handoff note (what you asked, what the last reply was, what changed in
git), and each assistant keeps its own session so you can switch back later.

- Works on **Linux, macOS and Windows**.
- The agents run exactly as they normally do, in your terminal. CopiClaude only
  forwards keystrokes and output, apart from one key that means "switch".
- No network access, no telemetry, no accounts. It never sees your credentials.
- It does **not** edit your `CLAUDE.md`, `AGENTS.md` or `.gitignore`.

> Unofficial community tool. Not affiliated with Anthropic or GitHub.

## Install

You need Python 3.9+ and at least one of the two CLIs installed and signed in.

```bash
pipx install git+https://github.com/AngelGianpieer/copiclaude
# or:  pip install --user git+https://github.com/AngelGianpieer/copiclaude
```

On Windows the ConPTY backend (`pywinpty`) is installed automatically. Use
Windows Terminal or any console with virtual-terminal support.

Check the setup with `copiclaude doctor`.

## Use

```bash
cd my-project
copiclaude                # starts the agent you used last (Claude Code the first time)
copiclaude --agent copilot
```

Work normally. To switch, press **Ctrl+K**, or run `copiclaude switch` from
another terminal. CopiClaude stops the current agent, writes
`.copiclaude/HANDOFF.md`, and starts the other one with the instruction to read
it. Each agent resumes its own previous conversation when you come back to it.

### When a usage limit is hit

CopiClaude watches for it in two ways: the agent's own session log (structured
errors, reliable) and the text on screen (a hint). It then **asks** rather than
acting, because a phrase like "rate limit" can also appear when an agent is just
talking about rate limits:

```
 Claude Code looks out of quota. ctrl+k: switch to GitHub Copilot CLI - any other key: ignore
```

Press the switch key to accept; any other key dismisses it (and is still
delivered to the agent). Set `auto_switch` to `always` to skip the question or
`off` to disable detection. If the other agent hit its limit recently,
CopiClaude will not propose bouncing back to it.

### Commands

| Command | What it does |
| --- | --- |
| `copiclaude` | Run the agent in the current project |
| `copiclaude switch` | Ask the running copiclaude to switch agent |
| `copiclaude status [--json]` | Show configuration, state and detected CLIs |
| `copiclaude config [--user]` | Interactive setup (`--show` prints the effective config) |
| `copiclaude doctor` | Check Python, terminal, both CLIs, git and config |
| `copiclaude clean` | Remove the block that 0.1 wrote into `CLAUDE.md`/`AGENTS.md` |

## Configuration

Layered, later wins: built-in defaults, the user file (`~/.config/copiclaude/config.json`,
`%APPDATA%\copiclaude\config.json` on Windows), then the project file
`.copiclaude/config.json`.

```json
{
  "default_agent": "claude",
  "auto_switch": "ask",
  "auto_continue": false,
  "switch_key": "ctrl+k",
  "claude":  { "command": "claude",  "model": "sonnet", "effort": "medium", "args": [] },
  "copilot": { "command": "copilot", "model": "auto",   "effort": "high",   "args": [] }
}
```

| Key | Values | Meaning |
| --- | --- | --- |
| `default_agent` | `claude`, `copilot` | Agent used the first time |
| `auto_switch` | `ask`, `always`, `off` | What to do when a limit is detected |
| `auto_continue` | `true`, `false` | `false`: the new agent summarises what it understood and waits for you. `true`: it carries on with the next steps |
| `switch_key` | `ctrl+<letter>`, `ctrl+]`, `ctrl+\`, `ctrl+^`, `ctrl+_` | Key that switches. Ctrl+K also means "delete to end of line" in some prompts; change it if you use that |
| `<agent>.command` | string or list | Executable (or wrapper) to launch |
| `<agent>.model` | string | Passed as `--model` |
| `<agent>.effort` | Claude: `low`…`max`; Copilot: `none`…`max` | Passed as `--effort` / `--reasoning-effort` |
| `<agent>.args` | list of strings | Extra flags always passed to that agent |

Tip: with Copilot's `model: "auto"`, leave `effort` empty. Auto may route to a model that
rejects `--reasoning-effort` (`invalid_reasoning_effort`, HTTP 400), and the turn fails.

Environment: `COPICLAUDE_LANG=en|es` picks the message language.

## What is stored, and where

Everything is under `.copiclaude/` in the project root (the nearest folder with a
`.git` or a `.copiclaude`). It contains its own `.gitignore` that ignores itself,
so it is never committed by accident.

| File | Content |
| --- | --- |
| `state.json` | current agent, session ids, switch count |
| `HANDOFF.md`, `handoffs/` | the latest handoff and the last 10 |
| `config.json` | your project configuration |
| `session.log` | launches, switches, exits (no conversation content) |

The handoff quotes your last few prompts and the agent's last reply, read from
the agent's own session file on your machine. It stays local and is only read by
the next agent, which is its purpose; don't share `.copiclaude/` if your prompts
are sensitive. Agents always start in the project root.

## How it differs from the 0.1 script

The first version asked the agent to write its own summary by typing into its
screen. That is unreliable when an agent has just hit its limit, and pressing
Enter into a live TUI can land on a permission dialog and approve something. 0.2
builds the handoff itself from git and the session file and never types into an
agent, kills the whole process tree on a switch, restores terminal modes the
agent left on, and is cross-platform. See [CHANGELOG.md](CHANGELOG.md) and
[docs/architecture.md](docs/architecture.md).

## Known limits

- Session files and quota messages are the CLIs' own formats and can change.
  Detection therefore fails safe: worst case you press the switch key yourself.
- One agent runs at a time; this is a switcher, not a parallel orchestrator.
- Windows is covered by automated tests against stand-in agents; real-agent
  behaviour on Windows depends on `pywinpty`/ConPTY. Please open an issue with the
  output of `copiclaude doctor` if something is off.

## Development

```bash
pip install -e ".[test]"
pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Licensed under MIT.
