import re
from pathlib import Path

import pytest

from copiclaude import i18n


def test_both_languages_have_the_same_keys_and_placeholders():
    en, es = i18n.MESSAGES["en"], i18n.MESSAGES["es"]
    assert set(en) == set(es)
    for key in en:
        assert set(re.findall(r"{(\w+)}", en[key])) == set(re.findall(r"{(\w+)}", es[key])), key


def test_every_key_used_in_the_code_exists():
    src = Path(i18n.__file__).parent
    used = set()
    for path in src.glob("*.py"):
        used |= set(re.findall(r'\bt\(\s*"(\w+)"', path.read_text()))
        used |= set(re.findall(r'\bt\(\s*"(reason_)"\s*\+', path.read_text()))
    used.discard("reason_")
    used |= {"reason_manual", "reason_quota", "reason_request", "mode_new", "mode_resume"}
    assert used <= set(i18n.MESSAGES["en"]), used - set(i18n.MESSAGES["en"])


@pytest.mark.parametrize("env,expected", [({"COPICLAUDE_LANG": "es"}, "es"), ({"COPICLAUDE_LANG": "en", "LANG": "es_PE.UTF-8"}, "en")])
def test_language_override(monkeypatch, env, expected):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert i18n.language() == expected


def test_language_from_locale(monkeypatch):
    monkeypatch.delenv("COPICLAUDE_LANG")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.setenv("LANG", "es_PE.UTF-8")
    assert i18n.language() == "es"
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")
    assert i18n.language() == "en"
