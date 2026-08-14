# Writing evidence-linked docs exposed two missing regression tests

## 1. Problem

I run [`agent-cost`](https://github.com/shiki-yusuke/agent-cost), a small
open-source CLI that reads local Claude Code / Codex CLI usage logs and
estimates token cost. I wanted documentation for it more trustworthy than a
hand-written README: not prose claiming "the reader handles the TTL
cache-write breakdown correctly," but claims that each point at the exact
test or source line backing them, checked against real git history so the
pointer can't silently go stale.

To do that I used a second tool I've been building,
[`evidence-docs`](https://github.com/shiki-yusuke/evidence-docs), to build a
**claim corpus** against `agent-cost`: 17 individual `observation`s grouped
into 5 `topic`s (pricing-catalog validation rules, the cache-write
lower-bound behavior, unpriced-fact handling, decimal arithmetic for money,
and the `measure` command's v1 contract). Each observation is one statement
— a behavior, an invariant, a decision record — with a `claim_kind`, an
`epistemic_status`, and one or more `provenance` entries naming the exact
file, test, or spec section it's backed by, plus a `content_digest` of that
source at a specific commit.

Building that corpus is what surfaced this post's actual finding. To write
an honest `provenance` entry for a behavior claim, I had to point at the
test that exercises it — reading the test, not just the source, for every
claim. Doing that for the cache-write TTL breakdown logic and the
pricing-status aggregation logic turned up two places where the claim I
wanted to make ("the code does X in this case") was true by reading the
code, but had **no test asserting it**. Both went into
`docs/claims/gaps.yaml` as `GAP-01` and `GAP-02`, and both became small,
scoped pull requests that added regression tests with zero implementation
changes.

## 2. Why it mattered

Neither gap was a live bug — that's the whole point of this post.
`agent-cost`'s existing test suite already covered the two extremes of each
piece of logic; what was missing was the *middle* case, the one that's easy
to reason yourself past while staring at the code.

- **GAP-01** (`agent_cost/readers/claude.py`, `parse_session_facts`): when a
  Claude Code usage event's `cache_creation` field is a dict, the reader
  computes `leftover = cache_creation_input_tokens - (ephemeral_5m +
  ephemeral_1h)` and emits it as a `cache_write_unknown` fact if positive.
  Existing tests covered a breakdown that exactly accounts for the total,
  and no breakdown at all — but not a breakdown dict that's *present and
  partial*, where the two counters sum to less than the total. That's a
  real, reachable path with no assertion on what it produces.
- **GAP-02** (`agent_cost/aggregate.py`, `_STATUS_RANK` / `build_rows`): a
  row's `pricing_status` should be the worst status among its facts, ordered
  `unpriced` (0) < `lower_bound` (1) < `priced` (2). The existing test only
  mixed an `unpriced` fact with a `priced` fact. No test built a row from a
  `lower_bound` fact (e.g. a `cache_write_unknown` token, priced as an
  explicit floor) mixed with a plain `priced` fact to confirm the row lands
  on `lower_bound`, not `priced` — the half of the ordering that isn't
  "obviously" covered by the unpriced case.

If either had silently broken in a later refactor — reordering
`_STATUS_RANK`'s values, or changing the leftover math — nothing in CI
would have caught it. The cost-estimation output would have quietly started
under- or over-reporting cost floors, without a single red test.

## 3. Why the obvious fix was insufficient

The obvious response to "I want good docs for this repo" is: write a good
README, or write good docstrings, and be careful. I already had both —
`agent-cost`'s README has a "What this measures, and what it doesn't"
section, and `price_fact()` has a docstring explaining the lower-bound
design decision. Careful prose is necessary but not sufficient, for two
reasons that showed up directly here:

1. **Prose doesn't force you to check the thing it describes against a
   test.** I could (and did, informally) describe the TTL-breakdown
   behavior accurately in a docstring without ever asking "is there a test
   where the breakdown dict is present but incomplete?" Writing prose
   doesn't create that question; writing a `provenance` entry that must
   name a specific test does.
2. **A doc that "looks read" and a doc that's actually checked are
   indistinguishable from the outside.** Nothing in a normal README tells a
   reader which sentences were verified by running something versus which
   were a best guess — every claim carries the same visual weight.

So the fix isn't "write better docs" in the abstract — it's structural:
every behavior claim needs a machine-checkable pointer to what backs it,
narrow enough that "no test covers this case" becomes visible while writing
it, not something discovered later.

## 4. Invariant

`evidence-docs` enforces this as a schema-level invariant on every
`observation`, not a style guideline. **`epistemic_status`** must be one of
a fixed vocabulary (from `execution_verified` down to `model_inference` /
`single_source_observation` / `recorded_decision`) — you have to say how
strongly the claim was checked, not just assert it. **`provenance`** is a
list of entries, each with a `source_kind` (`source`, `test`, `spec`, or
`review_memory`), a repo-relative `uri`, a `selector` (which
test/function/section), a `content_digest`, and the `repo_commit` the
digest was taken against.

Neither field is optional, and both are validated structurally: unknown
`source_kind` values are rejected outright, and `content_digest` is checked
against the actual git blob at the declared commit, not the working tree.
Two of `agent-cost`'s own observations (OBS-004, the cache-write-TTL claim,
and OBS-010, the pricing-status-ranking claim) exist because writing their
`provenance` forced me to go find "the test that proves this," and in both
cases the honest answer was "there isn't one for this specific sub-case" —
which is what `gaps.yaml` records.

## 5. Design (evidence-docs, minimally)

An `evidence-docs` corpus is a directory (conventionally `docs/claims/`)
with: `id-registry.yaml` (every `topic_id`/`observation_id` used anywhere
must be pre-registered here, closing typo/duplicate ID bugs at generate
time); `topics/*.yaml` and `observations/*.yaml` (one file per topic by
convention, not enforced); and `gaps.yaml`, a ledger of gaps found
(`gap_found: true`) *or* explicitly searched for and not found
(`gap_found: false`), each tagged with a `taxonomy` — `test_missing` for
both GAP-01 and GAP-02 here, `independent_re_search_no_drift` for a third
entry, GAP-03, where I re-checked three README pricing claims against the
current `rates.json` and found no drift, recorded as a negative result
rather than omitted.

`evidence-docs validate docs/claims --repo-commit <sha>` runs full
structural + provenance verification with no output written (CI-friendly);
`evidence-docs generate` does the same and then deterministically writes a
human-readable `site/index.md` and an AI-facing `bundle/*.jsonl` +
`manifest.json`. `evidence-docs context docs/claims --query '{"seeds":
{"paths": [...]}, "token_budget": ...}'` selects a relevant subset of
claims from the bundle for a given set of source paths, for feeding into an
LLM context window without shipping the whole corpus. `--generated-at` and
`--repo-commit` are always explicit CLI arguments, never derived from
`datetime.now()` or `git rev-parse` at run time, so the same corpus and
arguments always produce byte-identical output.

## 6. Fail behavior

The parts of `evidence-docs` that made this finding possible are the parts
designed to fail loudly on drift or forgery, not pass silently:

- **Digest verification targets the declared commit's git blob**
  (`git show <repo_commit>:<uri>`, hashed with sha256), not the current
  worktree file. This closes a real bypass: checking only the worktree's
  current hash would still let someone edit the file, recompute the digest,
  and leave `repo_commit` on the old SHA. A worktree/declared-commit
  mismatch is a warning (repos move on after a snapshot); a mismatch against
  the *declared commit's own* blob is always fatal.
- **Unknown `source_kind` is a hard rejection, not a skip.** An earlier
  design silently skipped unrecognized kinds — exactly what a forged or
  typo'd entry would want.
- **`--repo-commit` must equal every `valid_at_commit` and
  `provenance[].repo_commit` corpus-wide**, with no exceptions, since a
  corpus is a snapshot of one commit.
- **Two independent path-traversal guards** sit in front of the digest
  check, since `git show` never touches the filesystem and needs its own
  check separate from worktree path resolution.

None of this checks whether a *statement* is true (see Boundary, below) —
but it does mean a fake or lazy `provenance` entry gets caught at `validate`
time rather than trusted forever.

## 7. Verification: gap to merged test, with receipts

Both gaps followed the same path: recorded in `gaps.yaml`, then closed by a
small PR that added a test and changed no implementation code.

- **GAP-01 → [`shiki-yusuke/agent-cost#2`](https://github.com/shiki-yusuke/agent-cost/pull/2)**
  ("test: cover the partial TTL-breakdown leftover branch in the Claude
  reader"), merged 2026-08-14. Adds
  `test_cache_creation_partial_ttl_breakdown_leftover_is_unknown` to
  `tests/test_reader_claude.py`: a `cache_creation` dict with
  `ephemeral_5m_input_tokens=150` and `ephemeral_1h_input_tokens=100` against
  a `cache_creation_input_tokens` total of 300, asserting the reader emits
  `cache_write_5m=150`, `cache_write_1h=100`, **and** `cache_write_unknown=50`
  for the 50-token leftover. No implementation changes — the leftover math
  already behaved this way; the PR's own description says so.
- **GAP-02 → [`shiki-yusuke/agent-cost#3`](https://github.com/shiki-yusuke/agent-cost/pull/3)**
  ("test: pin the worst-status row aggregation order for pricing_status"),
  merged 2026-08-14. Adds four tests to `tests/test_aggregate.py`:
  `test_build_rows_all_priced_facts_mark_row_priced` (baseline),
  `test_build_rows_mixed_priced_and_lower_bound_marks_row_lower_bound` (the
  previously-untested half — a `lower_bound` fact plus a `priced` fact
  should mark the row `lower_bound`),
  `test_build_rows_mixed_lower_bound_and_unpriced_marks_row_unpriced`, and
  `test_build_rows_worst_status_ranking_is_order_independent` (same three
  facts constructed in three different orders, same resulting status). Again,
  no implementation changes.

Both PRs are public and merged; the diffs and CI runs are the actual
evidence for this post, not my summary of them.

## 8. Boundary — what this does not show

To be precise about scope, since it's easy to over-read a post like this:

- **This is not a bug report.** Both gaps were missing regression tests for
  code that already behaved correctly — nothing shipped broken, nothing was
  fixed except test coverage.
- **`evidence-docs` does not check whether a claim is true.** Its own schema
  doc says so plainly: "the prose claim itself is never checked against the
  code... validation checks structure and provenance shape, not truth."
  What forced these two gaps into the open was *my own* process of trying to
  write an honest provenance pointer for each claim, not an automated
  truth-checker. A careless author could still write `execution_verified`
  next to a claim backed only by reading the source; the schema's
  `negation_check` field helps catch that but is optional and unenforced.
- **`gaps.yaml` completeness is not verified either.** A corpus with zero
  recorded gaps is syntactically valid; whether the author actually looked
  for contradictions isn't something the tool can check. GAP-03 in this
  corpus (a re-check of three README pricing claims against `rates.json`
  that found no drift) exists because I chose to record a negative result,
  not because anything required it.
- **This is an n=1 experience report on one small repo, not an evaluation.**
  No general effect size, no hit rate across repos, no claim that repeating
  this will surface N more gaps. It found two missing regression tests in
  one corpus-authoring pass over one repo I maintain. Trying the same
  process elsewhere might find zero, or something entirely different — the
  claim here is about what happened and how to reproduce the *process*, not
  what you should expect to get out of it.

## 9. Try it yourself

The minimal path that reproduces the "write a claim, discover you can't
honestly back it" moment:

```bash
pip install evidence-docs

evidence-docs init docs/claims
# scaffolds topics/, observations/, id-registry.yaml, gaps.yaml, README.md

# ... author one observation for a behavior you believe is true, with a
#     provenance entry naming the exact test that proves it. If you can't
#     name one, that's the gap. ...

evidence-docs validate docs/claims --repo-commit "$(git rev-parse HEAD)"
```

`validate` will reject an unregistered ID, an unknown `source_kind`, or a
digest that doesn't match the git blob at the commit you passed — all
useful on their own — but the actual gap-finding step is upstream of the
tool: it happens while you're trying to fill in the `provenance` field
honestly, before you ever run `validate`.

## Links

- [`shiki-yusuke/agent-cost`](https://github.com/shiki-yusuke/agent-cost) — the repo the corpus was written against
- [`shiki-yusuke/evidence-docs`](https://github.com/shiki-yusuke/evidence-docs) — the claim-corpus tool
- [`agent-cost#2`](https://github.com/shiki-yusuke/agent-cost/pull/2) — GAP-01 fix (merged)
- [`agent-cost#3`](https://github.com/shiki-yusuke/agent-cost/pull/3) — GAP-02 fix (merged)
- `docs/claims/gaps.yaml` in `agent-cost` — the gap ledger (GAP-01/02/03)
- `docs/schema.md` in `evidence-docs` — the trust-boundary write-up referenced throughout
