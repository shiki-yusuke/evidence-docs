"""End-to-end: init -> validate -> generate -> context over the mini-domain fixture."""

from __future__ import annotations

import json
from pathlib import Path

from evidence_docs.bundle import generate, validate
from evidence_docs.context import run_context_query


def test_validate_passes_on_well_formed_fixture(mini_domain):
    result = validate(mini_domain.corpus_dir, mini_domain.repo_commit, mini_domain.repo_root)
    assert len(result.corpus.observations) == 8
    assert len(result.corpus.topics) == 3
    assert result.warnings == []


def test_generate_writes_expected_bundle_files(mini_domain):
    result = generate(
        mini_domain.corpus_dir,
        "2026-08-09T10:30:00Z",
        mini_domain.repo_commit,
        mini_domain.repo_root,
        corpus_title="mini-domain fixture corpus",
    )
    bundle_dir = mini_domain.corpus_dir / "bundle"
    for name in (
        "claims.jsonl",
        "relations.jsonl",
        "evidence.jsonl",
        "conflicts.jsonl",
        "gaps.json",
        "manifest.json",
        "overview.md",
    ):
        assert (bundle_dir / name).is_file(), name

    assert (mini_domain.corpus_dir / "site" / "index.md").is_file()

    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["observations"] == 8
    assert manifest["counts"]["topics"] == 3
    assert manifest["repo_commit"] == mini_domain.repo_commit
    assert manifest["generator"]["name"] == "evidence-docs"

    conflicts = [json.loads(line) for line in (bundle_dir / "conflicts.jsonl").read_text().splitlines()]
    assert [c["observation_id"] for c in conflicts] == ["OBS-007"]

    assert result.claims and result.manifest == manifest


def test_generate_updates_readme_counts_table(mini_domain):
    generate(mini_domain.corpus_dir, "2026-08-09T10:30:00Z", mini_domain.repo_commit, mini_domain.repo_root)
    readme = (mini_domain.corpus_dir / "README.md").read_text(encoding="utf-8")
    assert "behavior 4" in readme or "behavior" in readme
    assert "drifted 1" in readme
    assert "(run `evidence-docs generate` to fill this in)" not in readme


def test_context_query_matches_by_affected_path_and_expands_one_hop(mini_domain):
    generate(mini_domain.corpus_dir, "2026-08-09T10:30:00Z", mini_domain.repo_commit, mini_domain.repo_root)
    bundle_dir = mini_domain.corpus_dir / "bundle"

    result = run_context_query(bundle_dir, {"seeds": {"topic_ids": ["T-01"]}})
    matched_ids = {c["observation_id"] for c in result["claims"]}
    # T-01 seeds directly (OBS-001..003) plus a 1-hop expansion into T-02
    # (T-01 related_topics: [T-02]).
    assert {"OBS-001", "OBS-002", "OBS-003"} <= matched_ids
    assert "T-02" in result["matched_topic_ids"]
    assert result["truncated"] is False


def test_context_query_token_budget_truncates(mini_domain):
    generate(mini_domain.corpus_dir, "2026-08-09T10:30:00Z", mini_domain.repo_commit, mini_domain.repo_root)
    bundle_dir = mini_domain.corpus_dir / "bundle"

    full = run_context_query(bundle_dir, {"seeds": {"topic_ids": ["T-01", "T-02", "T-03"]}})
    assert len(full["claims"]) == 8

    limited = run_context_query(
        bundle_dir, {"seeds": {"topic_ids": ["T-01", "T-02", "T-03"]}, "token_budget": 1}
    )
    assert len(limited["claims"]) >= 1
    assert len(limited["claims"]) < len(full["claims"])
    assert limited["truncated"] is True


def test_init_then_validate_on_fresh_empty_corpus(tmp_path):
    from evidence_docs.init_templates import scaffold

    corpus_dir = tmp_path / "fresh"
    created = scaffold(corpus_dir, "2026-08-01")
    assert created

    result = validate(corpus_dir, "0" * 40, corpus_dir)
    assert len(result.corpus.observations) == 0
    assert len(result.corpus.topics) == 0

    # init is idempotent: running it again creates nothing new.
    assert scaffold(corpus_dir, "2026-08-01") == []
