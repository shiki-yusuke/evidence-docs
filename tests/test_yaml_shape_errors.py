"""Malformed corpus YAML (empty files, missing keys, wrong types) must raise
CorpusError naming the offending file -- never a bare KeyError/TypeError/
AttributeError traceback out of the public validate/generate commands."""

from __future__ import annotations

from pathlib import Path

import pytest

from evidence_docs.bundle import generate
from evidence_docs.corpus import load_corpus
from evidence_docs.errors import CorpusError


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _minimal_valid_corpus(dir_path: Path) -> None:
    _write(
        dir_path / "id-registry.yaml",
        "schema_version: '1.0'\ntopics:\n  T-01: {slug: x, minted_at: '2026-08-01'}\n"
        "observations:\n  OBS-001: {topic_id: T-01, minted_at: '2026-08-01'}\n",
    )
    _write(
        dir_path / "topics" / "T-01.yaml",
        "topic_id: T-01\ntitle: x\ndescription: x\nrelated_topics: []\n",
    )
    _write(
        dir_path / "observations" / "T-01.yaml",
        """\
topic_id: T-01
observations:
  - observation_id: OBS-001
    topic_id: T-01
    claim_kind: behavior
    statement: x
    origin: reconstructed
    epistemic_status: execution_verified
    review_status: unreviewed
    conformance_status: matched
    provenance:
      - source_kind: source
        uri: src/x.py
        content_digest: "{digest}"
        repo_commit: "{sha}"
        observed_at: "2026-08-01T00:00:00Z"
    valid_at_commit: "{sha}"
    affected_paths: [src/x.py]
""".format(digest="a" * 64, sha="f" * 40),
    )
    _write(dir_path / "gaps.yaml", "schema_version: '1.0'\ngaps: []\n")


def test_baseline_minimal_corpus_loads(tmp_path):
    _minimal_valid_corpus(tmp_path)
    load_corpus(tmp_path)  # must not raise


def test_empty_id_registry_file_raises_corpus_error_not_traceback(tmp_path):
    _minimal_valid_corpus(tmp_path)
    _write(tmp_path / "id-registry.yaml", "")  # yaml.safe_load("") -> None
    with pytest.raises(CorpusError, match="id-registry.yaml"):
        load_corpus(tmp_path)


def test_id_registry_missing_observations_key_raises_corpus_error(tmp_path):
    _minimal_valid_corpus(tmp_path)
    _write(
        tmp_path / "id-registry.yaml",
        "schema_version: '1.0'\ntopics:\n  T-01: {slug: x, minted_at: '2026-08-01'}\n",
    )
    with pytest.raises(CorpusError, match="id-registry.yaml"):
        load_corpus(tmp_path)


def test_id_registry_wrong_type_raises_corpus_error(tmp_path):
    _minimal_valid_corpus(tmp_path)
    _write(tmp_path / "id-registry.yaml", "- just\n- a\n- list\n")
    with pytest.raises(CorpusError, match="id-registry.yaml"):
        load_corpus(tmp_path)


def test_empty_topic_file_raises_corpus_error_naming_the_file(tmp_path):
    _minimal_valid_corpus(tmp_path)
    _write(tmp_path / "topics" / "T-01.yaml", "")
    with pytest.raises(CorpusError, match="T-01.yaml"):
        load_corpus(tmp_path)


def test_topic_missing_topic_id_key_raises_corpus_error(tmp_path):
    _minimal_valid_corpus(tmp_path)
    _write(tmp_path / "topics" / "T-01.yaml", "title: x\ndescription: x\n")
    with pytest.raises(CorpusError, match="T-01.yaml"):
        load_corpus(tmp_path)


def test_topic_related_topics_wrong_type_raises_corpus_error(tmp_path):
    _minimal_valid_corpus(tmp_path)
    _write(
        tmp_path / "topics" / "T-01.yaml",
        "topic_id: T-01\ntitle: x\ndescription: x\nrelated_topics: not-a-list\n",
    )
    with pytest.raises(CorpusError, match="T-01.yaml"):
        load_corpus(tmp_path)


def test_empty_observations_file_raises_corpus_error(tmp_path):
    _minimal_valid_corpus(tmp_path)
    _write(tmp_path / "observations" / "T-01.yaml", "")
    with pytest.raises(CorpusError, match="T-01.yaml"):
        load_corpus(tmp_path)


def test_observations_file_missing_observations_key_raises_corpus_error(tmp_path):
    _minimal_valid_corpus(tmp_path)
    _write(tmp_path / "observations" / "T-01.yaml", "topic_id: T-01\n")
    with pytest.raises(CorpusError, match="T-01.yaml"):
        load_corpus(tmp_path)


def test_observation_entry_as_scalar_string_raises_corpus_error(tmp_path):
    _minimal_valid_corpus(tmp_path)
    _write(
        tmp_path / "observations" / "T-01.yaml",
        "topic_id: T-01\nobservations:\n  - just a string, not a mapping\n",
    )
    with pytest.raises(CorpusError, match="T-01.yaml"):
        load_corpus(tmp_path)


def test_empty_gaps_file_raises_corpus_error(tmp_path):
    _minimal_valid_corpus(tmp_path)
    _write(tmp_path / "gaps.yaml", "")
    with pytest.raises(CorpusError, match="gaps.yaml"):
        load_corpus(tmp_path)


def test_gaps_missing_gaps_key_raises_corpus_error(tmp_path):
    _minimal_valid_corpus(tmp_path)
    _write(tmp_path / "gaps.yaml", "schema_version: '1.0'\n")
    with pytest.raises(CorpusError, match="gaps.yaml"):
        load_corpus(tmp_path)


def test_generate_raises_corpus_error_when_a_gap_entry_is_missing_its_id(mini_domain):
    """load_corpus() only checks that gaps.yaml has a top-level "gaps" list;
    build_gaps() (called later, during generate()) sorts by g["id"], which
    would otherwise raise a bare KeyError for a gap entry missing that key."""

    import yaml

    gaps_path = mini_domain.corpus_dir / "gaps.yaml"
    doc = yaml.safe_load(gaps_path.read_text(encoding="utf-8"))
    del doc["gaps"][0]["id"]
    gaps_path.write_text(yaml.safe_dump(doc), encoding="utf-8")

    with pytest.raises(CorpusError, match="gaps.yaml"):
        generate(mini_domain.corpus_dir, "2026-08-09T10:30:00Z", mini_domain.repo_commit, mini_domain.repo_root)


def test_id_registry_entry_missing_topic_id_key_raises_corpus_error(tmp_path):
    _minimal_valid_corpus(tmp_path)
    _write(
        tmp_path / "id-registry.yaml",
        "schema_version: '1.0'\ntopics:\n  T-01: {slug: x, minted_at: '2026-08-01'}\n"
        "observations:\n  OBS-001: {minted_at: '2026-08-01'}\n",  # topic_id missing
    )
    with pytest.raises(CorpusError):
        load_corpus(tmp_path)
