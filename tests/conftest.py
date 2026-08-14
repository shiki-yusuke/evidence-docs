"""Shared test fixtures.

`mini_domain` materializes fixtures/mini-domain into a real, throwaway git
repo per test: the repo/ half becomes an actual git commit (so
`git show <sha>:<uri>` blob verification is exercised for real, not
mocked), and the corpus/ half is copied with its `__REPO_COMMIT__` /
`__DIGEST:<path>__` placeholders substituted for the real commit SHA and
real file digests. This keeps the checked-in fixture free of a nested .git
directory while still testing the full validate/generate path end to end.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "mini-domain"

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "evidence-docs fixtures",
    "GIT_AUTHOR_EMAIL": "fixtures@example.invalid",
    "GIT_COMMITTER_NAME": "evidence-docs fixtures",
    "GIT_COMMITTER_EMAIL": "fixtures@example.invalid",
}


@dataclass
class MiniDomain:
    corpus_dir: Path
    repo_root: Path
    repo_commit: str


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=_env(),
        capture_output=True,
        text=True,
        check=True,
    )


def _env() -> dict:
    import os

    env = dict(os.environ)
    env.update(_GIT_ENV)
    return env


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def mini_domain(tmp_path: Path) -> MiniDomain:
    repo_root = tmp_path / "repo"
    shutil.copytree(FIXTURES_DIR / "repo", repo_root)

    _run_git(["init", "-q", "-b", "main"], cwd=repo_root)
    _run_git(["add", "-A"], cwd=repo_root)
    _run_git(
        ["-c", "commit.gpgsign=false", "commit", "-q", "-m", "mini-domain fixture snapshot"],
        cwd=repo_root,
    )
    repo_commit = _run_git(["rev-parse", "HEAD"], cwd=repo_root).stdout.strip()

    digests = {}
    for f in repo_root.rglob("*"):
        if f.is_file() and ".git" not in f.parts:
            rel = f.relative_to(repo_root).as_posix()
            digests[rel] = _sha256_of(f)

    corpus_dir = tmp_path / "corpus"
    shutil.copytree(FIXTURES_DIR / "corpus", corpus_dir)

    for f in corpus_dir.rglob("*"):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8")
        if "__REPO_COMMIT__" not in text and "__DIGEST:" not in text:
            continue
        text = text.replace("__REPO_COMMIT__", repo_commit)
        for rel, digest in digests.items():
            text = text.replace(f"__DIGEST:{rel}__", digest)
        f.write_text(text, encoding="utf-8")

    return MiniDomain(corpus_dir=corpus_dir, repo_root=repo_root, repo_commit=repo_commit)
