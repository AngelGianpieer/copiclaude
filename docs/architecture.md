# Architecture

CopiClaude is a supervisor that owns the terminal, runs one agent at a time inside
a pseudo-terminal, and can replace it with the other agent.

```
 your terminal ──► Terminal (raw mode) ──► InputFilter ──► agent's pty ──► claude | copilot
       ▲                                        │                │
       │                                   switch key           │ output
       └──────────── Terminal.write ◄───────────┴── QuotaDetector, ModeTracker
```

## Modules (`src/copiclaude/`)

| Module | Responsibility |
| --- | --- |
| `cli.py` | Argument parsing and the subcommands (`run`, `status`, `config`, `switch`, `clean`, `doctor`). |
| `supervisor.py` | The run loop, the "limit detected" prompt, switching, retry when a session form is refused. |
| `ptyproc.py` | `PosixPty` (`pty.fork`) and `WindowsPty` (`pywinpty`/ConPTY) behind one small interface. |
| `terminal.py` | Raw mode and VT setup per OS, `ModeTracker` and the escape sequences that undo what a killed agent left on. |
| `keys.py` | Parses the switch key and removes it from the input stream (legacy byte, kitty CSI-u, modifyOtherKeys; skips bracketed paste). |
| `detect.py` | Terminal bytes to text (cursor moves become spaces) and the quiet-after-match limit detector. |
| `agents.py` | Per-agent argv, session lookup, session-file reading (recent prompts, last reply, structured quota errors). |
| `handoff.py` | Builds `HANDOFF.md` from git and the session file; builds the first message for the next agent; cleans 0.1 blocks. |
| `store.py` | Layered config with validation, state with migration, atomic writes. |
| `project.py` | Project root discovery, the self-ignoring `.copiclaude/`, log, OS-level lock. |
| `i18n.py` | English/Spanish messages. |

## Decisions worth knowing

**Threads and one queue.** One reader thread for the user's terminal (for the whole
run) and one per agent process feed a single `queue.Queue`. The loop waits on it with
a 100 ms tick, so the same code runs on POSIX and Windows and can be tested with
stand-ins. Output from a previous agent's thread is dropped by tagging each launch.

**Never type into an agent.** The handoff is produced by copiclaude. Writing a request
into a live TUI can land on a permission prompt (Enter approves it), and an agent that
just hit its quota often cannot answer anyway. Agents are stopped with SIGTERM to the
process group, then SIGKILL after a grace period (`terminate()` on Windows).

**Detection is a hint, switching is a decision.** Two signals: (1) structured errors
appended to the agent's own session file after launch (API-error records for Claude,
`*failure`/`*failed` events for Copilot, HTTP 429), and (2) phrases on screen. A screen
phrase only counts after the agent has been silent for 1.5 s, and after either signal
the user is asked (`auto_switch=ask`). Ignoring the prompt starts a 2-minute cooldown.
An agent that hit a limit in the last hour is not proposed as a target.

**Session handling.** Each agent has its own session id in `state.json`. A session that
has no file on disk yet is started with `--session-id`, otherwise resumed. If a launch
exits within 8 s with an error and the user typed nothing, the other form is tried once.
Agents start in the project root because Claude Code keys sessions by directory.

**Handoff delivery.** As the first message of the next agent (`claude "..."` /
`copilot -i "..."`), pointing at `.copiclaude/HANDOFF.md`. The text uses only characters
that survive every command line (including `cmd.exe` shims). Nothing in the user's
project files is touched; `.copiclaude/` ignores itself with an inner `.gitignore`.

**Terminal hygiene.** Anything that stops an agent also writes reset sequences: kitty
keyboard pop, modifyOtherKeys off, bracketed paste, focus and mouse reporting, cursor
visible, and leaves the alternate screen only if the agent had entered it.

**Fail safe.** Every reader of another tool's files degrades to "not found"; a failed
handoff render still completes the switch with a minimal note; logging never raises.

## Testing

`tests/` has unit tests for each module and `test_integration.py`, which runs the real
copiclaude in a real pseudo-terminal against `tests/fake_agent.py`, using copiclaude's
own pty layer as the harness, so the same tests exercise ConPTY on Windows in CI.
