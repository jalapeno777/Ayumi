from __future__ import annotations

import os
import subprocess
from pathlib import Path

from monitoring.git_guard import git_log_recent_changes


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "Test Author")
    env.setdefault("GIT_AUTHOR_EMAIL", "test@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "Test Author")
    env.setdefault("GIT_COMMITTER_EMAIL", "test@example.com")
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    subprocess.run(
        ["git", "init", str(repo)], check=True, capture_output=True, text=True
    )
    _git(repo, "config", "user.name", "Test Author")
    _git(repo, "config", "user.email", "test@example.com")


def test_git_log_recent_changes_returns_commits_for_touched_path(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    tracked = repo / "src/module.py"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("print('hello')\n", encoding="utf-8")
    _git(repo, "add", "src/module.py")
    _git(repo, "commit", "-m", "touch guarded module")

    commits = git_log_recent_changes(str(tracked), days=7, repo_root=repo)

    assert len(commits) == 1
    assert commits[0].subject == "touch guarded module"
    assert commits[0].path == "src/module.py"
    assert commits[0].short_hash == commits[0].commit_hash[:12]


def test_git_log_recent_changes_returns_empty_for_untouched_path(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    tracked = repo / "src/module.py"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("print('hello')\n", encoding="utf-8")
    _git(repo, "add", "src/module.py")
    _git(repo, "commit", "-m", "touch guarded module")

    commits = git_log_recent_changes("src/other_module.py", days=7, repo_root=repo)

    assert commits == []
