"""Where a project's copiclaude state lives, and the lock that guards it."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from .store import atomic_write

STATE_DIRNAME = ".copiclaude"
MAX_LOG_BYTES = 512 * 1024


def find_root(cwd: Path) -> Path:
    """Nearest ancestor that is a git checkout or already has copiclaude state.

    Anchoring to the project root (instead of the current directory) keeps one
    state per project no matter which subdirectory the tool is started from.
    """
    for candidate in [cwd] + list(cwd.parents):
        if (candidate / STATE_DIRNAME).is_dir() or (candidate / ".git").exists():
            return candidate
    return cwd


def is_risky_root(root: Path) -> bool:
    """A home directory or filesystem root is almost never "the project"."""
    if (root / STATE_DIRNAME).is_dir():
        return False
    try:
        return root == Path.home() or root == root.parent
    except RuntimeError:  # no resolvable home
        return root == root.parent


class Project:
    def __init__(self, root: Path, cwd: Optional[Path] = None) -> None:
        self.root = root
        self.cwd = cwd or root
        self.state_dir = root / STATE_DIRNAME
        self.config_file = self.state_dir / "config.json"
        self.state_file = self.state_dir / "state.json"
        self.handoff_file = self.state_dir / "HANDOFF.md"
        self.handoffs_dir = self.state_dir / "handoffs"
        self.log_file = self.state_dir / "session.log"
        self.lock_file = self.state_dir / "lock"
        self.pid_file = self.state_dir / "lock.pid"
        self.request_file = self.state_dir / "switch.request"

    def ensure(self) -> None:
        """Create the state directory, ignored by git from the inside.

        The inner ``.gitignore`` means nothing outside ``.copiclaude/`` is
        touched and the handoff (which quotes recent prompts) is never committed
        by accident.
        """
        self.state_dir.mkdir(parents=True, exist_ok=True)
        marker = self.state_dir / ".gitignore"
        if not marker.exists():
            atomic_write(marker, "*\n")

    def log(self, message: str) -> None:
        try:
            self.ensure()
            if self.log_file.exists() and self.log_file.stat().st_size > MAX_LOG_BYTES:
                os.replace(self.log_file, self.log_file.with_name("session.log.1"))
            with open(str(self.log_file), "a", encoding="utf-8") as handle:
                handle.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
        except OSError:
            pass  # logging must never break the session


class LockError(Exception):
    def __init__(self, pid: Optional[int]) -> None:
        super().__init__("another copiclaude is running in this project")
        self.pid = pid


class ProjectLock:
    """Advisory lock released by the OS if the process dies (no stale locks)."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self._handle = None

    def _holder(self) -> Optional[int]:
        try:
            return int(self.project.pid_file.read_text().strip())
        except (OSError, ValueError):
            return None

    def acquire(self) -> None:
        self.project.ensure()
        handle = open(str(self.project.lock_file), "a+b")
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise LockError(self._holder())
        self._handle = handle
        try:
            atomic_write(self.project.pid_file, "%d\n" % os.getpid())
        except OSError:
            pass

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            self._handle.close()
        except OSError:
            pass
        self._handle = None
        try:
            self.project.pid_file.unlink()
        except OSError:
            pass

    def __enter__(self) -> "ProjectLock":
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()

    @staticmethod
    def is_held(project: Project) -> bool:
        probe = ProjectLock(project)
        try:
            probe.acquire()
        except LockError:
            return True
        probe.release()
        return False
