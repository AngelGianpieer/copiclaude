import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from copiclaude.project import LockError, Project, ProjectLock, find_root, is_risky_root

import pytest


def test_root_is_nearest_git_checkout(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    deep = tmp_path / "repo" / "a" / "b"
    deep.mkdir(parents=True)
    assert find_root(deep) == tmp_path / "repo"


def test_existing_state_dir_marks_the_root(tmp_path):
    (tmp_path / "p" / ".copiclaude").mkdir(parents=True)
    (tmp_path / "p" / "sub").mkdir()
    assert find_root(tmp_path / "p" / "sub") == tmp_path / "p"


def test_git_worktree_file_counts_as_a_checkout(tmp_path):
    (tmp_path / "wt").mkdir()
    (tmp_path / "wt" / ".git").write_text("gitdir: /elsewhere\n")
    assert find_root(tmp_path / "wt") == tmp_path / "wt"


def test_without_markers_the_cwd_is_the_root(tmp_path):
    (tmp_path / "loose").mkdir()
    assert find_root(tmp_path / "loose") == tmp_path / "loose"


def test_home_and_filesystem_root_are_risky_unless_already_adopted(isolated_env):
    assert is_risky_root(isolated_env)
    assert is_risky_root(Path(isolated_env.anchor))
    (isolated_env / ".copiclaude").mkdir()
    assert not is_risky_root(isolated_env)
    assert not is_risky_root(isolated_env / "projects")


def test_ensure_creates_self_ignoring_state_dir(project_dir):
    project = Project(project_dir)
    project.ensure()
    project.ensure()  # idempotent
    assert (project.state_dir / ".gitignore").read_text() == "*\n"
    assert not (project_dir / ".gitignore").exists()


def test_log_rotates(project_dir):
    project = Project(project_dir)
    project.ensure()
    project.log_file.write_text("x" * (600 * 1024))
    project.log("hello")
    assert (project.state_dir / "session.log.1").exists()
    assert "hello" in project.log_file.read_text()


def test_lock_is_exclusive_and_released(project_dir):
    project = Project(project_dir)
    with ProjectLock(project):
        assert ProjectLock.is_held(project)
        second = ProjectLock(project)
        with pytest.raises(LockError) as exc:
            second.acquire()
        assert exc.value.pid == os.getpid()
    assert not ProjectLock.is_held(project)
    assert not project.pid_file.exists()


def test_lock_dies_with_its_process(project_dir):
    """No stale locks: a killed holder must not block the next run."""
    script = textwrap.dedent(
        """
        import sys, time
        sys.path.insert(0, %r)
        from pathlib import Path
        from copiclaude.project import Project, ProjectLock
        lock = ProjectLock(Project(Path(%r)))
        lock.acquire()
        print("locked", flush=True)
        time.sleep(60)
        """
    ) % (str(Path(__file__).resolve().parent.parent / "src"), str(project_dir))
    proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE)
    try:
        assert proc.stdout.readline().strip() == b"locked"
        assert ProjectLock.is_held(Project(project_dir))
    finally:
        proc.kill()
        proc.wait()
    assert not ProjectLock.is_held(Project(project_dir))
