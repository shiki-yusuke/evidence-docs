from __future__ import annotations

import subprocess

import pytest

from evidence_docs.errors import CorpusError
from evidence_docs.gitio import (
    BlobDigestCache,
    is_safe_repo_relative_uri,
    resolve_repo_path,
    sha256_of_file,
)


def test_sha256_of_git_blob_matches_worktree_file_sha256(mini_domain):
    cache = BlobDigestCache(mini_domain.repo_root)
    blob_digest = cache.sha256_of_git_blob(mini_domain.repo_commit, "src/task_store.py")
    worktree_digest = sha256_of_file(mini_domain.repo_root / "src" / "task_store.py")
    assert blob_digest == worktree_digest


def test_blob_digest_cache_memoizes_repeated_uri(mini_domain):
    cache = BlobDigestCache(mini_domain.repo_root)
    cache.sha256_of_git_blob(mini_domain.repo_commit, "src/task_store.py")
    cache.sha256_of_git_blob(mini_domain.repo_commit, "src/task_store.py")
    cache.sha256_of_git_blob(mini_domain.repo_commit, "src/task_store.py")
    assert cache.call_count == 1


def test_blob_digest_cache_calls_once_per_distinct_uri(mini_domain):
    cache = BlobDigestCache(mini_domain.repo_root)
    cache.sha256_of_git_blob(mini_domain.repo_commit, "src/task_store.py")
    cache.sha256_of_git_blob(mini_domain.repo_commit, "tests/test_task_store.py")
    assert cache.call_count == 2


def test_sha256_of_git_blob_raises_for_nonexistent_uri(mini_domain):
    cache = BlobDigestCache(mini_domain.repo_root)
    with pytest.raises(CorpusError, match="git show"):
        cache.sha256_of_git_blob(mini_domain.repo_commit, "src/does_not_exist.py")


def test_sha256_of_git_blob_rejects_path_traversal_uri(mini_domain):
    cache = BlobDigestCache(mini_domain.repo_root)
    with pytest.raises(CorpusError, match="not a safe repo-relative path"):
        cache.sha256_of_git_blob(mini_domain.repo_commit, "../../etc/passwd")


def test_sha256_of_git_blob_uses_the_declared_commit_not_the_worktree(mini_domain):
    """Editing the worktree file after the commit must not change the blob digest --
    it must still reflect what was committed."""

    cache = BlobDigestCache(mini_domain.repo_root)
    original_digest = cache.sha256_of_git_blob(mini_domain.repo_commit, "src/task_store.py")

    (mini_domain.repo_root / "src" / "task_store.py").write_text("# tampered\n", encoding="utf-8")

    fresh_cache = BlobDigestCache(mini_domain.repo_root)
    digest_after_edit = fresh_cache.sha256_of_git_blob(mini_domain.repo_commit, "src/task_store.py")
    assert digest_after_edit == original_digest


@pytest.mark.parametrize(
    "uri",
    ["/etc/passwd", "../secret", "a/../../secret", "", "a//b"],
)
def test_is_safe_repo_relative_uri_rejects_traversal_and_absolute_paths(uri):
    assert is_safe_repo_relative_uri(uri) is False


def test_is_safe_repo_relative_uri_accepts_normal_relative_path():
    assert is_safe_repo_relative_uri("src/task_store.py") is True


def test_resolve_repo_path_rejects_path_traversal(mini_domain):
    with pytest.raises(CorpusError, match="escapes repo root"):
        resolve_repo_path(mini_domain.repo_root, "../../etc/passwd")


def test_resolve_repo_path_rejects_symlink_escape(mini_domain, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = mini_domain.repo_root / "escape-link"
    link.symlink_to(outside)
    with pytest.raises(CorpusError, match="escapes repo root"):
        resolve_repo_path(mini_domain.repo_root, "escape-link")


def test_resolve_repo_path_accepts_file_inside_repo_root(mini_domain):
    resolved = resolve_repo_path(mini_domain.repo_root, "src/task_store.py")
    assert resolved == (mini_domain.repo_root / "src" / "task_store.py").resolve()
