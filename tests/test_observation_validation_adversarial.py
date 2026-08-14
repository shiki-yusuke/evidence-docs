"""Adversarial cases for validate_observation(): each of these mirrors a
bypass found and closed during the pilot corpus's review history (see
docs/schema.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evidence_docs.corpus import validate_observation
from evidence_docs.errors import CorpusError

FAKE_PATH = Path("observations/fake.yaml")


def _base_observation(**overrides) -> dict:
    obs = {
        "observation_id": "OBS-001",
        "topic_id": "T-01",
        "claim_kind": "behavior",
        "statement": "example statement",
        "origin": "reconstructed",
        "epistemic_status": "execution_verified",
        "review_status": "unreviewed",
        "conformance_status": "matched",
        "provenance": [
            {
                "source_kind": "source",
                "uri": "src/example.py",
                "content_digest": "a" * 64,
                "repo_commit": "f" * 40,
                "observed_at": "2026-08-01T00:00:00Z",
            }
        ],
    }
    obs.update(overrides)
    return obs


def test_valid_observation_passes():
    validate_observation(_base_observation(), FAKE_PATH)  # must not raise


@pytest.mark.parametrize(
    "field,value",
    [
        ("claim_kind", "not_a_real_kind"),
        ("origin", "made_up"),
        ("epistemic_status", "very_sure"),
        ("conformance_status", "sort_of"),
        ("review_status", "half_reviewed"),
    ],
)
def test_rejects_unknown_enum_values(field, value):
    with pytest.raises(CorpusError):
        validate_observation(_base_observation(**{field: value}), FAKE_PATH)


def test_rejects_empty_provenance():
    with pytest.raises(CorpusError, match="no provenance"):
        validate_observation(_base_observation(provenance=[]), FAKE_PATH)


def test_rejects_typo_source_kind_even_with_plausible_digest():
    """A typo'd source_kind ("soruce") must not silently skip validation --
    if it did, an out-of-repo uri + arbitrary digest would sail through."""

    obs = _base_observation(
        provenance=[
            {
                "source_kind": "soruce",
                "uri": "../../etc/passwd",
                "content_digest": "a" * 64,
                "repo_commit": "f" * 40,
                "observed_at": "2026-08-01T00:00:00Z",
            }
        ]
    )
    with pytest.raises(CorpusError, match="unknown source_kind"):
        validate_observation(obs, FAKE_PATH)


def test_rejects_non_sha256_content_digest_for_repo_internal_source():
    obs = _base_observation(
        provenance=[
            {
                "source_kind": "source",
                "uri": "src/example.py",
                "content_digest": "not-a-hash",
                "repo_commit": "f" * 40,
                "observed_at": "2026-08-01T00:00:00Z",
            }
        ]
    )
    with pytest.raises(CorpusError, match="sha256"):
        validate_observation(obs, FAKE_PATH)


def test_external_source_kind_accepts_sha256_hex_digest():
    obs = _base_observation(
        provenance=[
            {
                "source_kind": "review_memory",
                "uri": "notes.jsonl#L1",
                "content_digest": "a" * 64,
                "repo_commit": "f" * 40,
                "observed_at": "2026-08-01T00:00:00Z",
            }
        ]
    )
    validate_observation(obs, FAKE_PATH)  # must not raise


def test_external_source_kind_accepts_declared_sentinel():
    obs = _base_observation(
        provenance=[
            {
                "source_kind": "review_memory",
                "uri": "notes.jsonl#L1",
                "content_digest": "not_computed_external_to_repo",
                "repo_commit": "f" * 40,
                "observed_at": "2026-08-01T00:00:00Z",
            }
        ]
    )
    validate_observation(obs, FAKE_PATH)  # must not raise


def test_external_source_kind_rejects_arbitrary_non_sentinel_digest():
    obs = _base_observation(
        provenance=[
            {
                "source_kind": "review_memory",
                "uri": "notes.jsonl#L1",
                "content_digest": "whatever-i-feel-like",
                "repo_commit": "f" * 40,
                "observed_at": "2026-08-01T00:00:00Z",
            }
        ]
    )
    with pytest.raises(CorpusError, match="sentinel"):
        validate_observation(obs, FAKE_PATH)


def test_external_source_kind_rejects_empty_uri():
    obs = _base_observation(
        provenance=[
            {
                "source_kind": "review_memory",
                "uri": "  ",
                "content_digest": "not_computed_external_to_repo",
                "repo_commit": "f" * 40,
                "observed_at": "2026-08-01T00:00:00Z",
            }
        ]
    )
    with pytest.raises(CorpusError, match="empty uri"):
        validate_observation(obs, FAKE_PATH)


@pytest.mark.parametrize(
    "observed_at",
    [
        None,
        "",
        "not-an-iso-date",
        "2026-08-01T00:00:00",  # naive
        "2026-08-01T00:00:00+09:00",  # non-UTC offset
    ],
)
def test_rejects_invalid_observed_at(observed_at):
    obs = _base_observation(
        provenance=[
            {
                "source_kind": "source",
                "uri": "src/example.py",
                "content_digest": "a" * 64,
                "repo_commit": "f" * 40,
                "observed_at": observed_at,
            }
        ]
    )
    with pytest.raises(CorpusError, match="observed_at"):
        validate_observation(obs, FAKE_PATH)


def test_negation_check_optional_field_absent_is_fine():
    validate_observation(_base_observation(), FAKE_PATH)  # must not raise


def test_negation_check_accepts_non_empty_string():
    validate_observation(_base_observation(negation_check="broke the guard, test went red"), FAKE_PATH)


def test_negation_check_rejects_empty_string():
    with pytest.raises(CorpusError, match="negation_check"):
        validate_observation(_base_observation(negation_check="   "), FAKE_PATH)


def test_negation_check_rejects_non_string_type():
    with pytest.raises(CorpusError, match="negation_check"):
        validate_observation(_base_observation(negation_check=True), FAKE_PATH)
