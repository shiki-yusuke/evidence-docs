"""Scaffolding written by `evidence-docs init`.

Creates an empty, valid-shape corpus: topics/ and observations/ directories,
an empty id-registry.yaml and gaps.yaml, an EXAMPLE.md worked example, and a
README.md carrying the AUTO-GENERATED:COUNTS_TABLE marker pair `generate`
needs (see render_md.update_readme_counts_table) -- without it, the very
first `evidence-docs generate` on a freshly-initialized corpus would fail.

EXAMPLE.md's enum reference tables are generated from evidence_docs.schema's
own sets at scaffold time (never hand-copied), so they cannot drift out of
sync with what `validate` actually accepts; tests/test_init_templates.py
still cross-checks the rendered text against schema.py as a regression
guard against a future edit that hardcodes the strings instead.
"""

from __future__ import annotations

from pathlib import Path

from .gitio import resolve_write_path
from .render_md import README_COUNTS_TABLE_END, README_COUNTS_TABLE_START
from .schema import (
    ALL_SOURCE_KINDS,
    CLAIM_KINDS,
    CONFORMANCE_STATUSES,
    EPISTEMIC_STATUSES,
    ORIGINS,
    REVIEW_STATUSES,
    SOURCE_KINDS_REPO_EXTERNAL,
    SOURCE_KINDS_REPO_INTERNAL,
)

ID_REGISTRY_TEMPLATE = """\
schema_version: "1.0"
# Stable ID ledger for this corpus. topic_id / observation_id must never
# change meaning once minted (tools and external references key off them).
# `evidence-docs validate`/`generate` reject any topic_id/observation_id
# used in topics/ or observations/ that isn't registered here first, and
# any ID registered here that is never defined.
#
# Workflow:
# - mint a new topic/observation here before writing its file
# - never reuse or renumber an existing ID once minted
# - to retire an ID, do not delete the entry -- future tooling can add a
#   `status: retired` convention here if that becomes necessary
#
# `topics` and `observations` below are *mappings* keyed by ID (a YAML dict),
# never a list -- `registry["topics"][tid]` / `registry["observations"][oid]`
# is how corpus.py looks entries up. Each observations entry also needs its
# own `topic_id` (not just `minted_at`): corpus.py cross-checks it against
# the `topic_id` field inside the observation itself and rejects a mismatch.
# See EXAMPLE.md in this directory for a fully worked topic_id/observation_id
# pair in this exact shape, plus the enum reference for every observation
# field that only accepts a fixed set of values.
minted_at_default: "{today}"
topics: {{}}
observations: {{}}
"""

GAPS_TEMPLATE = """\
schema_version: "1.0"
# Record of gaps found (or explicitly searched-for-and-not-found) while
# building this corpus. See docs/schema.md for the gap taxonomy this
# ledger is meant to support.
gaps: []
"""


def _enum_block(name: str, values: frozenset[str] | set[str]) -> str:
    """A markdown snippet listing `values`, bounded by AUTO-GENERATED markers
    (same convention as render_md's README_COUNTS_TABLE markers) so
    tests/test_init_templates.py can extract exactly what `init` wrote and
    diff it against the live schema.py set -- catching the case where a
    future edit replaces this call with a hand-typed, driftable string.
    """

    listing = ", ".join(f"`{v}`" for v in sorted(values))
    return (
        f"<!-- AUTO-GENERATED:ENUM:{name}:START (generated from evidence_docs/schema.py "
        f"by `evidence-docs init`; do not hand-edit -- see tests/test_init_templates.py) -->\n"
        f"{listing}\n"
        f"<!-- AUTO-GENERATED:ENUM:{name}:END -->"
    )


def _backtick_list(values: frozenset[str] | set[str]) -> str:
    return ", ".join(f"`{v}`" for v in sorted(values))


