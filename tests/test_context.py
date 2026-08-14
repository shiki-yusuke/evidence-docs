"""run_context_query() over a synthetic bundle (no generate() needed)."""

from __future__ import annotations

import json

import pytest

from evidence_docs.context import QueryError, run_context_query, validate_query
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


# --- validate_query() shape checks -----------------------------------------


def test_validate_query_accepts_well_formed_query():
    validate_query({"seeds": {"paths": ["a.py"], "topic_ids": ["T-01"]}, "token_budget": 100})  # no raise
    validate_query({})  # no raise


@pytest.mark.parametrize("bad_query", [None, [], "a string", 42, True])
def test_validate_query_rejects_non_object_top_level(bad_query):
    with pytest.raises(QueryError, match="must be a JSON object"):
        validate_query(bad_query)


def test_validate_query_rejects_non_object_seeds():
    with pytest.raises(QueryError, match="seeds must be an object"):
        validate_query({"seeds": ["not", "an", "object"]})


@pytest.mark.parametrize("bad_paths", [["ok", 1], "not-a-list", {"nope": True}, [None]])
def test_validate_query_rejects_malformed_seed_paths(bad_paths):
    with pytest.raises(QueryError, match="seeds.paths must be a list of strings"):
        validate_query({"seeds": {"paths": bad_paths}})


@pytest.mark.parametrize("bad_topic_ids", [[1, 2], "T-01", {"T-01": True}])
def test_validate_query_rejects_malformed_seed_topic_ids(bad_topic_ids):
    with pytest.raises(QueryError, match="seeds.topic_ids must be a list of strings"):
        validate_query({"seeds": {"topic_ids": bad_topic_ids}})


def test_validate_query_rejects_oversized_seed_list():
    with pytest.raises(QueryError, match="1000-entry limit"):
        validate_query({"seeds": {"paths": [f"p{i}.py" for i in range(1001)]}})


@pytest.mark.parametrize("bad_budget", [0, -1, "100", 1.5, True, False])
def test_validate_query_rejects_invalid_token_budget(bad_budget):
    with pytest.raises(QueryError, match="token_budget must be a positive integer"):
        validate_query({"token_budget": bad_budget})


def test_validate_query_accepts_null_token_budget():
    validate_query({"token_budget": None})  # treated as "not set", no raise


def test_validate_query_rejects_excessive_nesting():
    deeply_nested: dict = {}
    cursor = deeply_nested
    for _ in range(10):
        cursor["seeds"] = {}
        cursor = cursor["seeds"]
    with pytest.raises(QueryError, match="nested more than"):
        validate_query(deeply_nested)


def test_run_context_query_raises_query_error_for_malformed_query(tmp_path):
    bundle_dir = _write_bundle(tmp_path, [], [])
    with pytest.raises(QueryError):
        run_context_query(bundle_dir, {"seeds": {"paths": "not-a-list"}})


def test_query_error_is_a_corpus_error_subclass():
    assert issubclass(QueryError, CorpusError)
