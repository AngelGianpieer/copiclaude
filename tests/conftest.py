import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

FAKE_AGENT = str(Path(__file__).resolve().parent / "fake_agent.py")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Never touch the real home directory or the real CLIs' session stores."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    monkeypatch.setenv("COPILOT_HOME", str(home / ".copilot"))
    monkeypatch.setenv("COPICLAUDE_LANG", "en")
    monkeypatch.delenv("COPICLAUDE", raising=False)
    return home


@pytest.fixture
def project_dir(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".git").mkdir()  # marks the project root without needing git itself
    return root
