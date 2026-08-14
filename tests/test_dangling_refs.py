"""check_dangling_refs(): supporting_refs/contradicting_refs get the same
"no dangling reference" guarantee topics.related_topics already had."""

from __future__ import annotations

import pytest

from evidence_docs.corpus import check_dangling_refs, normalize_ref_target
from evidence_docs.errors import CorpusError


def _obs(oid, topic_id, **overrides):
    base = {
        "observation_id": oid,
        "topic_id": topic_id,
        "supporting_refs": [],
        "contradicting_refs": [],
    }
    base.update(overrides)
    return base


TOPICS = {"T-01": {"topic_id": "T-01"}, "T-02": {"topic_id": "T-02"}}


def test_no_refs_produces_no_warnings():
    observations = {"OBS-001": _obs("OBS-001", "T-01")}
    assert check_dangling_refs(TOPICS, observations) == []


def test_valid_internal_observation_ref_is_accepted():
    observations = {
        "OBS-001": _obs("OBS-001", "T-01", contradicting_refs=["OBS-002"]),
        "OBS-002": _obs("OBS-002", "T-01"),
    }
    assert check_dangling_refs(TOPICS, observations) == []


def test_valid_internal_topic_ref_is_accepted():
    observations = {"OBS-001": _obs("OBS-001", "T-01", supporting_refs=["T-02"])}
    assert check_dangling_refs(TOPICS, observations) == []


def test_dangling_observation_ref_is_rejected():
    observations = {"OBS-001": _obs("OBS-001", "T-01", contradicting_refs=["OBS-999"])}
    with pytest.raises(CorpusError, match="unknown observation_id"):
        check_dangling_refs(TOPICS, observations)


def test_dangling_topic_ref_is_rejected():
    observations = {"OBS-001": _obs("OBS-001", "T-01", supporting_refs=["T-99"])}
    with pytest.raises(CorpusError, match="unknown topic_id"):
        check_dangling_refs(TOPICS, observations)


def test_ref_with_anchor_and_free_text_normalizes_before_checking():
    observations = {
        "OBS-001": _obs("OBS-001", "T-01", contradicting_refs=["OBS-999#some note explaining why"]),
    }
    with pytest.raises(CorpusError, match="unknown observation_id"):
        check_dangling_refs(TOPICS, observations)


def test_external_doc_ref_is_not_checked_at_all():
    observations = {
        "OBS-001": _obs(
            "OBS-001",
            "T-01",
            contradicting_refs=["docs/decisions/some-note.md#anchor text here"],
        )
    }
    assert check_dangling_refs(TOPICS, observations) == []


@pytest.mark.parametrize("typo_ref", ["Obs-001", "OBS001", "obs-001", "T01", "t-01"])
def test_ambiguous_id_shaped_ref_is_a_warning_not_an_error(typo_ref):
    observations = {"OBS-001": _obs("OBS-001", "T-01", contradicting_refs=[typo_ref])}
    warnings = check_dangling_refs(TOPICS, observations)
    assert len(warnings) == 1
    assert "OBS-001.contradicting_refs" in warnings[0]


def test_normalize_ref_target_strips_anchor_and_trailing_text():
    assert normalize_ref_target("OBS-014#some anchor text") == "OBS-014"
    assert normalize_ref_target("OBS-014 because of X") == "OBS-014"
    assert normalize_ref_target("OBS-014") == "OBS-014"
