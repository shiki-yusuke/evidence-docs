"""Regression tests for what `evidence-docs init` scaffolds.

Two things are pinned down here that manual review alone won't catch:

1. `validate` must pass immediately after `init`, with no hand-editing --
   this is `init`'s core contract (an empty-but-valid corpus), and is
   exercised through the real `evidence_docs.bundle.validate` entry point,
   not a re-implementation of its checks.
2. EXAMPLE.md's enum reference tables (the "what are the valid values for
   this field" tables an author had no other way to discover short of
   reading evidence_docs/schema.py directly) must never silently drift from
   the schema.py sets that `validate` actually enforces. init_templates.py
   generates these tables from schema.py at scaffold time specifically to
   make that drift structurally impossible; this test is the regression
   guard in case a future edit replaces that generation with a hand-typed,
   driftable string instead.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

import yaml

from evidence_docs.bundle import validate
from evidence_docs.init_templates import scaffold
from evidence_docs.schema import (
    ALL_SOURCE_KINDS,
    CLAIM_KINDS,
    CONFORMANCE_STATUSES,
    EPISTEMIC_STATUSES,
    ORIGINS,
    REVIEW_STATUSES,
)

_ENUM_BLOCK_RE = re.compile(
    r"<!-- AUTO-GENERATED:ENUM:(?P<name>[a-z_]+):START.*?-->\n"
    r"(?P<body>.*?)\n"
    r"<!-- AUTO-GENERATED:ENUM:(?P=name):END -->",
    re.DOTALL,
)


def _parse_enum_blocks(text: str) -> dict[str, set[str]]:
    blocks: dict[str, set[str]] = {}
    for m in _ENUM_BLOCK_RE.finditer(text):
        values = {v.strip().strip("`") for v in m.group("body").split(",")}
        blocks[m.group("name")] = values
    return blocks


def test_validate_passes_immediately_after_init(tmp_path):
    corpus_dir = tmp_path / "corpus"
    scaffold(corpus_dir, "2026-08-15")

    result = validate(corpus_dir, "f" * 40, corpus_dir)

    assert result.corpus.observations == {}
    assert result.corpus.topics == {}
    assert result.warnings == []


def test_example_md_enum_reference_matches_schema(tmp_path):
    corpus_dir = tmp_path / "corpus"
    scaffold(corpus_dir, "2026-08-15")
    example_path = corpus_dir / "EXAMPLE.md"
    assert example_path.is_file()
    text = example_path.read_text(encoding="utf-8")

    expected = {
        "claim_kind": CLAIM_KINDS,
        "origin": ORIGINS,
        "epistemic_status": EPISTEMIC_STATUSES,
        "conformance_status": CONFORMANCE_STATUSES,
        "review_status": REVIEW_STATUSES,
        "source_kind": ALL_SOURCE_KINDS,
    }

    blocks = _parse_enum_blocks(text)
    assert set(blocks) == set(expected), (
        "EXAMPLE.md's enum reference blocks don't match the fields validate() enforces "
        f"(found {sorted(blocks)}, expected {sorted(expected)})"
    )
    for name, values in expected.items():
        assert blocks[name] == values, (
            f"EXAMPLE.md's {name!r} enum reference ({sorted(blocks[name])}) has drifted from "
            f"evidence_docs.schema's live set ({sorted(values)}) -- see init_templates.py's "
            "render_example_md()"
        )


_GIT_ENV = {
    "GIT_AUTHOR_NAME": "evidence-docs tests",
    "GIT_AUTHOR_EMAIL": "tests@example.invalid",
    "GIT_COMMITTER_NAME": "evidence-docs tests",
    "GIT_COMMITTER_EMAIL": "tests@example.invalid",
}


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(_GIT_ENV)
    return subprocess.run(["git", *args], cwd=str(cwd), env=env, capture_output=True, text=True, check=True)


def test_example_md_worked_example_shape_validates_against_a_real_repo(tmp_path):
    """Copy EXAMPLE.md's three shapes verbatim (substituting REPLACE_ME the
    way its own instructions say to), point provenance at one real file in a
    real repo, and confirm the result actually passes `validate` -- proving
    the shape EXAMPLE.md teaches is not just internally consistent prose but
    a real corpus `evidence_docs.bundle.validate` accepts."""

    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "foo.py").write_text(
        'def greet(name):\n    return f"Hello, {name}!"\n', encoding="utf-8"
    )
    _git(["init", "-q", "-b", "main"], repo_root)
    _git(["add", "-A"], repo_root)
    _git(["-c", "commit.gpgsign=false", "commit", "-q", "-m", "initial"], repo_root)
    commit = _git(["rev-parse", "HEAD"], repo_root).stdout.strip()
    digest = hashlib.sha256((repo_root / "src" / "foo.py").read_bytes()).hexdigest()

    corpus_dir = repo_root / "docs-claims"
    scaffold(corpus_dir, "2026-08-15")

    registry = {
        "schema_version": "1.0",
        "minted_at_default": "2026-08-15",
        "topics": {"T-01": {"slug": "greet-format", "minted_at": "2026-08-15"}},
        "observations": {"OBS-001": {"topic_id": "T-01", "minted_at": "2026-08-15"}},
    }
    (corpus_dir / "id-registry.yaml").write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

    topic = {
        "topic_id": "T-01",
        "title": "greet() greeting format",
        "description": "What greet(name) returns for a given name.",
        "representative_symbols": ["greet"],
        "representative_paths": ["src/foo.py"],
        "related_topics": [],
    }
    (corpus_dir / "topics" / "T-01-greet-format.yaml").write_text(
        yaml.safe_dump(topic, sort_keys=False), encoding="utf-8"
    )

    observation = {
        "observation_id": "OBS-001",
        "topic_id": "T-01",
        "claim_kind": "behavior",
        "statement": "greet(name) returns the string 'Hello, {name}!' for any name.",
        "origin": "reconstructed",
        "epistemic_status": "execution_verified",
        "review_status": "unreviewed",
        "conformance_status": "matched",
        "subject_refs": ["greet"],
        "supporting_refs": [],
        "contradicting_refs": [],
        "valid_at_commit": commit,
        "affected_paths": ["src/foo.py"],
        "provenance": [
            {
                "source_kind": "source",
                "uri": "src/foo.py",
                "selector": "greet",
                "content_digest": digest,
                "repo_commit": commit,
                "extraction_method": "static-read-source",
                "observed_at": "2026-08-15T00:00:00Z",
            }
        ],
    }
    (corpus_dir / "observations" / "T-01-greet-format.yaml").write_text(
        yaml.safe_dump({"observations": [observation]}, sort_keys=False), encoding="utf-8"
    )

    result = validate(corpus_dir, commit, repo_root)

    assert list(result.corpus.observations) == ["OBS-001"]
    assert list(result.corpus.topics) == ["T-01"]
    assert result.warnings == []
