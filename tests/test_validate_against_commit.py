"""find_repo_commit_mismatches() and verify_content_digests_against_commit():
the two checks that, combined, close the "edit file + update digest + keep
repo_commit on the old SHA" bypass (see docs/schema.md)."""

from __future__ import annotations

import pytest

from evidence_docs.corpus import find_repo_commit_mismatches, verify_content_digests_against_commit
from evidence_docs.errors import CorpusError
from evidence_docs.gitio import BlobDigestCache, sha256_of_file


def _obs(oid, topic_id, uri, digest, repo_commit, valid_at_commit=None):
    return {
        oid: {
            "observation_id": oid,
            "topic_id": topic_id,
            "valid_at_commit": valid_at_commit or repo_commit,
            "provenance": [
                {
                    "source_kind": "source",
                    "uri": uri,
                    "content_digest": digest,
                    "repo_commit": repo_commit,
                    "observed_at": "2026-08-01T00:00:00Z",
                }
            ],
        }
    }


def test_content_digest_matching_declared_commit_passes(mini_domain):
    real_digest = sha256_of_file(mini_domain.repo_root / "src" / "task_store.py")
    observations = _obs("OBS-001", "T-01", "src/task_store.py", real_digest, mini_domain.repo_commit)
    cache = BlobDigestCache(mini_domain.repo_root)
    warnings = verify_content_digests_against_commit(observations, mini_domain.repo_commit, mini_domain.repo_root, cache)
    assert warnings == []


def test_content_digest_mismatch_against_declared_commit_is_fatal(mini_domain):
    observations = _obs("OBS-001", "T-01", "src/task_store.py", "b" * 64, mini_domain.repo_commit)
    cache = BlobDigestCache(mini_domain.repo_root)
    with pytest.raises(CorpusError, match="content_digest mismatch"):
        verify_content_digests_against_commit(observations, mini_domain.repo_commit, mini_domain.repo_root, cache)


def test_editing_worktree_file_and_updating_digest_does_not_bypass_commit_check(mini_domain):
    """The classic 3-stage bypass: edit the file, recompute content_digest for the
    NEW content, but leave repo_commit on the OLD (still-matching) SHA. Hashing the
    worktree file would let this through; hashing the declared commit's git blob
    must not."""

    tampered_path = mini_domain.repo_root / "src" / "task_store.py"
    tampered_path.write_text("# entirely different content now\n", encoding="utf-8")
    tampered_digest = sha256_of_file(tampered_path)

    observations = _obs("OBS-001", "T-01", "src/task_store.py", tampered_digest, mini_domain.repo_commit)
    cache = BlobDigestCache(mini_domain.repo_root)
    with pytest.raises(CorpusError, match="content_digest mismatch"):
        verify_content_digests_against_commit(observations, mini_domain.repo_commit, mini_domain.repo_root, cache)


def test_worktree_drift_after_commit_is_a_warning_not_an_error(mini_domain):
    """If content_digest correctly matches the declared commit's blob, but the
    worktree has since moved on, that's expected (the corpus is a snapshot) and
    must only warn, not fail."""

    real_digest = sha256_of_file(mini_domain.repo_root / "src" / "task_store.py")
    (mini_domain.repo_root / "src" / "task_store.py").write_text("# repo moved on\n", encoding="utf-8")

    observations = _obs("OBS-001", "T-01", "src/task_store.py", real_digest, mini_domain.repo_commit)
    cache = BlobDigestCache(mini_domain.repo_root)
    warnings = verify_content_digests_against_commit(observations, mini_domain.repo_commit, mini_domain.repo_root, cache)
    assert any("has changed in the current worktree" in w for w in warnings)


def test_uri_no_longer_present_in_worktree_is_a_warning(mini_domain):
    real_digest = sha256_of_file(mini_domain.repo_root / "src" / "task_store.py")
    (mini_domain.repo_root / "src" / "task_store.py").unlink()

    observations = _obs("OBS-001", "T-01", "src/task_store.py", real_digest, mini_domain.repo_commit)
    cache = BlobDigestCache(mini_domain.repo_root)
    warnings = verify_content_digests_against_commit(observations, mini_domain.repo_commit, mini_domain.repo_root, cache)
    assert any("no longer exists" in w for w in warnings)


def test_find_repo_commit_mismatches_reports_every_mismatch_not_just_first():
    other_sha = "b" * 40
    expected_sha = "a" * 40
    observations = {
        "OBS-001": {
            "observation_id": "OBS-001",
            "valid_at_commit": other_sha,
            "provenance": [
                {"uri": "x.py", "repo_commit": other_sha},
                {"uri": "y.py", "repo_commit": expected_sha},
            ],
        },
        "OBS-002": {
            "observation_id": "OBS-002",
            "valid_at_commit": expected_sha,
            "provenance": [{"uri": "z.py", "repo_commit": other_sha}],
        },
    }
    mismatches = find_repo_commit_mismatches(observations, expected_sha)
    # OBS-001.valid_at_commit, OBS-001.provenance[0], OBS-002.provenance[0] -- 3 total.
    assert len(mismatches) == 3
    assert any("OBS-001.valid_at_commit" in m for m in mismatches)
    assert any("OBS-001.provenance[0]" in m for m in mismatches)
    assert any("OBS-002.provenance[0]" in m for m in mismatches)


def test_find_repo_commit_mismatches_empty_when_everything_matches():
    sha = "a" * 40
    observations = {
        "OBS-001": {
            "observation_id": "OBS-001",
            "valid_at_commit": sha,
            "provenance": [{"uri": "x.py", "repo_commit": sha}],
        }
    }
    assert find_repo_commit_mismatches(observations, sha) == []
