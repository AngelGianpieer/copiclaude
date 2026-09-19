"""The switch key: parsing its spec and spotting it in raw terminal input.

Terminals can report Ctrl+<letter> three different ways depending on which
keyboard protocol the child application enabled:

* legacy: a single control byte (Ctrl+K is 0x0B);
* kitty keyboard protocol: ``CSI <code> ; <mods> [: <event>] u``;
* xterm modifyOtherKeys: ``CSI 27 ; <mods> ; <code> ~``.

Bracketed-paste content is never inspected, so pasting text that happens to
contain a control byte cannot trigger a switch.
"""

from __future__ import annotations

import re
from typing import Tuple

_PASTE_ON = b"\x1b[200~"
_PASTE_OFF = b"\x1b[201~"
_KITTY = re.compile(rb"\x1b\[(\d+)(?::\d*)*;(\d+)(?::(\d+))?(?:;[\d:]*)?u")
_MOK = re.compile(rb"\x1b\[27;(\d+);(\d+)~")

# Keys that already mean something fundamental in a raw terminal.
_RESERVED = set("cdijmh[")
_PUNCT = {"]": 0x1D, "\\": 0x1C, "^": 0x1E, "_": 0x1F}


class KeySpec:
    def __init__(self, text: str, legacy: int, code: int) -> None:
        self.text = text
        self.legacy = legacy  # control byte sent by legacy terminals
        self.code = code  # unicode code point used by the CSI-u / modifyOtherKeys forms


def parse_key(spec: object) -> KeySpec:
    if not isinstance(spec, str):
        raise ValueError("must be a string like 'ctrl+k'")
    text = spec.strip().lower()
    if not text.startswith("ctrl+") or len(text) != len("ctrl+") + 1:
        raise ValueError("must look like 'ctrl+<letter>' (or ctrl+] ctrl+\\ ctrl+^ ctrl+_), got %r" % spec)
    char = text[-1]
    if char in _RESERVED:
        raise ValueError("ctrl+%s is reserved by the terminal; pick another key" % char)
    if "a" <= char <= "z":
        return KeySpec(text, ord(char) - 96, ord(char))
    if char in _PUNCT:
        return KeySpec(text, _PUNCT[char], ord(char))
    raise ValueError("unsupported key %r" % spec)


def _is_plain_ctrl(mods: int) -> bool:
    bits = mods - 1
    # ctrl (4) required; shift (1), alt (2) and super (8) not allowed.
    # caps-lock (64) and num-lock (128) are ignored.
    return bool(bits & 4) and not bits & (1 | 2 | 8)


class InputFilter:
    """Removes the switch key from the byte stream headed to the agent."""

    def __init__(self, key: KeySpec) -> None:
        self.key = key
        self.in_paste = False

    def feed(self, data: bytes) -> Tuple[bytes, bool]:
        """Return ``(bytes to forward, whether the switch key was pressed)``."""
        out = bytearray()
        triggered = False
        while data:
            if self.in_paste:
                end = data.find(_PASTE_OFF)
                if end == -1:
                    out += data
                    break
                cut = end + len(_PASTE_OFF)
                out += data[:cut]
                data = data[cut:]
                self.in_paste = False
                continue
            start = data.find(_PASTE_ON)
            segment = data if start == -1 else data[:start]
            forwarded, hit = self._scan(segment)
            out += forwarded
            triggered = triggered or hit
            if start == -1:
                break
            out += _PASTE_ON
            data = data[start + len(_PASTE_ON):]
            self.in_paste = True
        return bytes(out), triggered

    def _scan(self, segment: bytes) -> Tuple[bytes, bool]:
        hit = [False]
        key = self.key

        def kitty(match: "re.Match[bytes]") -> bytes:
            code, mods = int(match.group(1)), int(match.group(2))
            event = int(match.group(3) or 1)
            if code == key.code and _is_plain_ctrl(mods):
                if event == 1:  # press; repeat (2) and release (3) are swallowed silently
                    hit[0] = True
                return b""
            return match.group(0)

        def modify_other_keys(match: "re.Match[bytes]") -> bytes:
            mods, code = int(match.group(1)), int(match.group(2))
            if code == key.code and _is_plain_ctrl(mods):
                hit[0] = True
                return b""
            return match.group(0)

        segment = _KITTY.sub(kitty, segment)
        segment = _MOK.sub(modify_other_keys, segment)
        legacy = bytes([key.legacy])
        if legacy in segment:
            hit[0] = True
            segment = segment.replace(legacy, b"")
        return segment, hit[0]


_NOISE = re.compile(rb"^(?:\x1b\[[IO]|\x1b\[<\d+;\d+;\d+[Mm])+$")


def is_terminal_noise(data: bytes) -> bool:
    """Focus and mouse reports are not keystrokes: they must not dismiss prompts."""
    return bool(_NOISE.match(data))

