"""Vocabulary and low-level value validators for the claim corpus schema.

See docs/schema.md for the trust-boundary write-up: what these validators
guarantee, what they deliberately do not check, and why. This module only
holds pure, side-effect-free predicates and constants; the corpus-shaped
validation (cross-referencing topics/observations/id-registry, git blob
verification) lives in corpus.py and gitio.py.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

CLAIM_KINDS = {
    "behavior",
    "invariant",
    "constraint",
    "interface",
    "dependency",
    "failure_mode",
    "decision_record",
}
ORIGINS = {"recorded", "reconstructed"}
EPISTEMIC_STATUSES = {
    "recorded_decision",
    "execution_verified",
    "cross_source_corroborated",
    "single_source_observation",
    "model_inference",
    "conflicting",
}
CONFORMANCE_STATUSES = {"matched", "drifted", "not_checked"}
REVIEW_STATUSES = {"unreviewed", "reviewed_accepted", "reviewed_rejected"}

# provenance.source_kind explicit allow-list. Anything not listed here (typos
# included) is rejected outright: an unrecognized source_kind used to be
# silently skipped by both the hash-matching and repo-root-escape checks,
# which let a typo'd source_kind combine with an out-of-repo uri and an
# arbitrary content_digest to sail through validation untouched.
#
# - SOURCE_KINDS_REPO_INTERNAL: points at a file inside the repository. The
#   content_digest is checked against the *actual* sha256 of the git blob at
#   the declared repo_commit (real hash matching, not just "looks like a
#   sha256 hex string").
# - SOURCE_KINDS_REPO_EXTERNAL: references outside the repo, keyed by uri +
#   line/record locator rather than a repo-relative path (e.g. an external
#   review-memory log). Since there is no repo blob to hash against, only
#   the *shape* of uri/content_digest is validated.
SOURCE_KINDS_REPO_INTERNAL = {"source", "test", "spec"}
SOURCE_KINDS_REPO_EXTERNAL = {"review_memory"}
ALL_SOURCE_KINDS = SOURCE_KINDS_REPO_INTERNAL | SOURCE_KINDS_REPO_EXTERNAL

# Values content_digest is allowed to take for SOURCE_KINDS_REPO_EXTERNAL when
# a real hash cannot be computed (the uri isn't a repo-relative path). Add a
# new sentinel here -- and only here -- before using it in a corpus.
EXTERNAL_DIGEST_SENTINELS = {"not_computed_external_to_repo"}


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def is_sha256_hex(value) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def is_full_git_sha(value) -> bool:
    if not isinstance(value, str) or len(value) != 40:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def is_valid_iso8601_utc(value) -> bool:
    """Whether `value` parses as a UTC-offset ISO 8601 datetime.

    observed_at / generated_at are parsed as datetimes by downstream tooling
    (the CLI's own help text and README promise ISO 8601), so an arbitrary
    string (e.g. "not-an-iso-date") must not be accepted silently. Naive
    datetimes (no offset at all) are rejected explicitly -- without an
    offset there is no way to know which timezone the snapshot time is in.
    Non-UTC offsets (e.g. +09:00) are also rejected: downstream time
    comparisons and sorting would otherwise drift by the offset difference.
    """

    if not isinstance(value, str) or not value:
        return False
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        return False
    return parsed.utcoffset() == timedelta(0)
