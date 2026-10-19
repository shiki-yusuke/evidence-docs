"""Explanations: a non-authoritative, deterministically generated view of
"which known claims touch this change scope", derived from the claim corpus.

An explanation has `authority: none`. It is never hand-edited, never
referenced from the authoritative records (topics / observations / gaps /
id-registry), and goes stale -- failing validation -- as soon as the corpus
it was derived from changes. Validation never trusts a stored value: it
re-runs build_explanation() on the stored inputs (scope snapshot +
generated_at) and compares the whole file. See docs/schema.md
("Explanations (authority: none)").
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .corpus import revision_digest_of
from .errors import CorpusError
from .schema import (
    SOURCE_KINDS_REPO_INTERNAL,
    canonical_json,
    is_full_git_sha,
    is_sha256_hex,
    is_valid_iso8601_utc,
    sha256_hex,
)

EXPLANATIONS_DIR = "explanations"
SCHEMA_VERSION = "explanation/v0"
SCOPE_KIND = "impact-scan:v1"
GENERATOR_NAME = "evidence-docs"
GENERATOR_METHOD = "explain:impact-scan:v1"
TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "authority",
        "explanation_id",
        "scope",
        "corpus_commit",
        "commit_mismatch",
        "sources",
        "generator",
        "generated_at",
        "body",
    }
)
EXPLANATION_FILE_RE = re.compile(r"EXP-[0-9a-f]{16}\.json")
# What an authoritative record must never contain (rule 4).
EXPLANATION_REF_RE = re.compile(r"EXP-[0-9a-f]{16}|explanations/")

_SCOPE_REQUIRED_KEYS = {"scan_version", "repo_commit", "digest", "candidate_paths", "candidate_layers"}
_SCOPE_ALLOWED_KEYS = _SCOPE_REQUIRED_KEYS | {"open_items"}


def compute_scope_digest(candidate_paths: list, candidate_layers: list) -> str:
    """Same algorithm as lane's computeSnapshotDigest:
    sha256(utf8(JSON.stringify({candidate_paths, candidate_layers}))), key
    order as written (not sorted)."""

    payload = json.dumps(
        {"candidate_paths": candidate_paths, "candidate_layers": candidate_layers},
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return sha256_hex(payload)


def _check_str_list(value, name: str, where: str) -> None:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise CorpusError(f"{where}: {name} must be a list of strings")
    if len(set(value)) != len(value):
        raise CorpusError(f"{where}: {name} contains duplicates")


def validate_scope_snapshot(snapshot, where: str) -> None:
    """Strictly type-check an impact-scan:v1 snapshot, including recomputing
    its digest, so a snapshot whose candidate_paths were edited while the
    digest was left alone is rejected."""

    if not isinstance(snapshot, dict):
        raise CorpusError(f"{where}: scope snapshot must be a JSON object")
    missing = _SCOPE_REQUIRED_KEYS - set(snapshot)
    unknown = set(snapshot) - _SCOPE_ALLOWED_KEYS
    if missing:
        raise CorpusError(f"{where}: scope snapshot is missing keys {sorted(missing)}")
    if unknown:
        raise CorpusError(f"{where}: scope snapshot has unknown keys {sorted(unknown)}")
    if not isinstance(snapshot["scan_version"], str) or not snapshot["scan_version"]:
        raise CorpusError(f"{where}: scan_version must be a non-empty string")
    if not is_full_git_sha(snapshot["repo_commit"]):
        raise CorpusError(f"{where}: repo_commit must be a 40-character hex git SHA")
    if not is_sha256_hex(snapshot["digest"]):
        raise CorpusError(f"{where}: digest must be a 64-character hex sha256")
    paths = snapshot["candidate_paths"]
    _check_str_list(paths, "candidate_paths", where)
    for p in paths:
        if not p or p.startswith("/") or "\\" in p or ".." in p.split("/"):
            raise CorpusError(f"{where}: candidate_paths entry {p!r} is not a POSIX relative path")
    _check_str_list(snapshot["candidate_layers"], "candidate_layers", where)
    if "open_items" in snapshot:
        open_items = snapshot["open_items"]
        if not isinstance(open_items, list) or not all(isinstance(v, str) for v in open_items):
            raise CorpusError(f"{where}: open_items must be a list of strings")
    if compute_scope_digest(paths, snapshot["candidate_layers"]) != snapshot["digest"]:
        raise CorpusError(f"{where}: scope digest mismatch")


def load_scope_file(path: Path) -> dict:
    where = f"--scope-file {path}"
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise CorpusError(f"{where}: cannot read scope JSON ({e})") from e
    validate_scope_snapshot(snapshot, where)
    return snapshot


def explanation_id_for(scope_snapshot: dict) -> str:
    return "EXP-" + sha256_hex(canonical_json(scope_snapshot))[:16]


def _match_paths(obs: dict) -> set:
    paths = set(obs.get("affected_paths", []))
    for p in obs["provenance"]:
        if p.get("source_kind") in SOURCE_KINDS_REPO_INTERNAL:
            paths.add(p.get("uri"))
    return paths


def build_explanation(corpus, scope_snapshot: dict, corpus_commit: str, generated_at: str, generator_version: str) -> dict:
    """Pure function: the full explanation file for one scope. Both
    `explain` (to write) and `validate` (to reconstruct and compare) call it."""

    observations = corpus.observations
    match_index = {oid: _match_paths(observations[oid]) for oid in sorted(observations)}
    candidate_paths = scope_snapshot["candidate_paths"]
    covered: dict[str, list[str]] = {}
    uncovered: list[str] = []
    for path in candidate_paths:
        hits = [oid for oid, paths in match_index.items() if path in paths]
        if hits:
            covered[path] = hits
        else:
            uncovered.append(path)
    source_ids = sorted({oid for hits in covered.values() for oid in hits})
    sources = [
        {
            "kind": "observation",
            "observation_id": oid,
            "topic_id": observations[oid]["topic_id"],
            "revision_digest": revision_digest_of(observations[oid]),
        }
        for oid in source_ids
    ]
    commit_mismatch = scope_snapshot["repo_commit"] != corpus_commit

    lines = [
        f"# Explanation (authority: none) — {SCOPE_KIND} {scope_snapshot['digest']}",
        f"corpus_commit: {corpus_commit}",
    ]
    if commit_mismatch:
        lines.append(
            f"WARNING: scope repo_commit {scope_snapshot['repo_commit']} differs from "
            "corpus_commit; claims describe the corpus commit."
        )
    for path in candidate_paths:
        if path not in covered:
            continue
        lines += ["", f"## {path}"]
        for oid in covered[path]:
            obs = observations[oid]
            lines.append(f"- {oid} [{obs['claim_kind']} / {obs['epistemic_status']}] {obs['statement']}")
    lines += ["", "## Uncovered paths"]
    lines += [f"- {path}" for path in uncovered]
    lines += ["", "This file is generated. Do not edit; regenerate with evidence-docs explain."]

    return {
        "schema_version": SCHEMA_VERSION,
        "authority": "none",
        "explanation_id": explanation_id_for(scope_snapshot),
        "scope": {"kind": SCOPE_KIND, "snapshot": scope_snapshot},
        "corpus_commit": corpus_commit,
        "commit_mismatch": commit_mismatch,
        "sources": sources,
        "generator": {"name": GENERATOR_NAME, "version": generator_version, "method": GENERATOR_METHOD},
        "generated_at": generated_at,
        "body": {"covered_paths": covered, "uncovered_paths": uncovered, "text": "\n".join(lines) + "\n"},
    }


def serialize_explanation(explanation: dict) -> str:
    return json.dumps(explanation, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def reject_unless_plain(path: Path, want_dir: bool) -> None:
    """Shared by `explain` (before writing) and validate rule 1: an
    explanations path must be a real directory / regular file, never a
    symlink (resolve_write_path alone allows corpus-internal symlinks)."""

    kind = "directory" if want_dir else "file"
    if path.is_symlink():
        raise CorpusError(f"{path}: explanations {kind} must not be a symlink")
    ok = path.is_dir() if want_dir else path.is_file()
    if not ok:
        raise CorpusError(f"{path}: expected a regular explanations {kind}")


# --- rule 4: authoritative records never reference an explanation ---------


def _find_explanation_ref(value, key_path: str):
    if isinstance(value, str):
        return key_path if EXPLANATION_REF_RE.search(value) else None
    if isinstance(value, dict):
        for k, v in value.items():
            child = f"{key_path}.{k}" if key_path else str(k)
            if isinstance(k, str) and EXPLANATION_REF_RE.search(k):
                return child
            hit = _find_explanation_ref(v, child)
            if hit:
                return hit
    if isinstance(value, list):
        for i, v in enumerate(value):
            hit = _find_explanation_ref(v, f"{key_path}[{i}]")
            if hit:
                return hit
    return None


def check_no_explanation_refs(corpus, registry: dict, corpus_dir=None) -> None:
    # Raw-text pass first: every authoritative YAML file as written (wrapper keys,
    # comments, and anything the loader drops included), so nothing outside the
    # parsed records can carry a reference. The structured pass below keeps the
    # key-path in the message for the common case.
    if corpus_dir is not None:
        files = sorted((corpus_dir / "topics").glob("*.yaml"))
        files += sorted((corpus_dir / "observations").glob("*.yaml"))
        files += [corpus_dir / "gaps.yaml", corpus_dir / "id-registry.yaml"]
        for f in files:
            if not f.is_file():
                continue
            for lineno, line in enumerate(f.read_text(encoding="utf-8").splitlines(), start=1):
                if EXPLANATION_REF_RE.search(line):
                    rel = f.relative_to(corpus_dir).as_posix()
                    raise CorpusError(
                        f"authoritative record {rel}:{lineno} references an explanation (raw text)"
                    )
    records = [(tid, corpus.topics[tid]) for tid in sorted(corpus.topics)]
    records += [(oid, corpus.observations[oid]) for oid in sorted(corpus.observations)]
    for i, gap in enumerate(corpus.gaps or []):
        gap_id = gap.get("id") if isinstance(gap, dict) else None
        records.append((gap_id if isinstance(gap_id, str) else f"gaps[{i}]", gap))
    records.append(("id-registry.yaml", registry))
    for record_id, record in records:
        hit = _find_explanation_ref(record, "")
        if hit:
            raise CorpusError(f"authoritative record {record_id} references an explanation ({hit})")


# --- rules 1-3: validate stored explanations by full reconstruction --------


def _first_difference(saved, expected, key_path: str = "") -> str:
    if isinstance(saved, dict) and isinstance(expected, dict):
        for k in sorted(set(saved) | set(expected)):
            child = f"{key_path}.{k}" if key_path else k
            if k not in saved or k not in expected:
                return child
            diff = _first_difference(saved[k], expected[k], child)
            if diff:
                return diff
        return ""
    if isinstance(saved, list) and isinstance(expected, list):
        for i, (a, b) in enumerate(zip(saved, expected)):
            diff = _first_difference(a, b, f"{key_path}[{i}]")
            if diff:
                return diff
        return "" if len(saved) == len(expected) else f"{key_path}[{min(len(saved), len(expected))}]"
    if type(saved) is not type(expected) or saved != expected:
        return key_path or "<root>"
    return ""


def _validate_one(path: Path, corpus, repo_commit: str, generator_version: str) -> None:
    name = path.name
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise CorpusError(f"explanation file {name} is not valid JSON ({e})") from e
    if not isinstance(saved, dict):
        raise CorpusError(f"explanation file {name}: top level must be a JSON object")
    if set(saved) != TOP_LEVEL_KEYS:
        missing = sorted(TOP_LEVEL_KEYS - set(saved))
        unknown = sorted(set(saved) - TOP_LEVEL_KEYS)
        raise CorpusError(f"explanation file {name}: top-level keys missing {missing}, unknown {unknown}")
    scope = saved["scope"]
    if not isinstance(scope, dict) or scope.get("kind") != SCOPE_KIND or "snapshot" not in scope:
        raise CorpusError(f"explanation file {name}: scope must be {{kind: {SCOPE_KIND!r}, snapshot: ...}}")
    validate_scope_snapshot(scope["snapshot"], f"explanation file {name}")
    if not is_valid_iso8601_utc(saved["generated_at"]):
        raise CorpusError(f"explanation file {name}: generated_at is not a UTC ISO 8601 datetime")
    expected_id = explanation_id_for(scope["snapshot"])
    if name != f"{expected_id}.json" or saved["explanation_id"] != expected_id:
        raise CorpusError(f"explanation file {name} does not match its scope (expected {expected_id}.json)")

    expected = build_explanation(corpus, scope["snapshot"], repo_commit, saved["generated_at"], generator_version)
    if canonical_json(expected) == canonical_json(saved):
        return
    if canonical_json(saved["sources"]) != canonical_json(expected["sources"]):
        raise CorpusError(f"stale explanation {expected_id}: regenerate it")
    raise CorpusError(
        f"explanation {expected_id} does not match the generator output (edited by hand, or not "
        f"produced by this generator): first difference at {_first_difference(saved, expected)}"
    )


def validate_explanations(corpus_dir: Path, corpus, repo_commit: str, generator_version: str) -> None:
    exp_dir = corpus_dir / EXPLANATIONS_DIR
    if not os.path.lexists(exp_dir):
        return
    reject_unless_plain(exp_dir, want_dir=True)
    for entry in sorted(exp_dir.iterdir()):
        if entry.is_symlink() or not entry.is_file():
            raise CorpusError(f"{entry}: explanations/ may only contain regular files (no symlinks or subdirectories)")
        if not EXPLANATION_FILE_RE.fullmatch(entry.name):
            raise CorpusError(f"{entry}: explanation file names must match EXP-<16 hex>.json")
        _validate_one(entry, corpus, repo_commit, generator_version)
