"""Loading and validating a claim corpus: topics/*.yaml + observations/*.yaml +
id-registry.yaml + gaps.yaml -> an in-memory corpus, or a CorpusError
explaining exactly what is wrong.

This module is a behavior-preserving port of validation logic proven out in
an internal pilot corpus generator across eight rounds of review (human +
automated code review bots). See docs/schema.md for what is and isn't
verified, and why each check exists.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path

import yaml

from .errors import CorpusError
from .gitio import BlobDigestCache, resolve_repo_path, sha256_of_file
from .schema import (
    ALL_SOURCE_KINDS,
    CLAIM_KINDS,
    CONFORMANCE_STATUSES,
    EPISTEMIC_STATUSES,
    EXTERNAL_DIGEST_SENTINELS,
    ORIGINS,
    REVIEW_STATUSES,
    SOURCE_KINDS_REPO_EXTERNAL,
    SOURCE_KINDS_REPO_INTERNAL,
    canonical_json,
    is_sha256_hex,
    is_valid_iso8601_utc,
    sha256_hex,
)


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@contextmanager
def yaml_shape_guard(path: Path):
    """Turn a malformed-YAML-shape crash (missing key, wrong type -- e.g. an
    empty file parsing to None, or a mapping expected where a list or scalar
    was written) into a CorpusError that names the offending file, instead of
    letting a raw KeyError/TypeError/AttributeError/IndexError traceback
    reach the CLI. The public validate/generate commands promise CorpusError
    as their only failure mode; a stray traceback would break that contract
    and give the caller nothing to act on beyond "something crashed".
    """

    try:
        yield
    except (KeyError, TypeError, AttributeError, IndexError) as e:
        raise CorpusError(f"{path}: malformed corpus YAML ({type(e).__name__}: {e})") from e


class Corpus:
    def __init__(self, topics: dict, observations: dict, gaps: list, ref_warnings: list[str] | None = None):
        self.topics = topics
        self.observations = observations
        self.gaps = gaps
        self.ref_warnings = ref_warnings or []


def load_corpus(corpus_dir: Path) -> Corpus:
    registry_path = corpus_dir / "id-registry.yaml"
    with yaml_shape_guard(registry_path):
        registry = load_yaml(registry_path)
        registered_topics = registry["topics"]
        registered_observations = registry["observations"]

    topics: dict[str, dict] = {}
    for path in sorted((corpus_dir / "topics").glob("*.yaml")):
        with yaml_shape_guard(path):
            topic = load_yaml(path)
            tid = topic["topic_id"]
            related = topic.get("related_topics", [])
            if not isinstance(related, list):
                # A bare `list(...)` conversion would silently accept a
                # string here (iterating its characters) instead of
                # surfacing the shape mistake.
                raise TypeError(f"related_topics must be a list, got {type(related).__name__}")
        if tid not in registered_topics:
            raise CorpusError(f"{path}: topic_id {tid} is not in id-registry.yaml")
        if tid in topics:
            raise CorpusError(f"duplicate topic_id {tid}")
        topics[tid] = topic

    observations: dict[str, dict] = {}
    for path in sorted((corpus_dir / "observations").glob("*.yaml")):
        with yaml_shape_guard(path):
            doc = load_yaml(path)
            obs_list = doc["observations"]
        for obs in obs_list:
            with yaml_shape_guard(path):
                oid = obs["observation_id"]
                topic_id = obs["topic_id"]
            if oid not in registered_observations:
                raise CorpusError(
                    f"{path}: observation_id {oid} is not in id-registry.yaml "
                    "(mint it there first -- IDs must be stable and pre-registered)"
                )
            with yaml_shape_guard(path):
                registered_topic_id = registered_observations[oid]["topic_id"]
            if registered_topic_id != topic_id:
                raise CorpusError(f"{path}: {oid} topic_id mismatch vs id-registry.yaml")
            if topic_id not in topics:
                raise CorpusError(f"{path}: {oid} references unknown topic_id {topic_id}")
            if oid in observations:
                raise CorpusError(f"duplicate observation_id {oid}")
            validate_observation(obs, path)
            observations[oid] = obs

    missing_topics = set(registered_topics) - set(topics)
    missing_obs = set(registered_observations) - set(observations)
    if missing_topics:
        raise CorpusError(f"id-registry.yaml declares topics never defined: {sorted(missing_topics)}")
    if missing_obs:
        raise CorpusError(f"id-registry.yaml declares observations never defined: {sorted(missing_obs)}")

    # A typo'd or stale entry in related_topics would otherwise flow straight
    # into relations.jsonl unvalidated, injecting an unresolvable edge into
    # the graph an AI agent is meant to walk.
    for tid in sorted(topics):
        for related in topics[tid].get("related_topics", []):
            if related not in topics:
                raise CorpusError(
                    f"topics/{tid}: related_topics references unknown topic_id "
                    f"{related!r} (typo? or a topic that was removed without updating "
                    "related_topics elsewhere)"
                )

    ref_warnings = check_dangling_refs(topics, observations)

    gaps_path = corpus_dir / "gaps.yaml"
    with yaml_shape_guard(gaps_path):
        gaps = load_yaml(gaps_path)["gaps"]

    return Corpus(topics=topics, observations=observations, gaps=gaps, ref_warnings=ref_warnings)


_INTERNAL_REF_RE = re.compile(r"^(OBS|T)-\d+$")
# Looser than _INTERNAL_REF_RE: case-insensitive, hyphen optional. Catches
# typos of the exact shape (wrong case, dropped hyphen) that would otherwise
# be indistinguishable from a genuinely external reference.
_AMBIGUOUS_REF_RE = re.compile(r"^(obs|t)-?\d+$", re.IGNORECASE)


def normalize_ref_target(ref: str) -> str:
    """Extract the leading token a supporting_refs/contradicting_refs entry
    points at, stripping a trailing `#anchor` or free-text explanation
    (e.g. "OBS-014#some note" or "OBS-014 because of X" both normalize to
    "OBS-014"). Shared by check_dangling_refs() and build_relations() so
    both agree on what a ref "means".
    """

    return ref.split("#", 1)[0].split(" ", 1)[0]


def check_dangling_refs(topics: dict[str, dict], observations: dict[str, dict]) -> list[str]:
    """Cross-check supporting_refs/contradicting_refs against the corpus,
    the same way related_topics is cross-checked against topics.

    A ref is free text that may point at an internal claim ("OBS-014"), a
    topic ("T-03"), or something external entirely (a spec/doc path, a PR
    comment locator) -- only the leading token (see normalize_ref_target)
    is inspected:

    - A target that exactly matches the OBS-<n>/T-<n> shape is treated as
      an internal reference and must exist in this corpus; a typo'd or
      stale ID (e.g. "OBS-999") is rejected, the same guarantee
      related_topics already gets.
    - A target that loosely resembles an ID (case-insensitive "obs-"/"t-"
      prefix) without matching that shape exactly -- e.g. "Obs-014" or
      "OBS014" -- is almost certainly a typo'd internal reference, but not
      confidently enough to hard-fail the whole corpus over. It is
      returned as a warning instead of an error.
    - Anything else (a doc path, a review-memory locator, ...) is an
      external reference and is not checked here at all -- the same
      convention build_relations() uses to decide whether to emit an
      observation_contradicts edge.
    """

    warnings: list[str] = []
    for oid in sorted(observations):
        obs = observations[oid]
        for field in ("supporting_refs", "contradicting_refs"):
            for ref in obs.get(field) or []:
                target = normalize_ref_target(ref)
                if _INTERNAL_REF_RE.match(target):
                    if target.startswith("OBS-") and target not in observations:
                        raise CorpusError(
                            f"{oid}.{field} references unknown observation_id {target!r} "
                            f"(from ref {ref!r}) -- typo? or an observation that was "
                            "removed without updating its referrers"
                        )
                    if target.startswith("T-") and target not in topics:
                        raise CorpusError(
                            f"{oid}.{field} references unknown topic_id {target!r} "
                            f"(from ref {ref!r}) -- typo? or a topic that was removed "
                            "without updating its referrers"
                        )
                elif _AMBIGUOUS_REF_RE.match(target):
                    warnings.append(
                        f"{oid}.{field} ref {ref!r} looks like it might be an internal "
                        f"reference (target {target!r}) but doesn't match the OBS-<n>/T-<n> "
                        "shape exactly; treated as external and not cross-checked here -- "
                        "verify this isn't a typo'd internal reference"
                    )
    return warnings


def validate_observation(obs: dict, path: Path) -> None:
    oid = obs["observation_id"]
    if obs["claim_kind"] not in CLAIM_KINDS:
        raise CorpusError(f"{path}: {oid} invalid claim_kind {obs['claim_kind']!r}")
    if obs["origin"] not in ORIGINS:
        raise CorpusError(f"{path}: {oid} invalid origin {obs['origin']!r}")
    if obs["epistemic_status"] not in EPISTEMIC_STATUSES:
        raise CorpusError(f"{path}: {oid} invalid epistemic_status {obs['epistemic_status']!r}")
    if obs["conformance_status"] not in CONFORMANCE_STATUSES:
        raise CorpusError(f"{path}: {oid} invalid conformance_status {obs['conformance_status']!r}")
    if obs["review_status"] not in REVIEW_STATUSES:
        raise CorpusError(f"{path}: {oid} invalid review_status {obs['review_status']!r}")
    if "negation_check" in obs and obs["negation_check"] is not None:
        if not isinstance(obs["negation_check"], str) or not obs["negation_check"].strip():
            raise CorpusError(
                f"{path}: {oid} negation_check must be a non-empty string when present "
                "(a short record of the test-broke-red check performed for "
                "execution_verified claims), got {obs['negation_check']!r}"
            )
    # subject_refs/supporting_refs/contradicting_refs are all free-text lists
    # (a symbol name, or a pointer to another claim/doc). Existence of
    # supporting_refs/contradicting_refs targets that look like internal IDs
    # is cross-checked later by check_dangling_refs(), once the whole corpus
    # is loaded; here only the shape is checked, since it applies uniformly
    # to all three fields regardless of what they end up pointing at.
    for field in ("subject_refs", "supporting_refs", "contradicting_refs"):
        if field not in obs or obs[field] is None:
            continue
        values = obs[field]
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise CorpusError(f"{path}: {oid} {field} must be a list of strings")
        if any(not v.strip() for v in values):
            raise CorpusError(f"{path}: {oid} {field} must not contain blank entries")
    if not obs["provenance"]:
        raise CorpusError(f"{path}: {oid} has no provenance")
    for prov in obs["provenance"]:
        observed_at = prov.get("observed_at")
        if not observed_at or not is_valid_iso8601_utc(observed_at):
            raise CorpusError(
                f"{obs['observation_id']}: provenance.observed_at must be a UTC ISO 8601 "
                f"datetime (got {observed_at!r}) -- downstream tools parse it (see "
                "is_valid_iso8601_utc docstring)"
            )
        kind = prov["source_kind"]
        # An unrecognized source_kind (typos included) is rejected
        # unconditionally. Silently skipping unknown kinds would let e.g.
        # "source_kind: soruce" bypass both the hash-matching and
        # repo-root-escape checks below, with an arbitrary content_digest.
        if kind not in ALL_SOURCE_KINDS:
            raise CorpusError(
                f"{path}: {oid} provenance has unknown source_kind {kind!r} "
                f"(must be one of {sorted(ALL_SOURCE_KINDS)} -- typo? or a genuinely new "
                "source kind that needs to be added to ALL_SOURCE_KINDS first)"
            )

        if kind in SOURCE_KINDS_REPO_EXTERNAL:
            # No repo blob to hash against (uri isn't repo-relative), so only
            # the shape of uri/content_digest is validated: either a sha256
            # hex string, or one of the explicitly declared sentinels.
            if not isinstance(prov["uri"], str) or not prov["uri"].strip():
                raise CorpusError(f"{path}: {oid} provenance has empty uri (source_kind={kind})")
            digest = prov["content_digest"]
            if not (is_sha256_hex(digest) or digest in EXTERNAL_DIGEST_SENTINELS):
                raise CorpusError(
                    f"{path}: {oid} provenance content_digest {digest!r} for {prov['uri']!r} "
                    f"(source_kind={kind}) must be either a sha256 hex string or one of the "
                    f"declared sentinels {sorted(EXTERNAL_DIGEST_SENTINELS)} -- add a new "
                    "sentinel there first if this is a genuinely new case"
                )
            continue

        # SOURCE_KINDS_REPO_INTERNAL: only the sha256-hex *shape* is checked
        # here. Whether it matches the actual git blob at --repo-commit is
        # checked later by verify_content_digests_against_commit(), once
        # repo_commit is known (load_corpus() runs before that argument is
        # available).
        if not is_sha256_hex(prov["content_digest"]):
            raise CorpusError(
                f"{path}: {oid} provenance for {prov['uri']} must carry a sha256 "
                f"content_digest (source_kind={kind})"
            )


def revision_digest_of(obs: dict) -> str:
    """Content hash of an observation, stable across re-confirmation.

    provenance.observed_at is excluded from the digested payload on purpose:
    without that exclusion, merely re-confirming the same fact on a later
    date would change the digest, making it impossible to tell "unchanged
    fact, re-observed" apart from "the claim's content actually changed".
    """

    payload = {
        "observation_id": obs["observation_id"],
        "topic_id": obs["topic_id"],
        "claim_kind": obs["claim_kind"],
        "statement": obs["statement"],
        "origin": obs["origin"],
        "epistemic_status": obs["epistemic_status"],
        "conformance_status": obs["conformance_status"],
        "subject_refs": obs.get("subject_refs", []),
        "affected_paths": obs.get("affected_paths", []),
        "supporting_refs": obs.get("supporting_refs", []),
        "contradicting_refs": obs.get("contradicting_refs", []),
        "provenance": [{k: v for k, v in p.items() if k != "observed_at"} for p in obs["provenance"]],
    }
    return sha256_hex(canonical_json(payload))


def build_claims(observations: dict[str, dict]) -> list[dict]:
    claims = []
    for oid in sorted(observations):
        obs = observations[oid]
        claim = dict(obs)
        claim["revision_digest"] = revision_digest_of(obs)
        claims.append(claim)
    return claims


def build_relations(topics: dict[str, dict], observations: dict[str, dict]) -> list[dict]:
    """`contradicting_refs` entries are normalized the same way
    check_dangling_refs() validates them (see normalize_ref_target): only a
    ref whose normalized target is an observation_id that actually exists
    in this corpus becomes an observation_contradicts edge. Refs pointing
    at external docs, or ambiguous almost-an-ID typos, are left out of the
    relation graph entirely -- an edge to something that can't be resolved
    would be worse than no edge.
    """

    relations = []
    for oid in sorted(observations):
        obs = observations[oid]
        relations.append(
            {"type": "topic_contains_observation", "topic_id": obs["topic_id"], "observation_id": oid}
        )
    for tid in sorted(topics):
        for related in topics[tid].get("related_topics", []):
            relations.append({"type": "topic_related_to_topic", "from": tid, "to": related})
    all_obs_ids = set(observations)
    for oid in sorted(observations):
        for ref in observations[oid].get("contradicting_refs", []):
            target = normalize_ref_target(ref)
            if target in all_obs_ids:
                relations.append({"type": "observation_contradicts", "from": oid, "to": target})
    return relations


def build_evidence(observations: dict[str, dict]) -> list[dict]:
    evidence = []
    for oid in sorted(observations):
        for idx, prov in enumerate(observations[oid]["provenance"]):
            evidence.append({"observation_id": oid, "provenance_index": idx, **prov})
    return evidence


def build_conflicts(observations: dict[str, dict]) -> list[dict]:
    conflicts = []
    for oid in sorted(observations):
        obs = observations[oid]
        if obs["conformance_status"] == "drifted":
            conflicts.append(
                {
                    "observation_id": oid,
                    "topic_id": obs["topic_id"],
                    "statement": obs["statement"],
                    "contradicting_refs": obs.get("contradicting_refs", []),
                }
            )
    return conflicts


def build_gaps(gaps: list[dict]) -> list[dict]:
    return sorted(gaps, key=lambda g: g["id"])


def counts_by(claims: list[dict], field: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in claims:
        out[c[field]] = out.get(c[field], 0) + 1
    return dict(sorted(out.items()))


def find_repo_commit_mismatches(observations: dict[str, dict], repo_commit: str) -> list[str]:
    """Cross-check --repo-commit against every valid_at_commit / provenance[].repo_commit
    recorded in the corpus.

    A corpus is a snapshot of a single commit; if per-observation repo_commit
    values were allowed to disagree, site/bundle output would describe a code
    state that no single commit actually had. Any mismatch is fatal, and all
    of them are reported together (not just the first) so a bulk re-stamp
    only needs one validate/generate cycle to see everything that's wrong.
    """

    mismatches = []
    for oid in sorted(observations):
        obs = observations[oid]
        if obs["valid_at_commit"] != repo_commit:
            mismatches.append(f"{oid}.valid_at_commit = {obs['valid_at_commit']!r} (expected {repo_commit!r})")
        for idx, prov in enumerate(obs["provenance"]):
            if prov["repo_commit"] != repo_commit:
                mismatches.append(
                    f"{oid}.provenance[{idx}] uri={prov.get('uri')!r} .repo_commit = "
                    f"{prov['repo_commit']!r} (expected {repo_commit!r})"
                )
    return mismatches


def verify_content_digests_against_commit(
    observations: dict[str, dict], repo_commit: str, repo_root: Path, blob_cache: BlobDigestCache
) -> list[str]:
    """Verify SOURCE_KINDS_REPO_INTERNAL content_digest against the git blob at
    repo_commit (not the current worktree file).

    Hashing only the worktree file would let "edit the referenced file,
    update content_digest to the new hash, leave repo_commit on the old SHA"
    slip past find_repo_commit_mismatches() (repo_commit itself still
    matches). Hashing `git show <repo_commit>:<uri>` instead verifies what
    the file *actually contained* at the declared commit.

    Returns a list of non-fatal warning strings (worktree drift since
    repo_commit); raises CorpusError on any digest mismatch, which is fatal.
    """

    warnings: list[str] = []
    for oid in sorted(observations):
        obs = observations[oid]
        for idx, prov in enumerate(obs["provenance"]):
            if prov["source_kind"] not in SOURCE_KINDS_REPO_INTERNAL:
                continue
            uri = prov["uri"]
            blob_digest = blob_cache.sha256_of_git_blob(repo_commit, uri)
            if blob_digest != prov["content_digest"]:
                raise CorpusError(
                    f"{oid}.provenance[{idx}] content_digest mismatch against "
                    f"git blob {repo_commit}:{uri} "
                    f"(declared={prov['content_digest']}, blob={blob_digest}). "
                    "The declared content_digest does not match what this file actually "
                    "contained at repo_commit -- re-verify the claim and update content_digest."
                )

            try:
                worktree_path = resolve_repo_path(repo_root, uri)
            except CorpusError:
                warnings.append(
                    f"{oid}.provenance[{idx}] uri={uri!r} escapes the repo root "
                    "in the current worktree; skipping worktree-drift check"
                )
                continue
            if not worktree_path.is_file():
                warnings.append(
                    f"{oid}.provenance[{idx}] uri={uri!r} no longer exists in the "
                    f"current worktree (it existed at {repo_commit}); re-verify recommended"
                )
                continue
            worktree_digest = sha256_of_file(worktree_path)
            if worktree_digest != blob_digest:
                warnings.append(
                    f"{oid}.provenance[{idx}] uri={uri!r} has changed in the "
                    f"current worktree since {repo_commit} (worktree={worktree_digest}, "
                    f"commit={blob_digest}); the corpus is a snapshot so this is expected "
                    "as the repo moves forward, but re-verify this claim before relying on it"
                )
    return warnings
