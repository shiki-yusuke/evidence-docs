# evidence-docs

Deterministic, verifiable **claim corpora** for AI-assisted codebase
documentation: human-authored `topics` and `observations` with explicit
`provenance` back to source/tests/spec, validated against real git history
and rendered into both a human-readable Markdown site and an AI-facing
context bundle.

`evidence-docs` grew out of documenting a single change to a real codebase
as a set of small, individually-sourced claims instead of one big
freeform writeup, and hardening the validator against every way that
approach can be gamed or drift silently (see [`docs/schema.md`](docs/schema.md)
for the full trust-boundary write-up).

## Why a claim corpus instead of a doc?

A normal doc is one blob of prose that is either entirely trusted or
entirely suspect. A claim corpus instead splits it into many small
`observation`s, each with:

- a `claim_kind` (`behavior`, `invariant`, `constraint`, `interface`,
  `dependency`, `failure_mode`, `decision_record`),
- an `epistemic_status` (how strongly it's been checked -- from
  `execution_verified` down to `model_inference`),
- explicit `provenance`: which file/test/spec it came from, and a content
  hash of that source *at the commit the claim was authored against*.

`evidence-docs validate`/`generate` re-check that hash against the actual
git blob at the declared commit, reject unknown/typo'd source kinds, and
reject any observation whose declared commit doesn't match the one you're
generating for. The result is a corpus where "this claim is
`execution_verified`" means something a machine can double-check, not just
something an author asserted.

## Install

```bash
pip install evidence-docs
```

(Python 3.9+, one dependency: PyYAML.)

## Quick start

```bash
evidence-docs init docs/claims
# ... author topics/*.yaml and observations/*.yaml, registering each new
#     topic_id/observation_id in id-registry.yaml first ...

evidence-docs validate docs/claims --repo-commit <full-git-sha>

evidence-docs generate docs/claims \
  --generated-at 2026-08-09T10:30:00Z \
  --repo-commit <full-git-sha>
# writes docs/claims/site/index.md (human-readable) and
# docs/claims/bundle/*.jsonl + manifest.json (AI-facing)

evidence-docs context docs/claims \
  --query '{"seeds": {"paths": ["src/foo.py"]}, "token_budget": 4000}'
# prints a JSON selection of claims relevant to those seed paths, stdout
```

`--generated-at` and `--repo-commit` are always explicit arguments, never
derived from `datetime.now()` or `git rev-parse` at run time -- the same
corpus + the same arguments always produce byte-identical `site/`/`bundle/`
output from `generate`, and the same bundle + query always produce the same
result from `context`. This determinism guarantee is scoped to `generate`
and `context` specifically: `init` stamps `id-registry.yaml` with today's
date as a human-readable authoring hint, which has no bearing on any
corpus's validity or on `generate`/`context` output.

## Commands

| command | what it does |
|---|---|
| `init <dir>` | scaffold `topics/`, `observations/`, `id-registry.yaml`, `gaps.yaml`, `README.md` |
| `validate <dir> --repo-commit <sha> [--repo-root <path>]` | full corpus validation, no output written (CI-friendly exit 0/1) |
| `generate <dir> --generated-at <iso> --repo-commit <sha> [--repo-root <path>]` | validate, then deterministically write `site/index.md` + `bundle/*` |
| `context <dir> --query <json\|path>` | select claims from `bundle/` for a query (`seeds.paths` / `seeds.topic_ids`, optional `token_budget`); v0 retrieval, see `docs/schema.md` |

`--repo-root` defaults to the corpus directory itself; a relative
`--repo-root` is resolved against the corpus directory, not your shell's
current directory.

## What's verified, what isn't

See [`docs/schema.md`](docs/schema.md) for the full write-up: the
source_kind allow-list, the three-stage history behind content-digest
verification (format check → worktree hash → declared-commit git blob
hash), why `provenance.observed_at` must be UTC ISO 8601 with an explicit
offset, why `revision_digest` excludes `observed_at`, and -- just as
important -- what is deliberately *not* checked (statement truthfulness,
`affected_paths` completeness, whether an author's `epistemic_status` is
honest).

## Case study

[Writing evidence-linked docs exposed two missing regression
tests](docs/articles/writing-evidence-linked-docs-exposed-two-missing-regression-tests.md) —
how authoring a claim corpus against a real codebase
([agent-cost](https://github.com/shiki-yusuke/agent-cost)) surfaced two missing regression
tests, both since closed by merged PRs.

## Fixtures / examples

`fixtures/mini-domain/` is a small synthetic domain (a fictional in-memory
task store) used by the test suite as a runnable example: `fixtures/mini-domain/corpus/`
is a complete corpus, `fixtures/mini-domain/repo/` is the source tree its
provenance points at.

## License

MIT, see [LICENSE](LICENSE).

---

## 日本語での簡単な案内

`evidence-docs` は、コードベースに関する主張（claim）を「誰が・どのソースを・どの粒度で
裏付けたか」を明示する形で記録し、宣言されたコミット時点の git blob と実際に照合してから
人間向け Markdown と AI 向け context bundle を決定的に生成する CLI ツールです。検証ロジックの
詳細（何を検証し、何を検証しないか）は `docs/schema.md` を参照してください。