_INTERNAL_SOURCE_KINDS = _backtick_list(SOURCE_KINDS_REPO_INTERNAL)
_EXTERNAL_SOURCE_KINDS = _backtick_list(SOURCE_KINDS_REPO_EXTERNAL)


def render_example_md(today: str) -> str:
    """Build EXAMPLE.md's content.

    This is a function (not a `.format()`-style template like
    ID_REGISTRY_TEMPLATE) because the body already needs f-string
    interpolation for the enum blocks below; layering a second `.format(
    today=...)` pass on top of an f-string's output is broken -- the
    literal `{observations: [...]}` this text also needs to show verbatim
    would itself look like a second format() placeholder and blow up with
    `KeyError: 'observations'`. Taking `today` as a real f-string variable
    here avoids that trap entirely.
    """

    return f"""\
# worked example: one topic + one observation

This file is documentation only. Nothing under `topics/`, `observations/`,
or `id-registry.yaml` in a freshly-initialized corpus references it, and
`evidence-docs validate`/`generate` never read it -- it exists purely so you
don't have to reconstruct the corpus's exact on-disk shape from
`docs/schema.md` and the `evidence-docs` source by trial and error. Copy the
three shapes below, replace every `REPLACE_ME`, mint the ID(s) you use in
`id-registry.yaml` first, then run:

```bash
evidence-docs validate . --repo-commit <full-40-char-git-sha>
```

`content_digest` for a `source`/`test`/`spec` provenance entry must be the
real sha256 of that file's content *at `repo_commit`* (the git blob, not
necessarily whatever's on disk right now). One way to compute it once the
file is committed:

```bash
git show <repo_commit>:<uri> | sha256sum
```

## 1. `id-registry.yaml` -- `topics`/`observations` are *mappings* keyed by ID, never a list

```yaml
topics:
  T-01:
    slug: REPLACE_ME-short-topic-slug
    minted_at: "{today}"
observations:
  OBS-001:
    topic_id: T-01   # required here too -- must match the observation's own
                     # topic_id field below exactly, or validate rejects it
    minted_at: "{today}"
```

## 2. `topics/T-01-REPLACE_ME.yaml`

```yaml
topic_id: T-01
title: REPLACE_ME human-readable title
description: REPLACE_ME what this topic covers, one or two sentences
representative_symbols: [REPLACE_ME_function_or_class_name]
representative_paths: [REPLACE_ME/path/in/repo.py]
related_topics: []   # topic_ids of related topics, cross-checked to exist
```

## 3. `observations/T-01-REPLACE_ME.yaml` -- top level is `{{observations: [...]}}`, a list of one or more observations, *not* a single observation document

```yaml
observations:
  - observation_id: OBS-001
    topic_id: T-01
    claim_kind: behavior                    # see claim_kind reference below
    statement: REPLACE_ME what you observed, one sentence
    origin: reconstructed                   # see origin reference below
    epistemic_status: execution_verified    # see epistemic_status reference below
    review_status: unreviewed               # see review_status reference below
    conformance_status: matched             # see conformance_status reference below
    # negation_check is optional but expected for execution_verified claims:
    # a short record of the test-broke-red check you performed (see
    # fixtures/mini-domain/corpus/observations/T-01-scope-id-derivation.yaml
    # in the evidence-docs source for a real example).
    subject_refs: [REPLACE_ME_symbol]
    supporting_refs: []
    contradicting_refs: []
    valid_at_commit: REPLACE_ME_full_40_char_git_sha   # must equal --repo-commit
    affected_paths: [REPLACE_ME/path/in/repo.py]
    provenance:
      - source_kind: source                 # see provenance.source_kind reference below
        uri: REPLACE_ME/path/in/repo.py
        selector: REPLACE_ME_symbol
        content_digest: REPLACE_ME_sha256_hex_of_the_git_blob_at_repo_commit
        repo_commit: REPLACE_ME_full_40_char_git_sha   # must equal --repo-commit and valid_at_commit
        extraction_method: REPLACE_ME e.g. static-read-source
        observed_at: "{today}T00:00:00Z"    # UTC ISO 8601, trailing Z or +00:00 required
```

## Enum reference

Every field below only accepts one of the listed values -- anything else
(a plausible-looking guess included, e.g. `reviewed` instead of
`reviewed_accepted`) fails `validate`.

### claim_kind

{_enum_block("claim_kind", CLAIM_KINDS)}

### origin

{_enum_block("origin", ORIGINS)}

### epistemic_status

{_enum_block("epistemic_status", EPISTEMIC_STATUSES)}

### conformance_status

{_enum_block("conformance_status", CONFORMANCE_STATUSES)}

### review_status

{_enum_block("review_status", REVIEW_STATUSES)}

### provenance.source_kind

{_enum_block("source_kind", ALL_SOURCE_KINDS)}

{_INTERNAL_SOURCE_KINDS} are verified against the actual git blob at
`--repo-commit`: `content_digest` must be the real sha256 of that file's
content at that commit. {_EXTERNAL_SOURCE_KINDS} has no repo blob to hash
against, so only the *shape* of `uri`/`content_digest` is checked (a sha256
hex string, or the sentinel `not_computed_external_to_repo`).
"""

