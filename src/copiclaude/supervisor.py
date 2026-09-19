"""The run loop: one agent at a time in a transparent pty, switching on demand.

Everything the user types goes to the agent, everything the agent draws goes to
the terminal, except for the switch key. The loop also watches for quota
problems (the agent's own session file first, screen text as a hint) and, when
one is seen, *asks* before switching unless the config says otherwise.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple

from . import handoff
from .agents import AGENT_IMPLS, SignalWatcher, new_session_id
from .detect import QuotaDetector
from .i18n import t
from .keys import InputFilter, is_terminal_noise, parse_key
from .project import Project
from .ptyproc import BackendError, spawn_pty
from .store import OTHER, Config, State, is_uuid, save_state
from .terminal import ModeTracker, Terminal


@dataclass
class Timing:
    tick: float = 0.1  # loop granularity
    quiet: float = 1.5  # silence required after a limit message on screen
    ask_seconds: float = 15.0  # how long the "switch?" banner waits
    cooldown: float = 120.0  # after ignoring a proposal, don't ask again for this long
    signal_poll: float = 1.0  # how often the session file is checked
    term_grace: float = 3.0  # SIGTERM -> SIGKILL
    fast_fail: float = 8.0  # an exit sooner than this counts as "failed to start"
    launch_guard: float = 1.0  # ignore the switch key right after a launch
    quota_memory: float = 3600.0  # how long an agent stays "exhausted" after a switch for quota
    pending_after: float = 3.0  # a launch counts as delivered after this long


class Pump:
    """Reader threads feeding one queue, so the loop has a single wait point."""

    def __init__(self) -> None:
        self.queue: "queue.Queue[Tuple[Any, Optional[bytes]]]" = queue.Queue()

    def start(self, tag: Any, read: Callable[[], bytes]) -> None:
        def run() -> None:
            while True:
                try:
                    data = read()
                except Exception:  # noqa: BLE001 - a dying source must end the stream, not the thread noisily
                    data = b""
                self.queue.put((tag, data or None))
                if not data:
                    return

        threading.Thread(target=run, name="copiclaude-%s" % (tag,), daemon=True).start()

    def get(self, timeout: float) -> Optional[Tuple[Any, Optional[bytes]]]:
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None


@dataclass
class Outcome:
    kind: str  # "exit" | "switch"
    code: int = 0
    reason: str = ""  # for "switch": manual | quota | request
    detail: str = ""
    fast_fail: bool = False
    user_input: bool = False


def _exit_code(code: int) -> int:
    return code if code >= 0 else 128 - code  # killed by signal N -> 128+N, like a shell


class Supervisor:
    def __init__(
        self,
        project: Project,
        config: Config,
        state: State,
        terminal: Terminal,
        spawn: Callable[..., Any] = spawn_pty,
        timing: Optional[Timing] = None,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        start_agent: Optional[str] = None,
    ) -> None:
        self.project = project
        self.config = config
        self.state = state
        self.terminal = terminal
        self.spawn = spawn
        self.timing = timing or Timing()
        self.clock = clock
        self.wall = wall
        self.start_agent = start_agent
        self.key = parse_key(config.switch_key)
        self.pump = Pump()
        self.stop_requested = False
        self._generation = 0

    # ------------------------------------------------------------------ helpers
    def _say(self, message: str) -> None:
        self.terminal.write_text("\r\n[copiclaude] %s\r\n" % message)

    def _save(self) -> None:
        try:
            save_state(self.project.state_file, self.state)
        except OSError as exc:
            self.project.log("could not save state: %s" % exc)

    def _banner(self, text: str) -> None:
        rows, cols = self.terminal.size()
        text = (" " + text)[: max(1, cols - 1)]
        self.terminal.write(("\x1b7\x1b[%d;1H\x1b[2K\x1b[7m%s\x1b[0m\x1b8" % (rows, text)).encode("utf-8"))

    def _clear_banner(self, proc: Any) -> None:
        rows, cols = self.terminal.size()
        self.terminal.write(("\x1b7\x1b[%d;1H\x1b[2K\x1b8" % rows).encode("utf-8"))
        # The banner overwrote a row of the agent's screen; a resize round-trip makes
        # full-screen agents repaint it.
        if cols > 1:
            proc.resize(rows, cols - 1)
            time.sleep(0.03)
            proc.resize(rows, cols)

    def _can_switch_to(self, target: str) -> bool:
        return AGENT_IMPLS[target].resolve(self.config.agent(target)) is not None

    def _recently_exhausted(self, agent: str) -> Optional[int]:
        stamp = self.state.last_quota_at.get(agent)
        if stamp is None:
            return None
        age = self.wall() - stamp
        return int(age // 60) if 0 <= age < self.timing.quota_memory else None

    # --------------------------------------------------------------------- run
    def run(self) -> int:
        agent = self.start_agent or self.state.current_agent or self.config.default_agent
        prompt = handoff.build_prompt(self.project, self.config.auto_continue) if self.state.handoff_pending else None
        self.state.current_agent = agent
        self._save()
        self.terminal.enter()
        self.pump.start("stdin", self.terminal.read)
        try:
            self._say(t("starting", agent=AGENT_IMPLS[agent].label, key=self.config.switch_key))
            self.project.log("start agent=%s" % agent)
            while True:
                outcome = self._run_agent(agent, prompt)
                prompt = None
                if outcome.kind == "exit":
                    return outcome.code
                target = OTHER[agent]
                prompt = self._switch(agent, target, outcome)
                agent = target
        finally:
            self.terminal.leave()

    def _run_agent(self, agent: str, prompt: Optional[str]) -> Outcome:
        spec = AGENT_IMPLS[agent]
        cfg = self.config.agent(agent)
        head = spec.resolve(cfg)
        if head is None:
            self._say(t("not_installed", command=cfg.command[0], agent=spec.label, name=agent))
            return Outcome("exit", 127)
        session_id = self.state.sessions.get(agent)
        if not is_uuid(session_id):
            session_id = new_session_id()
            self.state.sessions[agent] = session_id
            self._save()
        resume = spec.session_exists(session_id)
        tried = set()
        while True:
            argv = spec.build_argv(cfg, head, session_id, resume, prompt)
            tried.add(tuple(argv))
            outcome = self._launch(agent, argv, session_id)
            if outcome.kind == "exit" and outcome.fast_fail and not outcome.user_input and outcome.code != 0:
                # A session that was assumed new (or existing) may be the other way round
                # (e.g. the CLI keeps sessions somewhere unexpected): try the other form once.
                alternative = spec.build_argv(cfg, head, session_id, not resume, prompt)
                if tuple(alternative) not in tried:
                    resume = not resume
                    self._say(t("retrying", agent=spec.label, mode=t("mode_resume" if resume else "mode_new")))
                    continue
            return outcome

    def _launch(self, agent: str, argv: list, session_id: str) -> Outcome:
        spec = AGENT_IMPLS[agent]
        timing = self.timing
        rows, cols = self.terminal.size()
        env = dict(os.environ)
        env["COPICLAUDE"] = "1"
        env["COPICLAUDE_AGENT"] = agent
        if os.name != "nt":
            env.setdefault("TERM", "xterm-256color")
        try:
            proc = self.spawn(argv, str(self.project.cwd), env, rows, cols)
        except (BackendError, OSError) as exc:
            self._say(t("backend_error", error=exc))
            return Outcome("exit", 127)
        self.project.log("launch agent=%s argv=%s" % (agent, " ".join(argv[:1] + [a if len(a) < 60 else a[:57] + "..." for a in argv[1:]])))
        self._generation += 1
        tag = ("out", self._generation)
        self.pump.start(tag, proc.read)

        detector = QuotaDetector(spec.quota_patterns, quiet=timing.quiet)
        watcher = SignalWatcher(spec, session_id)
        modes = ModeTracker()
        keys = InputFilter(self.key)
        target = OTHER[agent]

        started = self.clock()
        user_input = False
        asking_until: Optional[float] = None
        asking_reason = ""
        asking_drawn = 0.0
        note_until: Optional[float] = None
        cooldown_until = 0.0
        last_size = (rows, cols)
        last_poll = 0.0
        eof_at: Optional[float] = None
        exited_at: Optional[float] = None
        pending_cleared = not self.state.handoff_pending

        def finish(outcome: Outcome, terminate: bool) -> Outcome:
            if terminate:
                proc.terminate(timing.term_grace)
            proc.close()
            self.terminal.write(modes.reset_bytes() + b"\x1b[0m")
            outcome.user_input = user_input
            return outcome

        def dismiss(now: float) -> None:
            nonlocal asking_until, cooldown_until
            asking_until = None
            cooldown_until = now + timing.cooldown
            detector.reset()
            self._clear_banner(proc)

        while True:
            item = self.pump.get(timing.tick)
            now = self.clock()
            code = proc.poll()

            if item is not None:
                source, data = item
                if source == "stdin":
                    if data is None:
                        self._say(t("terminal_closed", agent=spec.label))
                        return finish(Outcome("exit", 129), True)
                    forward, pressed = keys.feed(data)
                    if pressed and now - started >= timing.launch_guard and code is None:
                        if asking_until is not None:
                            return finish(Outcome("switch", reason="quota", detail=asking_reason), True)
                        if self._can_switch_to(target):
                            return finish(Outcome("switch", reason="manual"), True)
                        self._banner(t("banner_cannot_switch", target=AGENT_IMPLS[target].label))
                        note_until = now + 4.0
                    if forward and code is None:
                        if not is_terminal_noise(forward):
                            user_input = True
                            if asking_until is not None:
                                dismiss(now)
                        proc.write(forward)
                elif source == tag:
                    if data is None:
                        eof_at = now
                    else:
                        modes.feed(data)
                        self.terminal.write(data)
                        detector.feed(data, now)
                # output from an earlier agent's reader thread is dropped

            # ---- has the agent ended? (wait for its last output, but not forever)
            if code is not None and exited_at is None:
                exited_at = now
            if eof_at is not None or exited_at is not None:
                done = (eof_at is not None and code is not None) or (
                    exited_at is not None and now - exited_at >= 1.0
                ) or (eof_at is not None and now - eof_at > 2.0)
                if done:
                    final = code if code is not None else 0
                    if code is None:
                        proc.terminate(timing.term_grace)
                        final = proc.poll() or 0
                    outcome = Outcome("exit", _exit_code(final), fast_fail=now - started < timing.fast_fail)
                    if outcome.code != 0:
                        self._say(t("exited_error", agent=spec.label, code=outcome.code))
                    self.project.log("agent=%s exited code=%s" % (agent, outcome.code))
                    return finish(outcome, False)
                continue

            if self.stop_requested:
                self._say(t("signal_stop", agent=spec.label))
                return finish(Outcome("exit", 143), True)

            # ---- periodic work
            size = self.terminal.size()
            if size != last_size:
                last_size = size
                proc.resize(*size)

            if not pending_cleared and now - started >= timing.pending_after:
                pending_cleared = True
                self.state.handoff_pending = False
                self._save()

            if note_until is not None and now >= note_until:
                note_until = None
                self._clear_banner(proc)

            if asking_until is not None:
                if now >= asking_until:
                    dismiss(now)
                elif now - asking_drawn >= 1.0:
                    asking_drawn = now
                    self._banner(self._ask_text(agent, target))

            signal_hit = None
            if now - last_poll >= timing.signal_poll:
                last_poll = now
                if self._take_switch_request():
                    if self._can_switch_to(target):
                        return finish(Outcome("switch", reason="request"), True)
                    self._banner(t("banner_cannot_switch", target=AGENT_IMPLS[target].label))
                    note_until = now + 4.0
                signal_hit = watcher.poll()
            found = signal_hit or detector.poll(now)
            if found and asking_until is None and now >= cooldown_until and self.config.auto_switch != "off":
                minutes = self._recently_exhausted(target)
                if minutes is not None:
                    self._banner(t("banner_other_exhausted", agent=spec.label, other=AGENT_IMPLS[target].label, minutes=minutes))
                    note_until = now + 6.0
                    cooldown_until = now + timing.cooldown
                elif not self._can_switch_to(target):
                    cooldown_until = now + timing.cooldown
                elif self.config.auto_switch == "always":
                    self.project.log("auto switch (%s): %s" % (agent, found))
                    return finish(Outcome("switch", reason="quota", detail=found), True)
                else:
                    self.project.log("limit suspected (%s): %s" % (agent, found))
                    asking_until = now + timing.ask_seconds
                    asking_reason = found
                    asking_drawn = now
                    self._banner(self._ask_text(agent, target))

    def _take_switch_request(self) -> bool:
        """True (once) if `copiclaude switch` left a request file."""
        try:
            self.project.request_file.unlink()
        except OSError:
            return False
        return True

    def _ask_text(self, agent: str, target: str) -> str:
        return t(
            "banner_limit",
            agent=AGENT_IMPLS[agent].label,
            key=self.config.switch_key,
            target=AGENT_IMPLS[target].label,
        )

    # ------------------------------------------------------------------ switch
    def _switch(self, source: str, target: str, outcome: Outcome) -> str:
        self._say(t("switching", source=source, target=target, reason=t("reason_" + outcome.reason)))
        session_id = self.state.sessions.get(source, "")
        try:
            ctx = AGENT_IMPLS[source].read_context(session_id)
            text = handoff.render(self.project, source, target, outcome.reason, ctx, self.wall())
        except Exception as exc:  # noqa: BLE001 - a handoff problem must never strand the user
            self.project.log("handoff render failed: %s" % exc)
            from .agents import Context

            text = handoff.render(self.project, source, target, outcome.reason, Context(), self.wall())
        try:
            handoff.write(self.project, text, source, target)
        except OSError as exc:
            self.project.log("handoff write failed: %s" % exc)
        self.state.current_agent = target
        self.state.switch_count += 1
        self.state.handoff_pending = True
        if outcome.reason == "quota":
            self.state.last_quota_at[source] = self.wall()
        self._save()
        self.project.log("switch %s -> %s reason=%s count=%d" % (source, target, outcome.reason, self.state.switch_count))
        self._say(t("handoff_written", path=self._relative_handoff(), target=AGENT_IMPLS[target].label))
        return handoff.build_prompt(self.project, self.config.auto_continue)

    def _relative_handoff(self) -> str:
        try:
            return os.path.relpath(str(self.project.handoff_file), str(self.project.cwd))
        except ValueError:
            return str(self.project.handoff_file)
