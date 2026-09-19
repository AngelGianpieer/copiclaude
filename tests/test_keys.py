import pytest

from copiclaude.keys import InputFilter, is_terminal_noise, parse_key


def feed(data, key="ctrl+k"):
    return InputFilter(parse_key(key)).feed(data)


def test_legacy_byte_is_removed_and_reported():
    assert feed(b"ab\x0bcd") == (b"abcd", True)


def test_plain_input_untouched():
    assert feed(b"hello \x1b[A world") == (b"hello \x1b[A world", False)


@pytest.mark.parametrize("mods", [5, 69, 133, 197])  # ctrl, +caps, +num, +both
def test_kitty_press_with_lock_modifiers(mods):
    assert feed(b"\x1b[107;%du" % mods) == (b"", True)


def test_kitty_release_and_repeat_are_swallowed_without_retrigger():
    assert feed(b"\x1b[107;5:3u") == (b"", False)
    assert feed(b"\x1b[107;5:2u") == (b"", False)
    assert feed(b"\x1b[107;5:1u") == (b"", True)


def test_kitty_other_keys_pass_through():
    for seq in (b"\x1b[107;1u", b"\x1b[107;6u", b"\x1b[108;5u", b"\x1b[107;7u"):  # none / shift / other / alt
        assert feed(seq) == (seq, False)


def test_modify_other_keys_form():
    assert feed(b"\x1b[27;5;107~") == (b"", True)
    assert feed(b"\x1b[27;5;108~") == (b"\x1b[27;5;108~", False)


def test_paste_content_is_never_inspected():
    data = b"\x1b[200~line1\x0bline2\x1b[201~"
    assert feed(data) == (data, False)


def test_paste_state_survives_chunk_boundaries():
    flt = InputFilter(parse_key("ctrl+k"))
    assert flt.feed(b"\x1b[200~abc\x0b") == (b"\x1b[200~abc\x0b", False)
    assert flt.feed(b"def\x1b[201~\x0b") == (b"def\x1b[201~", True)


@pytest.mark.parametrize(
    "spec,legacy,code",
    [("ctrl+k", 0x0B, 107), ("CTRL+G", 0x07, 103), ("ctrl+]", 0x1D, 93), ("ctrl+\\", 0x1C, 92)],
)
def test_parse_key(spec, legacy, code):
    key = parse_key(spec)
    assert (key.legacy, key.code) == (legacy, code)


@pytest.mark.parametrize("bad", ["k", "ctrl+", "ctrl+kk", "alt+k", "ctrl+c", "ctrl+d", "ctrl+m", "ctrl+[", "ctrl+1", 5, None])
def test_parse_key_rejects(bad):
    with pytest.raises(ValueError):
        parse_key(bad)


def test_other_key_is_configurable():
    assert feed(b"a\x07b", "ctrl+g") == (b"ab", True)
    assert feed(b"\x0b", "ctrl+g") == (b"\x0b", False)


def test_terminal_noise():
    assert is_terminal_noise(b"\x1b[I")
    assert is_terminal_noise(b"\x1b[<0;10;5M\x1b[<0;10;5m")
    assert not is_terminal_noise(b"a")
    assert not is_terminal_noise(b"\x1b[I a")
