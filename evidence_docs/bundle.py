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
)
from .errors import CorpusError
from .gitio import BlobDigestCache
from .render_md import render_markdown, render_overview_md, update_readme_counts_table
from .schema import is_full_git_sha, is_valid_iso8601_utc, sha256_hex
from .schema import SOURCE_KINDS_REPO_INTERNAL

GENERATOR_NAME = "evidence-docs"


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    lines = [json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


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
    warnings = verify_content_digests_against_commit(observations, repo_commit, repo_root, blob_cache)
    return ValidationResult(corpus=corpus, warnings=warnings)


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
    gaps_out = build_gaps(gaps)

    readme_path = corpus_dir / "README.md"
    if readme_path.is_file():
        update_readme_counts_table(readme_path, claims)

    site_dir = corpus_dir / "site"
    bundle_dir = corpus_dir / "bundle"
    site_dir.mkdir(exist_ok=True)
    bundle_dir.mkdir(exist_ok=True)

    write_jsonl(bundle_dir / "claims.jsonl", claims)
    write_jsonl(bundle_dir / "relations.jsonl", relations)
    write_jsonl(bundle_dir / "evidence.jsonl", evidence)
    write_jsonl(bundle_dir / "conflicts.jsonl", conflicts)
    write_json(bundle_dir / "gaps.json", gaps_out)

    corpus_digest = sha256_hex(
        "\n".join(
            (bundle_dir / name).read_text(encoding="utf-8")
            for name in ("claims.jsonl", "relations.jsonl", "evidence.jsonl", "conflicts.jsonl", "gaps.json")
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
    write_json(bundle_dir / "manifest.json", manifest)
    (bundle_dir / "overview.md").write_text(
        render_overview_md(topics, claims, generated_at, repo_commit), encoding="utf-8"
    )

    rel = os.path.relpath(repo_root, site_dir)
    repo_relative_prefix = "./" if rel == "." else rel.replace(os.sep, "/") + "/"

    if regen_command is None:
        regen_command = (
            f"evidence-docs generate {corpus_dir} "
            f"--generated-at {generated_at} --repo-commit {repo_commit}"
        )

    (site_dir / "index.md").write_text(
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
        encoding="utf-8",
    )

    return GenerateResult(claims=claims, topics=topics, manifest=manifest, warnings=result.warnings)
