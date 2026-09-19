"""Run a program inside a pseudo-terminal, on POSIX (pty) and Windows (ConPTY).

Both classes share one small interface (duck-typed):

    read() -> bytes        block for output; b'' when the program is gone
    write(bytes)           send input
    resize(rows, cols)
    poll() -> Optional[int]   exit code, or None while running
    terminate(grace)       stop the program and everything it started
    close()
"""

from __future__ import annotations

import errno
import os
import signal
import struct
import time
import warnings
from typing import Dict, List, Optional

from .terminal import write_all


class BackendError(Exception):
    """The pty backend is unavailable or the program could not be started."""


def spawn_pty(argv: List[str], cwd: str, env: Dict[str, str], rows: int, cols: int):
    if os.name == "nt":
        return WindowsPty(argv, cwd, env, rows, cols)
    return PosixPty(argv, cwd, env, rows, cols)


class PosixPty:
    def __init__(self, argv: List[str], cwd: str, env: Dict[str, str], rows: int, cols: int) -> None:
        import fcntl
        import pty
        import termios

        self._status: Optional[int] = None
        self._closed = False
        self._reader_open = True
        with warnings.catch_warnings():
            # os.forkpty in a multi-threaded process warns on 3.12+; the child only
            # runs the few calls below before exec, so it cannot deadlock on our locks.
            warnings.simplefilter("ignore", DeprecationWarning)
            pid, fd = pty.fork()
        if pid == 0:  # child
            try:
                # Python ignores SIGPIPE; programs we launch expect the default.
                signal.signal(signal.SIGPIPE, signal.SIG_DFL)
                fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
                os.chdir(cwd)
                os.execve(argv[0], argv, env)
            except BaseException as exc:  # noqa: BLE001 - must not return into the parent's code
                try:
                    os.write(2, ("copiclaude: cannot start %s: %s\r\n" % (argv[0], exc)).encode())
                finally:
                    os._exit(127)
        self.pid = pid
        self._fd = fd
        self._reader_fd = os.dup(fd)  # private copy for the reader thread (no fd-reuse races)

    def read(self) -> bytes:
        """Runs on the reader thread, which is the sole owner of ``_reader_fd``."""
        if not self._reader_open:
            return b""
        try:
            data = os.read(self._reader_fd, 65536)
        except OSError as exc:
            if exc.errno not in (errno.EIO, errno.EBADF):  # Linux: EIO once the child is gone
                raise
            data = b""
        if not data:  # EOF (macOS returns b"" instead of raising)
            self._reader_open = False
            try:
                os.close(self._reader_fd)
            except OSError:
                pass
        return data

    def write(self, data: bytes) -> None:
        try:
            write_all(self._fd, data)
        except OSError:
            pass

    def resize(self, rows: int, cols: int) -> None:
        import fcntl
        import termios

        try:
            fcntl.ioctl(self._fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

    def poll(self) -> Optional[int]:
        if self._status is None:
            try:
                pid, status = os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                self._status = 0
            else:
                if pid == self.pid:
                    self._status = os.waitstatus_to_exitcode(status)
        return self._status

    def _wait(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.poll() is not None:
                return True
            time.sleep(0.02)
        return self.poll() is not None

    def terminate(self, grace: float) -> None:
        # The child is a session leader, so its pid is also its process-group id:
        # signalling the group reaches the tools and servers it started too.
        for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 2.0)):
            if self.poll() is not None:
                break
            try:
                os.killpg(self.pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
            if self._wait(wait):
                break

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            os.close(self._fd)
        except OSError:
            pass
        # _reader_fd belongs to the reader thread and is closed when its read hits EOF;
        # closing it from here could race with a read still in flight.


class WindowsPty:
    def __init__(self, argv: List[str], cwd: str, env: Dict[str, str], rows: int, cols: int) -> None:
        try:
            from winpty import PtyProcess  # type: ignore[import-not-found]
        except ImportError as exc:
            raise BackendError("the 'pywinpty' package is required on Windows: pip install pywinpty (%s)" % exc)
        try:
            self._proc = PtyProcess.spawn(argv, cwd=cwd, env=env, dimensions=(rows, cols))
        except Exception as exc:  # noqa: BLE001 - pywinpty raises assorted types
            raise BackendError("cannot start %s: %s" % (argv[0], exc))

    def read(self) -> bytes:
        try:
            data = self._proc.read(65536)
        except EOFError:
            return b""
        except OSError:
            return b""
        return data.encode("utf-8", errors="replace") if isinstance(data, str) else bytes(data)

    def write(self, data: bytes) -> None:
        try:
            self._proc.write(data.decode("utf-8", errors="replace"))
        except (OSError, EOFError):
            pass

    def resize(self, rows: int, cols: int) -> None:
        try:
            self._proc.setwinsize(rows, cols)
        except Exception:  # noqa: BLE001
            pass

    def poll(self) -> Optional[int]:
        try:
            if self._proc.isalive():
                return None
        except Exception:  # noqa: BLE001
            pass
        status = getattr(self._proc, "exitstatus", None)
        return status if isinstance(status, int) else 0

    def terminate(self, grace: float) -> None:
        deadline = time.monotonic() + grace
        try:
            self._proc.terminate(force=False)
        except Exception:  # noqa: BLE001
            pass
        while time.monotonic() < deadline and self.poll() is None:
            time.sleep(0.05)
        if self.poll() is None:
            try:
                self._proc.terminate(force=True)
            except Exception:  # noqa: BLE001
                pass

    def close(self) -> None:
        try:
            self._proc.close(force=True)
        except Exception:  # noqa: BLE001
            pass
