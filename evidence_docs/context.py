"""`evidence-docs context`: v0 retrieval over an already-generated bundle.

Selects claims for a query made of seeds (affected_paths and/or topic_ids)
plus an optional token_budget, and returns them ranked by how directly they
matched. This is deliberately the simplest thing that is useful:

1. exact affected_paths intersection (claim.affected_paths & seeds.paths)
2. explicit seed topic_ids (every claim under those topics)
3. a single 1-hop expansion across topic_related_to_topic edges, followed in
   both directions, from whatever topics tiers 1-2 touched

Anything past a 1-hop topic walk (deeper graph traversal, claim_kind
filters, symbol-level seeds) is out of scope for v0; see docs/schema.md.
"""

from __future__ import annotations

import json
from pathlib import Path

from .errors import CorpusError

# Rough, provider-agnostic token estimate (~4 characters per token). Good
# enough for budget truncation; not meant to match any specific tokenizer.
_CHARS_PER_TOKEN_ESTIMATE = 4

_MAX_SEED_LIST_LEN = 1000
_MAX_QUERY_DEPTH = 6


class QueryError(CorpusError):
    """Raised when a --query payload itself is malformed input (wrong JSON
    shape, wrong field types, too large/deep), as opposed to a
    corpus/bundle-state problem (e.g. `generate` hasn't been run yet).

    Kept as a CorpusError subclass so any caller that only knows about
    CorpusError still catches it, but the CLI can tell the two apart to
    report a usage error (exit 2) instead of a run failure (exit 1).
    """


def _check_depth(obj, depth: int = 0) -> None:
    if depth > _MAX_QUERY_DEPTH:
        raise QueryError(f"--query is nested more than {_MAX_QUERY_DEPTH} levels deep")
    if isinstance(obj, dict):
        for v in obj.values():
            _check_depth(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _check_depth(v, depth + 1)


def _check_string_list(value, name: str) -> None:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise QueryError(f"{name} must be a list of strings")
    if len(value) > _MAX_SEED_LIST_LEN:
        raise QueryError(f"{name} exceeds the {_MAX_SEED_LIST_LEN}-entry limit")


def validate_query(query) -> None:
    """Reject a --query payload that isn't shaped the way run_context_query()
    expects, before any of its fields are accessed -- an untrusted/malformed
    query should fail with an explanatory QueryError, not a bare
    KeyError/TypeError/AttributeError traceback from deep inside retrieval.
    """

    if not isinstance(query, dict):
        raise QueryError(f"--query must be a JSON object, got {type(query).__name__}")
    _check_depth(query)

    seeds = query.get("seeds", {})
    if not isinstance(seeds, dict):
        raise QueryError("--query.seeds must be an object")
    if "paths" in seeds:
        _check_string_list(seeds["paths"], "--query.seeds.paths")
    if "topic_ids" in seeds:
        _check_string_list(seeds["topic_ids"], "--query.seeds.topic_ids")

    if "token_budget" in query and query["token_budget"] is not None:
        token_budget = query["token_budget"]
        if isinstance(token_budget, bool) or not isinstance(token_budget, int) or token_budget <= 0:
            raise QueryError("--query.token_budget must be a positive integer")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        raise CorpusError(f"{path} not found -- run `evidence-docs generate` before `context`")
    rows = []
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _estimate_tokens(claim: dict) -> int:
    return max(1, len(json.dumps(claim, ensure_ascii=False)) // _CHARS_PER_TOKEN_ESTIMATE)


def run_context_query(bundle_dir: Path, query: dict) -> dict:
    validate_query(query)
    claims = _read_jsonl(bundle_dir / "claims.jsonl")
    relations = _read_jsonl(bundle_dir / "relations.jsonl")

    seeds = query.get("seeds", {})
    seed_paths = set(seeds.get("paths", []))
    seed_topic_ids = set(seeds.get("topic_ids", []))
    token_budget = query.get("token_budget")

    path_matches = [c for c in claims if seed_paths & set(c.get("affected_paths", []))]
    path_match_ids = {c["observation_id"] for c in path_matches}

    topic_seed_matches = [
        c for c in claims if c["topic_id"] in seed_topic_ids and c["observation_id"] not in path_match_ids
    ]
    seed_ids = path_match_ids | {c["observation_id"] for c in topic_seed_matches}
    seed_topics = {c["topic_id"] for c in path_matches} | {c["topic_id"] for c in topic_seed_matches} | seed_topic_ids

    hop_topics: set[str] = set()
    for rel in relations:
        if rel.get("type") != "topic_related_to_topic":
            continue
        if rel["from"] in seed_topics:
            hop_topics.add(rel["to"])
        if rel["to"] in seed_topics:
            hop_topics.add(rel["from"])
    hop_topics -= seed_topics

    hop_matches = [c for c in claims if c["topic_id"] in hop_topics and c["observation_id"] not in seed_ids]

    ordered = (
        sorted(path_matches, key=lambda c: c["observation_id"])
        + sorted(topic_seed_matches, key=lambda c: c["observation_id"])
        + sorted(hop_matches, key=lambda c: c["observation_id"])
    )

    truncated = False
    if token_budget is None:
        selected = ordered
    else:
        selected = []
        used = 0
        for c in ordered:
            est = _estimate_tokens(c)
            # Always keep the first claim even if it alone exceeds the
            # budget -- an empty result is worse than a single over-budget
            # claim.
            if selected and used + est > token_budget:
                break
            selected.append(c)
            used += est
        # truncated if some matching claims were dropped, or if the kept
        # set (necessarily just the first claim, per the rule above) is
        # itself already over budget.
        truncated = len(selected) < len(ordered) or used > token_budget

    return {
        "query": query,
        "claims": selected,
        "matched_topic_ids": sorted({c["topic_id"] for c in selected}),
        "truncated": truncated,
        "rationale": (
            "v0 retrieval: exact affected_paths intersection and seed topic_ids first, "
            "then a single 1-hop expansion across topic_related_to_topic edges (followed "
            "in both directions). token_budget truncates in this priority order using an "
            "approximate 4-chars-per-token estimate; the first claim is always kept even "
            "if it alone exceeds the budget. Future versions may add claim_kind filters "
            "and deeper multi-hop traversal."
        ),
    }
