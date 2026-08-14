"""run_context_query() over a synthetic bundle (no generate() needed)."""

from __future__ import annotations

import json

import pytest

from evidence_docs.context import run_context_query
from evidence_docs.errors import CorpusError


def _claim(oid, topic_id, affected_paths=None, size_pad=0):
    return {
        "observation_id": oid,
        "topic_id": topic_id,
        "affected_paths": affected_paths or [],
        "statement": "x" * size_pad,
    }


def _write_bundle(tmp_path, claims, relations):
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "claims.jsonl").write_text(
        "\n".join(json.dumps(c) for c in claims) + ("\n" if claims else ""), encoding="utf-8"
    )
    (bundle_dir / "relations.jsonl").write_text(
        "\n".join(json.dumps(r) for r in relations) + ("\n" if relations else ""), encoding="utf-8"
    )
    return bundle_dir


def test_matches_by_affected_path_intersection(tmp_path):
    claims = [
        _claim("OBS-001", "T-01", ["src/a.py"]),
        _claim("OBS-002", "T-01", ["src/b.py"]),
    ]
    bundle_dir = _write_bundle(tmp_path, claims, [])
    result = run_context_query(bundle_dir, {"seeds": {"paths": ["src/a.py"]}})
    assert [c["observation_id"] for c in result["claims"]] == ["OBS-001"]
    assert result["matched_topic_ids"] == ["T-01"]
    assert result["truncated"] is False


def test_matches_by_seed_topic_ids(tmp_path):
    claims = [_claim("OBS-001", "T-01"), _claim("OBS-002", "T-02")]
    bundle_dir = _write_bundle(tmp_path, claims, [])
    result = run_context_query(bundle_dir, {"seeds": {"topic_ids": ["T-02"]}})
    assert [c["observation_id"] for c in result["claims"]] == ["OBS-002"]


def test_one_hop_expansion_across_topic_related_to_topic_both_directions(tmp_path):
    claims = [
        _claim("OBS-001", "T-01"),
        _claim("OBS-002", "T-02"),
        _claim("OBS-003", "T-03"),
    ]
    relations = [
        {"type": "topic_related_to_topic", "from": "T-01", "to": "T-02"},
        {"type": "topic_related_to_topic", "from": "T-03", "to": "T-01"},
    ]
    bundle_dir = _write_bundle(tmp_path, claims, relations)
    result = run_context_query(bundle_dir, {"seeds": {"topic_ids": ["T-01"]}})
    matched = {c["observation_id"] for c in result["claims"]}
    # T-01 seeded directly; T-02 via from=T-01; T-03 via to=T-01 (reverse direction).
    assert matched == {"OBS-001", "OBS-002", "OBS-003"}


def test_two_hop_is_not_included(tmp_path):
    claims = [_claim("OBS-001", "T-01"), _claim("OBS-002", "T-02"), _claim("OBS-003", "T-03")]
    relations = [
        {"type": "topic_related_to_topic", "from": "T-01", "to": "T-02"},
        {"type": "topic_related_to_topic", "from": "T-02", "to": "T-03"},
    ]
    bundle_dir = _write_bundle(tmp_path, claims, relations)
    result = run_context_query(bundle_dir, {"seeds": {"topic_ids": ["T-01"]}})
    matched = {c["observation_id"] for c in result["claims"]}
    assert matched == {"OBS-001", "OBS-002"}  # T-03 is 2 hops away


def test_path_matches_ranked_before_hop_expansion(tmp_path):
    claims = [
        _claim("OBS-002", "T-02"),
        _claim("OBS-001", "T-01", ["src/a.py"]),
    ]
    relations = [{"type": "topic_related_to_topic", "from": "T-01", "to": "T-02"}]
    bundle_dir = _write_bundle(tmp_path, claims, relations)
    result = run_context_query(bundle_dir, {"seeds": {"paths": ["src/a.py"]}})
    ids_in_order = [c["observation_id"] for c in result["claims"]]
    assert ids_in_order == ["OBS-001", "OBS-002"]


def test_no_seeds_matches_nothing(tmp_path):
    claims = [_claim("OBS-001", "T-01")]
    bundle_dir = _write_bundle(tmp_path, claims, [])
    result = run_context_query(bundle_dir, {})
    assert result["claims"] == []
    assert result["truncated"] is False


def test_token_budget_always_keeps_at_least_one_claim(tmp_path):
    claims = [_claim("OBS-001", "T-01", ["src/a.py"], size_pad=10_000)]
    bundle_dir = _write_bundle(tmp_path, claims, [])
    result = run_context_query(bundle_dir, {"seeds": {"paths": ["src/a.py"]}, "token_budget": 1})
    assert len(result["claims"]) == 1
    assert result["truncated"] is True


def test_missing_bundle_raises_helpful_error(tmp_path):
    with pytest.raises(CorpusError, match="run `evidence-docs generate`"):
        run_context_query(tmp_path / "bundle", {"seeds": {"paths": ["x"]}})
