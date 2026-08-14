"""Orchestrates validate/generate: ties corpus loading, git blob verification,
bundle/manifest writing, and the site/index.md projection together.

GENERATED_AT and REPO_COMMIT are always caller-supplied (CLI arguments) and
never derived from `datetime.now()` or `git rev-parse` at run time -- that is
what makes generate() deterministic: same inputs + same arguments always
produce byte-identical output.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import __version__
from .corpus import (
    build_claims,
    build_conflicts,
    build_evidence,
    build_gaps,
    build_relations,
    counts_by,
    find_repo_commit_mismatches,
    load_corpus,
    verify_content_digests_against_commit,
    yaml_shape_guard,
)
from .errors import CorpusError
from .gitio import BlobDigestCache, resolve_write_path
from .render_md import render_markdown, render_overview_md, update_readme_counts_table
from .schema import is_full_git_sha, is_valid_iso8601_utc, sha256_hex
from .schema import SOURCE_KINDS_REPO_INTERNAL

GENERATOR_NAME = "evidence-docs"


def write_json(corpus_dir: Path, relative: str, obj) -> Path:
    """Write JSON under corpus_dir at `relative`, refusing to follow a
    symlink out of corpus_dir (see gitio.resolve_write_path)."""

    path = resolve_write_path(corpus_dir, relative)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_jsonl(corpus_dir: Path, relative: str, rows: list[dict]) -> Path:
    path = resolve_write_path(corpus_dir, relative)
    lines = [json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def write_text(corpus_dir: Path, relative: str, text: str) -> Path:
    path = resolve_write_path(corpus_dir, relative)
    path.write_text(text, encoding="utf-8")
    return path


def resolve_repo_root(corpus_dir: Path, repo_root_arg: str | None) -> Path:
    """Resolve --repo-root. A relative path is resolved against corpus_dir
    (not the process cwd) -- this replaces the pilot's hardcoded
    `../../../..` depth with an explicit, corpus-relative default.

    With no --repo-root given, the corpus directory itself is treated as the
    repo root (the common case for a small/standalone project where docs and
    source share one tree).
    """

    if repo_root_arg is None:
        return corpus_dir
    p = Path(repo_root_arg)
    if p.is_absolute():
        return p
    return (corpus_dir / p).resolve()


class ValidationResult:
    def __init__(self, corpus, warnings: list[str]):
        self.corpus = corpus
        self.warnings = warnings


def validate(corpus_dir: Path, repo_commit: str, repo_root: Path) -> ValidationResult:
    """Run every corpus check (load + repo-commit consistency + git blob
    hashing) without writing any output. Raises CorpusError on the first
    fatal problem; returns non-fatal worktree-drift warnings otherwise.
    """

    if not is_full_git_sha(repo_commit):
        raise CorpusError(f"--repo-commit must be a 40-character hex git SHA, got {repo_commit!r}")

    corpus = load_corpus(corpus_dir)
    observations = corpus.observations

    mismatches = find_repo_commit_mismatches(observations, repo_commit)
    if mismatches:
        detail = "\n".join(f"  - {m}" for m in mismatches)
        raise CorpusError(
            f"--repo-commit={repo_commit!r} does not match {len(mismatches)} value(s) "
            f"recorded in the corpus:\n{detail}"
        )

    blob_cache = BlobDigestCache(repo_root)
    drift_warnings = verify_content_digests_against_commit(observations, repo_commit, repo_root, blob_cache)
    return ValidationResult(corpus=corpus, warnings=corpus.ref_warnings + drift_warnings)


class GenerateResult:
    def __init__(self, claims: list[dict], topics: dict, manifest: dict, warnings: list[str]):
        self.claims = claims
        self.topics = topics
        self.manifest = manifest
        self.warnings = warnings


def generate(
    corpus_dir: Path,
    generated_at: str,
    repo_commit: str,
    repo_root: Path,
    corpus_title: str = "claim corpus",
    regen_command: str | None = None,
) -> GenerateResult:
    if not is_valid_iso8601_utc(generated_at):
        raise CorpusError(
            "--generated-at must be a UTC-offset ISO 8601 datetime "
            f"(e.g. 2026-08-09T10:30:00Z), got {generated_at!r}"
        )

    result = validate(corpus_dir, repo_commit, repo_root)
    corpus = result.corpus
    topics = corpus.topics
    observations = corpus.observations
    gaps = corpus.gaps

    claims = build_claims(observations)
    relations = build_relations(topics, observations)
    evidence = build_evidence(observations)
    conflicts = build_conflicts(observations)
    with yaml_shape_guard(corpus_dir / "gaps.yaml"):
        gaps_out = build_gaps(gaps)

    # resolve_write_path guards every write below against a symlinked site/
    # or bundle/ directory (or a symlinked README.md) redirecting output
    # outside corpus_dir -- see gitio.resolve_write_path.
    readme_resolved = resolve_write_path(corpus_dir, "README.md")
    if readme_resolved.is_file():
        update_readme_counts_table(readme_resolved, claims)

    site_dir = resolve_write_path(corpus_dir, "site")
    bundle_dir = resolve_write_path(corpus_dir, "bundle")
    site_dir.mkdir(exist_ok=True)
    bundle_dir.mkdir(exist_ok=True)

    claims_path = write_jsonl(corpus_dir, "bundle/claims.jsonl", claims)
    relations_path = write_jsonl(corpus_dir, "bundle/relations.jsonl", relations)
    evidence_path = write_jsonl(corpus_dir, "bundle/evidence.jsonl", evidence)
    conflicts_path = write_jsonl(corpus_dir, "bundle/conflicts.jsonl", conflicts)
    gaps_path_out = write_json(corpus_dir, "bundle/gaps.json", gaps_out)

    corpus_digest = sha256_hex(
        "\n".join(
            p.read_text(encoding="utf-8")
            for p in (claims_path, relations_path, evidence_path, conflicts_path, gaps_path_out)
        )
    )

    manifest = {
        "generated_at": generated_at,
        "repo_commit": repo_commit,
        "generator": {"name": GENERATOR_NAME, "version": __version__},
        "corpus_digest": corpus_digest,
        "counts": {
            "topics": len(topics),
            "observations": len(claims),
            "by_claim_kind": counts_by(claims, "claim_kind"),
            "by_origin": counts_by(claims, "origin"),
            "by_epistemic_status": counts_by(claims, "epistemic_status"),
            "by_conformance_status": counts_by(claims, "conformance_status"),
        },
    }
    write_json(corpus_dir, "bundle/manifest.json", manifest)
    write_text(corpus_dir, "bundle/overview.md", render_overview_md(topics, claims, generated_at, repo_commit))

    rel = os.path.relpath(repo_root, site_dir)
    repo_relative_prefix = "./" if rel == "." else rel.replace(os.sep, "/") + "/"

    if regen_command is None:
        # Deliberately uses "." rather than corpus_dir's absolute path: the
        # generated output must be a pure function of corpus content +
        # arguments, not of where the corpus happens to sit on disk (two
        # byte-identical copies of the same corpus at different paths must
        # produce byte-identical site/index.md).
        regen_command = (
            "evidence-docs generate . "
            f"--generated-at {generated_at} --repo-commit {repo_commit}"
        )

    write_text(
        corpus_dir,
        "site/index.md",
        render_markdown(
            topics,
            observations,
            generated_at,
            repo_commit,
            repo_relative_prefix,
            SOURCE_KINDS_REPO_INTERNAL,
            corpus_title,
            regen_command,
        ),
    )

    return GenerateResult(claims=claims, topics=topics, manifest=manifest, warnings=result.warnings)
