# Changelog

All notable changes to `evidence-docs`. This project is pre-1.0; the corpus schema
and CLI surface may still change between minor versions.

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
