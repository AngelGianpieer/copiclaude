"""The user's real terminal: raw input, size, and cleaning up after a child.

An agent that is killed cannot undo the terminal modes it switched on (mouse
tracking, bracketed paste, kitty keyboard protocol, alternate screen...), which
would leave the user's shell spewing escape codes. ``reset_bytes`` restores them.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from typing import Optional, Tuple

_MODE = re.compile(rb"\x1b\[\?([0-9;]+)([hl])")

RESET_MODES = (
    b"\x1b[<99u"  # pop every kitty keyboard-protocol level
    b"\x1b[>4;0m"  # xterm modifyOtherKeys off
    b"\x1b[?2004l"  # bracketed paste
    b"\x1b[?1004l"  # focus reporting
    b"\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?1015l"  # mouse tracking
    b"\x1b[?2031l"
    b"\x1b[?25h"  # cursor visible
    b"\x1b[0m"
)


class ModeTracker:
    """Remembers whether the child left the terminal on the alternate screen."""

    def __init__(self) -> None:
        self.alt_screen = False
        self._carry = b""

    def feed(self, data: bytes) -> None:
        data = self._carry + data
        tail = data[-16:]
        self._carry = tail if b"\x1b" in tail else b""
        for match in _MODE.finditer(data):
            if any(p in (b"1049", b"1047", b"47") for p in match.group(1).split(b";")):
                self.alt_screen = match.group(2) == b"h"

    def reset_bytes(self) -> bytes:
        out = RESET_MODES
        if self.alt_screen:
            out += b"\x1b[?1049l"
        return out


class Terminal:
    """Interface used by the supervisor (see PosixTerminal / WindowsTerminal)."""

    def is_tty(self) -> bool:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())

    def size(self) -> Tuple[int, int]:
        cols, rows = shutil.get_terminal_size((80, 24))
        return rows, cols

    def enter(self) -> None:
        """Switch to raw mode."""

    def leave(self) -> None:
        """Restore the original mode."""

    def read(self) -> bytes:
        """Block for input; return b'' at end of input."""
        raise NotImplementedError

    def write(self, data: bytes) -> None:
        raise NotImplementedError

    def write_text(self, text: str) -> None:
        """Print a message while in raw mode (newlines need a carriage return)."""
        self.write(text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8", errors="replace"))

    def close(self) -> None:
        """Unblock a pending read (test doubles); real terminals need nothing."""


def write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        try:
            written = os.write(fd, view)
        except InterruptedError:
            continue
        view = view[written:]


class PosixTerminal(Terminal):
    def __init__(self) -> None:
        self._saved = None

    def enter(self) -> None:
        import termios
        import tty

        fd = sys.stdin.fileno()
        self._saved = termios.tcgetattr(fd)
        tty.setraw(fd)

    def leave(self) -> None:
        if self._saved is not None:
            import termios

            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._saved)
            self._saved = None

    def read(self) -> bytes:
        try:
            return os.read(sys.stdin.fileno(), 4096)
        except OSError:
            return b""

    def write(self, data: bytes) -> None:
        try:
            write_all(sys.stdout.fileno(), data)
        except OSError:
            pass


class WindowsTerminal(Terminal):
    """Console with virtual-terminal input/output so escape sequences pass through."""

    ENABLE_PROCESSED_INPUT = 0x0001
    ENABLE_LINE_INPUT = 0x0002
    ENABLE_ECHO_INPUT = 0x0004
    ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
    ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004

    def __init__(self) -> None:
        import ctypes

        self._k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        self._stdin = self._k32.GetStdHandle(-10)
        self._stdout = self._k32.GetStdHandle(-11)
        self._saved_in: Optional[int] = None
        self._saved_out: Optional[int] = None
        self._high_surrogate = ""

    def _get_mode(self, handle: int) -> Optional[int]:
        import ctypes

        mode = ctypes.c_uint32()
        return mode.value if self._k32.GetConsoleMode(handle, ctypes.byref(mode)) else None

    def enter(self) -> None:
        self._saved_in = self._get_mode(self._stdin)
        self._saved_out = self._get_mode(self._stdout)
        if self._saved_in is not None:
            raw = self._saved_in & ~(self.ENABLE_ECHO_INPUT | self.ENABLE_LINE_INPUT | self.ENABLE_PROCESSED_INPUT)
            self._k32.SetConsoleMode(self._stdin, raw | self.ENABLE_VIRTUAL_TERMINAL_INPUT)
        if self._saved_out is not None:
            self._k32.SetConsoleMode(self._stdout, self._saved_out | self.ENABLE_VIRTUAL_TERMINAL_PROCESSING)

    def leave(self) -> None:
        if self._saved_in is not None:
            self._k32.SetConsoleMode(self._stdin, self._saved_in)
        if self._saved_out is not None:
            self._k32.SetConsoleMode(self._stdout, self._saved_out)

    def read(self) -> bytes:
        import ctypes

        buffer = ctypes.create_unicode_buffer(1024)
        count = ctypes.c_uint32()
        if not self._k32.ReadConsoleW(self._stdin, buffer, 1024, ctypes.byref(count), None) or count.value == 0:
            return b""
        text = self._high_surrogate + buffer.value[: count.value]
        self._high_surrogate = ""
        if text and "\ud800" <= text[-1] <= "\udbff":  # split surrogate pair: wait for the rest
            self._high_surrogate, text = text[-1], text[:-1]
        return text.encode("utf-8", errors="replace")

    def write(self, data: bytes) -> None:
        try:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        except (OSError, ValueError):
            pass


def make_terminal() -> Terminal:
    return WindowsTerminal() if os.name == "nt" else PosixTerminal()
