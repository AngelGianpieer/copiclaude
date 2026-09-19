import os
import shutil
import subprocess

import pytest

from copiclaude import handoff
from copiclaude.agents import PROMPT_PREFIX, Context
from copiclaude.project import Project


def make_ctx(prompts=("fix the parser",), reply="I fixed it"):
    ctx = Context()
    ctx.found, ctx.prompts, ctx.last_reply = True, list(prompts), reply
    return ctx


def test_render_contains_context_and_framing(project_dir):
    text = handoff.render(Project(project_dir), "claude", "copilot", "quota", make_ctx(), 0)
    assert "# Handoff: claude -> copilot" in text
    assert "usage limit" in text
    assert "not a set of instructions" in text
    assert "1. fix the parser" in text
    assert "> I fixed it" in text


def test_render_without_history_says_so(project_dir):
    text = handoff.render(Project(project_dir), "claude", "copilot", "manual", Context())
    assert "could not be read" in text


def test_terminal_garbage_never_reaches_the_handoff(project_dir):
    ctx = make_ctx(prompts=["\x1b[31mred\x1b[0m prompt\x1b[64Gtail\x00"], reply="\x1b]0;t\x07clean\x1b[1B")
    text = handoff.render(Project(project_dir), "claude", "copilot", "manual", ctx)
    assert "\x1b" not in text and "\x00" not in text


def test_long_content_is_truncated(project_dir):
    text = handoff.render(Project(project_dir), "a", "b", "manual", make_ctx(prompts=["x" * 5000], reply="y" * 9000))
    assert len(text) < 5000 and "[...]" in text


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_git_state_is_included(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    run("init", "-q")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "T")
    (repo / "a.txt").write_text("1\n")
    run("add", ".")
    run("commit", "-q", "-m", "first commit")
    (repo / "a.txt").write_text("2\n")
    (repo / "new.txt").write_text("x\n")
    text = handoff.render(Project(repo), "claude", "copilot", "manual", make_ctx())
    assert "## Git state" in text and "a.txt" in text and "new.txt" in text and "first commit" in text


def test_non_git_directory_is_fine(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    assert "## Git state" not in handoff.render(Project(d), "a", "b", "manual", make_ctx())


def test_write_creates_latest_and_history_and_prunes(project_dir):
    project = Project(project_dir)
    for i in range(14):
        handoff.write(project, "text %d" % i, "claude", "copilot", keep=10)
    assert project.handoff_file.read_text() == "text 13"
    assert len(list(project.handoffs_dir.glob("*.md"))) <= 10


def test_prompt_is_safe_for_every_command_line(project_dir):
    project = Project(project_dir)
    for auto in (False, True):
        prompt = handoff.build_prompt(project, auto)
        assert prompt.startswith(PROMPT_PREFIX)
        assert ".copiclaude/HANDOFF.md" in prompt
        assert not set(prompt) & set('"&|<>^%$`\\!\n')
    assert "wait for my confirmation" in handoff.build_prompt(project, False)
    assert "continue the work" in handoff.build_prompt(project, True)


def test_prompt_from_a_subdirectory_points_at_the_root_state(project_dir):
    sub = project_dir / "src" / "pkg"
    sub.mkdir(parents=True)
    prompt = handoff.build_prompt(Project(project_dir, sub), False)
    assert "../../.copiclaude/HANDOFF.md" in prompt


def test_prompt_with_an_unsafe_path_falls_back_to_a_generic_description(tmp_path):
    weird = tmp_path / "a&b %x"
    weird.mkdir()
    sub = weird / "s"
    sub.mkdir()
    prompt = handoff.build_prompt(Project(weird, sub), False)
    assert not set(prompt) & set('"&|<>^%')


# ------------------------------------------------------------------ legacy 0.1 blocks

BLOCK = handoff.LEGACY_START + "\n(No se pudo confirmar ...)\n```\n\x1b[64Gjunk\n```\n" + handoff.LEGACY_END


def test_legacy_block_only_file_is_removed_with_backup(tmp_path):
    (tmp_path / "CLAUDE.md").write_text(BLOCK + "\n")
    changed = handoff.remove_legacy_blocks(tmp_path)
    assert [p.name for p in changed] == ["CLAUDE.md"]
    assert not (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / "CLAUDE.md.copiclaude.bak").read_text() == BLOCK + "\n"


def test_legacy_block_is_removed_but_user_content_is_kept(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# My rules\n\nUse tabs.\n\n" + BLOCK + "\n")
    handoff.remove_legacy_blocks(tmp_path)
    assert (tmp_path / "AGENTS.md").read_text() == "# My rules\n\nUse tabs.\n"


def test_files_without_a_block_are_left_alone(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("mine\n")
    assert handoff.find_legacy_blocks(tmp_path) == []
    assert handoff.remove_legacy_blocks(tmp_path) == []
    assert not (tmp_path / "CLAUDE.md.copiclaude.bak").exists()


def test_copiclaude_never_writes_project_instruction_files(project_dir):
    project = Project(project_dir)
    handoff.write(project, handoff.render(project, "a", "b", "manual", make_ctx()), "a", "b")
    assert not (project_dir / "CLAUDE.md").exists() and not (project_dir / "AGENTS.md").exists()
    assert (project.state_dir / ".gitignore").read_text() == "*\n"