README_TEMPLATE = f"""\
# claim corpus

This directory is an `evidence-docs` claim corpus: human-authored `topics/`
and `observations/` (with `provenance` back to source/tests/spec), a stable
`id-registry.yaml`, and a `gaps.yaml` ledger of known unknowns.

**New to this corpus's on-disk shape?** See `EXAMPLE.md` in this directory
for a fully worked topic + observation you can copy and edit, and the full
enum reference for every field that only accepts a fixed set of values.

Regenerate the human-readable `site/` and AI-facing `bundle/` with:

```bash
evidence-docs generate . --generated-at <ISO8601Z> --repo-commit <full-sha>
```

See `docs/schema.md` in the `evidence-docs` package for what is and is not
verified by `validate`/`generate`.

## Observation counts

{README_COUNTS_TABLE_START}
(run `evidence-docs generate` to fill this in)
{README_COUNTS_TABLE_END}
"""


def scaffold(dir_path: Path, today: str) -> list[str]:
    """Create the corpus skeleton under dir_path. Idempotent: files/dirs that
    already exist are left untouched (reported, not overwritten).

    Every write is resolved through resolve_write_path() first, so a
    dir_path that already contains a symlinked `topics`/`observations`/
    `id-registry.yaml`/etc. (e.g. re-running init against a corpus checked
    out from an untrusted source) can't redirect a write outside dir_path.
    """

    created: list[str] = []
    dir_path.mkdir(parents=True, exist_ok=True)

    for sub in ("topics", "observations"):
        p = resolve_write_path(dir_path, sub)
        if not p.is_dir():
            p.mkdir(parents=True)
            resolve_write_path(dir_path, f"{sub}/.gitkeep").write_text("", encoding="utf-8")
            created.append(str(p))

    registry_path = resolve_write_path(dir_path, "id-registry.yaml")
    if not registry_path.exists():
        registry_path.write_text(ID_REGISTRY_TEMPLATE.format(today=today), encoding="utf-8")
        created.append(str(registry_path))

    gaps_path = resolve_write_path(dir_path, "gaps.yaml")
    if not gaps_path.exists():
        gaps_path.write_text(GAPS_TEMPLATE, encoding="utf-8")
        created.append(str(gaps_path))

    readme_path = resolve_write_path(dir_path, "README.md")
    if not readme_path.exists():
        readme_path.write_text(README_TEMPLATE, encoding="utf-8")
        created.append(str(readme_path))

    example_path = resolve_write_path(dir_path, "EXAMPLE.md")
    if not example_path.exists():
        example_path.write_text(render_example_md(today), encoding="utf-8")
        created.append(str(example_path))

    return created
