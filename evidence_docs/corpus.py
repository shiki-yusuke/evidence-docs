"""Loading and validating a claim corpus: topics/*.yaml + observations/*.yaml +
id-registry.yaml + gaps.yaml -> an in-memory corpus, or a CorpusError
explaining exactly what is wrong.

This module is a behavior-preserving port of the validation logic proven out
in the sketch-web `CLI-1919` pilot corpus generator across eight rounds of
review (human + Copilot + Codex bot). See docs/schema.md for what is and
isn't verified, and why each check exists.
"""

from __future__ import annotations

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


class Corpus:
    def __init__(self, topics: dict, observations: dict, gaps: list):
        self.topics = topics
        self.observations = observations
        self.gaps = gaps


def load_corpus(corpus_dir: Path) -> Corpus:
    registry = load_yaml(corpus_dir / "id-registry.yaml")
    registered_topics = registry["topics"]
    registered_observations = registry["observations"]

    topics: dict[str, dict] = {}
    for path in sorted((corpus_dir / "topics").glob("*.yaml")):
        topic = load_yaml(path)
        tid = topic["topic_id"]
        if tid not in registered_topics:
            raise CorpusError(f"{path}: topic_id {tid} is not in id-registry.yaml")
        if tid in topics:
            raise CorpusError(f"duplicate topic_id {tid}")
        topics[tid] = topic

    observations: dict[str, dict] = {}
    for path in sorted((corpus_dir / "observations").glob("*.yaml")):
        doc = load_yaml(path)
        for obs in doc["observations"]:
            oid = obs["observation_id"]
            if oid not in registered_observations:
                raise CorpusError(
                    f"{path}: observation_id {oid} is not in id-registry.yaml "
                    "(mint it there first -- IDs must be stable and pre-registered)"
                )
            if registered_observations[oid]["topic_id"] != obs["topic_id"]:
                raise CorpusError(f"{path}: {oid} topic_id mismatch vs id-registry.yaml")
            if obs["topic_id"] not in topics:
                raise CorpusError(f"{path}: {oid} references unknown topic_id {obs['topic_id']}")
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

    gaps = load_yaml(corpus_dir / "gaps.yaml")["gaps"]

    return Corpus(topics=topics, observations=observations, gaps=gaps)


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
            target = ref.split("#", 1)[0].split(" ", 1)[0]
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
