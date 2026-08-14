# Claim corpus schema: trust boundary

This is the single place that says, plainly, what `evidence-docs
validate`/`generate` actually check, and what they cannot and do not check.
Every check below exists because a specific way of gaming or drifting the
corpus was found (mostly during an eight-round pre-OSS pilot review); every
"not verified" line exists so nobody assumes a check is happening when it
isn't.

## What is trusted as input (not re-derived)

- **statement text.** The prose claim itself is never checked against the
  code. A statement can be wrong, outdated, or overclaimed and still pass
  validation -- validation checks *structure and provenance shape*, not
  truth. Catching an overclaimed statement is a human/reviewer job (see
  "epistemic_status honesty" below).
- **`affected_paths` completeness.** Nothing checks that every path actually
  touched by an observation is listed, only that listed paths are used
  as-is by `context` retrieval.
- **`selector` text** (which test/function/section a provenance entry
  points at). It is not verified that the selector actually appears at that
  location -- only `content_digest` (see below) is checked, which verifies
  the *file's* content, not that the selector string exists inside it.
- **`gaps.yaml` completeness.** A corpus with zero recorded gaps is
  syntactically valid. Whether the authors actually looked for
  contradictions is not something a validator can check.
- **epistemic_status honesty.** Nothing stops an author from writing
  `execution_verified` for a claim only supported by reading the source. The
  `negation_check` field (below) is one tool for catching this, but it's
  optional and unenforced.

## What is structurally verified

- **IDs are pre-registered.** Every `topic_id`/`observation_id` used in
  `topics/*.yaml` / `observations/*.yaml` must already exist in
  `id-registry.yaml`, and every ID registered there must be defined
  somewhere. This closes typo/duplicate/off-by-one ID bugs at generate
  time, not at read time.
- **`related_topics` has no dangling references.** A topic referencing a
  `topic_id` that doesn't exist (typo, or a topic removed without updating
  its referrers) is rejected -- otherwise it would flow straight into
  `relations.jsonl` as an edge nothing can resolve.
- **Enum fields are exact-match against a fixed vocabulary**
  (`claim_kind`, `origin`, `epistemic_status`, `conformance_status`,
  `review_status`, `provenance[].source_kind`). Unknown values (including
  typos) are rejected outright rather than silently ignored -- an unknown
  `source_kind` used to be treated as "skip this provenance entry's
  checks", which is exactly the gap a forged entry would exploit.
- **`provenance[].observed_at` is UTC-offset ISO 8601.** Naive datetimes
  (no offset) and non-UTC offsets (`+09:00` etc.) are both rejected, not
  just malformed strings. Downstream tools parse this field as a datetime
  and compare/sort by it; an ambiguous or skewed value would corrupt that
  silently instead of failing loudly.
- **`--repo-commit` must equal every `valid_at_commit` and
  `provenance[].repo_commit` in the corpus, with no exceptions.** A corpus
  is defined as a snapshot of one commit; if per-observation commits were
  allowed to disagree, `site/`/`bundle/` output would describe a code state
  no single commit ever had.

## Content digest verification (the part with the most history)

`provenance[].content_digest` for `source_kind` in `{source, test, spec}`
(files that live inside the repo) is checked against the **git blob at the
declared `repo_commit`** -- i.e. `git show <repo_commit>:<uri>`, hashed with
sha256 -- not against whatever is currently on disk in the worktree.

This is the *only* correct order, arrived at through three iterations that
each closed a bypass the previous one left open:

1. Format-only check ("is this 64 hex chars"): passes for any digest,
   including a stale one from a since-changed file, or an unrelated
   64-char value.
2. Check against the worktree file's real sha256: closes (1), but "edit the
   referenced file, recompute content_digest for the new content, leave
   `repo_commit` on the old SHA" still passes -- `repo_commit` matching
   corpus-wide (previous section) doesn't imply the *file* matches that
   commit.
3. Check against the git blob at the declared commit: closes (2), because
   the hash is computed from what the file *actually contained* at that
   commit, independent of what the worktree currently holds.

Two independent path-traversal guards sit in front of this:
`resolve_repo_path()` resolves against the worktree filesystem (following
symlinks) and rejects anything outside `repo_root`; `is_safe_repo_relative_uri()`
rejects `..`/absolute paths at the string level before the uri is ever
handed to `git show`, since git show never touches the filesystem and needs
its own independent check.

If the worktree file's current content differs from the git-blob content at
`repo_commit`, that produces a **warning**, not a validation failure -- the
corpus is a snapshot, so the repo moving on afterward is expected. A
mismatch against the *declared commit's own blob* is always fatal.

`source_kind: review_memory` (and any future repo-external source) cannot
be blob-verified this way, since its `uri` isn't a repo-relative path.
Only the shape of `content_digest` is checked there: it must be a sha256
hex string, or one of the declared entries in `EXTERNAL_DIGEST_SENTINELS`.

## `revision_digest`

`bundle/claims.jsonl` carries a `revision_digest` per claim, computed by
the generator (never authored by hand) from a canonical JSON payload of the
claim's semantic fields. `provenance[].observed_at` is deliberately
excluded from that payload: re-confirming the same fact on a later date
should not change the digest, since the digest is meant to distinguish
"content changed" from "content re-observed, unchanged". This was a
pilot-stage design decision, preserved here as-is because there's no way to
represent "same fact, later confirmation" any other way without it.

## `negation_check` (optional)

An observation may carry a free-text `negation_check` field recording that
the reviewer broke (or reverted a condition in) the cited test and
confirmed it goes red, before trusting an `execution_verified` claim. It is
**optional, not required** -- there's no way to mechanically verify that a
described negation check was actually performed, so making it mandatory
would just move the honesty problem one field over. When present, only its
*shape* is checked (non-empty string). Treat its absence as "not recorded",
not as "not done".

## Corpus size / file granularity

Observations are grouped one-file-per-topic (not one-file-per-observation).
This is a diff-review tradeoff, not a correctness requirement: at larger
corpus sizes, splitting to one-file-per-observation may read better in
review tooling. `evidence-docs` does not enforce either layout.
