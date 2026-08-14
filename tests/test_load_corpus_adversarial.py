"""Adversarial cases for load_corpus(): ID registry cross-checks and
dangling related_topics references."""

from __future__ import annotations

from pathlib import Path

import pytest

from evidence_docs.corpus import load_corpus
from evidence_docs.errors import CorpusError

VALID_OBS_YAML = """\
topic_id: T-01
observations:
  - observation_id: OBS-001
    topic_id: T-01
    claim_kind: behavior
    statement: example
    origin: reconstructed
    epistemic_status: execution_verified
    review_status: unreviewed
    conformance_status: matched
    provenance:
      - source_kind: source
        uri: src/example.py
        content_digest: "{digest}"
        repo_commit: "{sha}"
        observed_at: "2026-08-01T00:00:00Z"
    valid_at_commit: "{sha}"
    affected_paths: [src/example.py]
"""

DIGEST = "a" * 64
SHA = "f" * 40


def _write_corpus(dir_path: Path, *, id_registry: str, topics: dict, observations: dict, gaps: str = None):
    (dir_path / "topics").mkdir(parents=True, exist_ok=True)
    (dir_path / "observations").mkdir(parents=True, exist_ok=True)
    (dir_path / "id-registry.yaml").write_text(id_registry, encoding="utf-8")
    (dir_path / "gaps.yaml").write_text(gaps or "schema_version: '1.0'\ngaps: []\n", encoding="utf-8")
    for name, text in topics.items():
        (dir_path / "topics" / name).write_text(text, encoding="utf-8")
    for name, text in observations.items():
        (dir_path / "observations" / name).write_text(text, encoding="utf-8")


def _valid_topic(tid="T-01", related=None):
    related_yaml = f"related_topics: [{', '.join(related)}]" if related else "related_topics: []"
    return f"""\
topic_id: {tid}
title: Example topic
description: an example
{related_yaml}
"""


def test_valid_minimal_corpus_loads(tmp_path):
    _write_corpus(
        tmp_path,
        id_registry="schema_version: '1.0'\ntopics:\n  T-01: {slug: x, minted_at: '2026-08-01'}\n"
        "observations:\n  OBS-001: {topic_id: T-01, minted_at: '2026-08-01'}\n",
        topics={"T-01.yaml": _valid_topic()},
        observations={"T-01.yaml": VALID_OBS_YAML.format(digest=DIGEST, sha=SHA)},
    )
    corpus = load_corpus(tmp_path)
    assert list(corpus.topics) == ["T-01"]
    assert list(corpus.observations) == ["OBS-001"]


def test_rejects_topic_not_in_id_registry(tmp_path):
    _write_corpus(
        tmp_path,
        id_registry="schema_version: '1.0'\ntopics: {}\nobservations: {}\n",
        topics={"T-01.yaml": _valid_topic()},
        observations={},
    )
    with pytest.raises(CorpusError, match="not in id-registry"):
        load_corpus(tmp_path)


def test_rejects_observation_id_not_in_id_registry(tmp_path):
    _write_corpus(
        tmp_path,
        id_registry="schema_version: '1.0'\ntopics:\n  T-01: {slug: x, minted_at: '2026-08-01'}\n"
        "observations: {}\n",
        topics={"T-01.yaml": _valid_topic()},
        observations={"T-01.yaml": VALID_OBS_YAML.format(digest=DIGEST, sha=SHA)},
    )
    with pytest.raises(CorpusError, match="not in id-registry"):
        load_corpus(tmp_path)


def test_rejects_topic_id_mismatch_between_registry_and_observation(tmp_path):
    _write_corpus(
        tmp_path,
        id_registry="schema_version: '1.0'\ntopics:\n  T-01: {slug: x, minted_at: '2026-08-01'}\n"
        "  T-02: {slug: y, minted_at: '2026-08-01'}\n"
        "observations:\n  OBS-001: {topic_id: T-02, minted_at: '2026-08-01'}\n",
        topics={"T-01.yaml": _valid_topic(), "T-02.yaml": _valid_topic("T-02")},
        observations={"T-01.yaml": VALID_OBS_YAML.format(digest=DIGEST, sha=SHA)},
    )
    with pytest.raises(CorpusError, match="topic_id mismatch"):
        load_corpus(tmp_path)


def test_rejects_duplicate_topic_id(tmp_path):
    _write_corpus(
        tmp_path,
        id_registry="schema_version: '1.0'\ntopics:\n  T-01: {slug: x, minted_at: '2026-08-01'}\n"
        "observations: {}\n",
        topics={"a.yaml": _valid_topic(), "b.yaml": _valid_topic()},
        observations={},
    )
    with pytest.raises(CorpusError, match="duplicate topic_id"):
        load_corpus(tmp_path)


def test_rejects_id_registry_declaring_topic_never_defined(tmp_path):
    _write_corpus(
        tmp_path,
        id_registry="schema_version: '1.0'\ntopics:\n  T-01: {slug: x, minted_at: '2026-08-01'}\n"
        "  T-99: {slug: ghost, minted_at: '2026-08-01'}\n"
        "observations: {}\n",
        topics={"T-01.yaml": _valid_topic()},
        observations={},
    )
    with pytest.raises(CorpusError, match="never defined"):
        load_corpus(tmp_path)


def test_rejects_dangling_related_topics_reference(tmp_path):
    _write_corpus(
        tmp_path,
        id_registry="schema_version: '1.0'\ntopics:\n  T-01: {slug: x, minted_at: '2026-08-01'}\n"
        "observations: {}\n",
        topics={"T-01.yaml": _valid_topic(related=["T-99"])},
        observations={},
    )
    with pytest.raises(CorpusError, match="unknown topic_id"):
        load_corpus(tmp_path)
