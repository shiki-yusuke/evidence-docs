# Changelog

All notable changes to `evidence-docs`. This project is pre-1.0; the corpus schema
and CLI surface may still change between minor versions.

## 0.3.0 (2026-10-19)

### Added
- `evidence-docs explain` and the `explanations/` namespace: a deterministic,
  LLM-free, non-authoritative (`authority: none`) list of the claims touching a change
  scope (`impact-scan:v1`, lane's `ImpactScanSnapshot`). One file per scope
  (`explanations/EXP-<sha256(scope)[:16]>.json`); re-running `explain` overwrites it.
- When `explanations/` exists, `validate` (and therefore `generate`) re-builds every
  explanation from its stored scope + `generated_at` and the current corpus, and rejects
  stale, hand-edited, renamed, symlinked or malformed files. See `docs/schema.md`,
  "Explanations (authority: none)".

### Changed
- `validate` (and `generate`) now rejects any topic / observation / gap / id-registry
  string value or key containing `EXP-<16 hex>` or `explanations/`: authoritative
  records must never reference an explanation. This applies even when no
  `explanations/` directory exists. Corpora that contain neither string are unaffected,
  and `validate` / `generate` output for them is unchanged.

### Fixed
- `evidence-docs --version` reported `0.1.0` on 0.2.0: the package version now has one
  source (`evidence_docs.__version__`, read by `pyproject.toml` as a dynamic field). The
  same string is what `explain` writes into `generator.version`.

## 0.2.0

First-use experience. Nothing about corpus validation itself changed -- `validate`,
`generate` and `context` behave exactly as in 0.1.0.

### Added
- `evidence-docs demo` — a self-contained walkthrough that builds a throwaway git repo,
  writes one provenance-backed observation against it, shows `validate` passing, then
  breaks the same corpus three different ways (stale `content_digest` after a real code
  change, a typo'd `source_kind`, a `repo_commit` pointing elsewhere) and shows each
  rejection with its reason. It runs the production `validate` path, not a demo-only
  check, so what you see is what your own corpus will get.
- `evidence-docs init` now also scaffolds `EXAMPLE.md`: a copy-pasteable worked example
  of the three file shapes (`id-registry.yaml`, a topic, an observation) plus a
  reference listing every valid value of each enum. The enum lists are generated from
  the schema module itself and a test fails if they ever drift from it.

### Why
Authoring a first corpus by hand from an empty scaffold turned out to be the real
barrier: four consecutive attempts failed on shape alone (registry as a list instead of
a mapping, a missing `topic_id` on the registry entry, the observations file layout, an
invalid `review_status`) even with a working corpus open for reference. The content was
never the problem; the shape was.
