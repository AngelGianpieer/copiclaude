from copiclaude.agents import AGENT_IMPLS
from copiclaude.detect import QuotaDetector, TextStream, strip_ansi

CLAUDE = AGENT_IMPLS["claude"].quota_patterns
COPILOT = AGENT_IMPLS["copilot"].quota_patterns


def run(patterns, chunks, quiet=1.0):
    det = QuotaDetector(patterns, quiet=quiet)
    t = 0.0
    for chunk in chunks:
        det.feed(chunk, t)
        t += 0.1
    return det, t


def test_strip_ansi_maps_cursor_moves_to_spaces():
    # the shape of real Claude Code repaints: words separated by "CSI n G" rather than spaces
    raw = "You've\x1b[8Ghit\x1b[12Gyour\x1b[17Glimit\x1b[0m"
    assert "You've hit your limit" in " ".join(strip_ansi(raw).split())


def test_strip_ansi_removes_osc_sgr_and_controls():
    assert strip_ansi("\x1b]0;title\x07\x1b[1;31mred\x1b[0m\x00\x08") == "red"


def test_split_escape_and_utf8_across_chunks():
    stream = TextStream()
    data = "café \x1b[38;2;1;2;3mok".encode()
    out = "".join(stream.feed(data[i:i + 1]) for i in range(len(data)))
    assert out == "café ok"


def test_limit_message_fires_only_after_silence():
    det, t = run(CLAUDE, [b"working...", b"You've hit your limit - resets 3pm"])
    assert det.poll(t) is None  # still fresh
    hit = det.poll(t + 1.5)
    assert hit and "hit your limit" in hit
    assert det.poll(t + 5) is None  # reported once


def test_continued_output_cancels_the_hint():
    det, t = run(CLAUDE, [b"You've hit your limit"])
    det.feed(b"...and the agent keeps streaming", t + 0.5)
    assert det.poll(t + 0.9) is None
    assert det.poll(t + 2.0) is not None  # quiet again after the last chunk: still a candidate
    det2 = QuotaDetector(CLAUDE, quiet=1.0, expire=3.0)
    det2.feed(b"You've hit your limit", 0.0)
    for i in range(1, 8):  # keeps talking every 0.5s for longer than `expire`
        det2.feed(b"more text", i * 0.5)
        assert det2.poll(i * 0.5) is None
    assert det2.poll(20.0) is None  # expired: never reported


def test_same_text_is_not_reported_twice():
    det, t = run(CLAUDE, [b"You've hit your limit"])
    assert det.poll(t + 2) is not None
    det.feed(b"unrelated new output", t + 3)
    assert det.poll(t + 6) is None


def test_reset_discards_pending_and_old_text():
    det, t = run(CLAUDE, [b"You've hit your limit"])
    det.reset()
    assert det.poll(t + 5) is None


def test_ordinary_talk_about_rate_limits_does_not_match():
    for text in (
        b"Set a rate limit of 10 requests per minute in nginx.",
        b"the function limit() returns the limit",
        b"resets at midnight UTC in this cron job",
        b"usage: prog [options]",
    ):
        det, t = run(CLAUDE + COPILOT, [text])
        assert det.poll(t + 5) is None, text


def test_known_messages_match():
    cases = [
        (CLAUDE, b"You've hit your limit \xc2\xb7 resets 3pm"),
        (CLAUDE, b"5-hour limit reached \xe2\x88\x99 resets 3pm"),
        (CLAUDE, b"Claude AI usage limit reached|1789849696"),
        (CLAUDE, b"Weekly limit reached"),
        (COPILOT, b"The next model call is final for this session"),
        (COPILOT, b"You've reached your monthly quota"),
        (COPILOT, b"quota exceeded"),
        (COPILOT, b"Session limits reached"),
    ]
    for patterns, text in cases:
        det, t = run(patterns, [text])
        assert det.poll(t + 5) is not None, text


def test_match_survives_tui_repaint_escapes():
    raw = b"You've\x1b[2C\x1b[1Bhit\x1b[8Gyour\x1b[13Glimit"
    det, t = run(CLAUDE, [raw])
    assert det.poll(t + 5) is not None
