"""Turning a raw terminal byte stream into text, and spotting "out of quota".

TUI agents repaint with cursor-movement escapes instead of spaces, so a naive
"strip the escapes" leaves words glued together. Cursor-forward/absolute moves
are mapped to a space and vertical moves to a newline before matching.

Screen matching is only a *hint*. A phrase such as "rate limit" also shows up
when the agent is merely talking about rate limits, so a hit only counts once
the agent has gone quiet, and (by default) the user is asked to confirm.
"""

from __future__ import annotations

import codecs
import re
from typing import List, Optional, Pattern

_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ESC2 = re.compile(r"\x1b[\x20-\x2f]*[\x30-\x7e]")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _csi_replacement(match: "re.Match[str]") -> str:
    final = match.group(0)[-1]
    if final in "CG`a":  # cursor forward / absolute column: TUIs use these instead of spaces
        return " "
    if final in "BEHFfde":  # cursor down / next line / absolute position
        return "\n"
    return ""


def strip_ansi(text: str) -> str:
    text = _OSC.sub("", text)
    text = _CSI.sub(_csi_replacement, text)
    text = _ESC2.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _CTRL.sub("", text)


def _escape_complete(text: str, index: int) -> bool:
    if _CSI.match(text, index) or _OSC.match(text, index):
        return True
    following = text[index + 1:index + 2]
    if following == "" or following in "[]P^_X":
        return False
    if following in " !\"#$%&'()*+,-./":
        return len(text) > index + 2
    return True


class TextStream:
    """Incrementally decode bytes and strip escapes, holding back split sequences."""

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._carry = ""

    def feed(self, data: bytes) -> str:
        text = self._carry + self._decoder.decode(data)
        self._carry = ""
        index = text.rfind("\x1b")
        if index != -1 and len(text) - index < 64 and not _escape_complete(text, index):
            self._carry = text[index:]
            text = text[:index]
        return strip_ansi(text)


def phrase(text: str) -> str:
    """Regex for a phrase that tolerates missing/extra spaces (see module docstring)."""
    return r"\s*".join(re.escape(word) for word in text.split())


class QuotaDetector:
    """Watches agent output for a quota/limit message that is followed by silence."""

    def __init__(self, patterns: List[Pattern[str]], quiet: float = 1.5, expire: float = 20.0) -> None:
        self.patterns = patterns
        self.quiet = quiet
        self.expire = expire
        self._stream = TextStream()
        self._text = ""
        self._scanned = 0
        self._last_output = 0.0
        self._suspect: Optional[str] = None
        self._suspect_at = 0.0

    def feed(self, data: bytes, now: float) -> None:
        visible = re.sub(r"\s+", " ", self._stream.feed(data))
        if not visible.strip():
            return
        self._last_output = now
        self._text += visible
        if len(self._text) > 4000:
            cut = len(self._text) - 4000
            self._text = self._text[cut:]
            self._scanned = max(0, self._scanned - cut)
        if self._suspect is not None:
            return
        window = self._text[self._scanned:]
        best = None
        for pattern in self.patterns:
            match = pattern.search(window)
            if match and (best is None or match.start() < best.start()):
                best = match
        if best is not None:
            self._scanned += best.end()
            self._suspect = self._text[max(0, self._scanned - 160):self._scanned].strip()
            self._suspect_at = now

    def poll(self, now: float) -> Optional[str]:
        """Return the matched excerpt once output has been quiet long enough."""
        if self._suspect is None:
            return None
        if now - self._last_output >= self.quiet:
            hit, self._suspect = self._suspect, None
            return hit
        if now - self._suspect_at > self.expire:  # the agent kept talking: not a limit screen
            self._suspect = None
        return None

    def reset(self) -> None:
        self._suspect = None
        self._scanned = len(self._text)
