"""Scaffolding written by `evidence-docs init`.

Creates an empty, valid-shape corpus: topics/ and observations/ directories,
an empty id-registry.yaml and gaps.yaml, and a README.md carrying the
AUTO-GENERATED:COUNTS_TABLE marker pair `generate` needs (see
render_md.update_readme_counts_table) -- without it, the very first
`evidence-docs generate` on a freshly-initialized corpus would fail.
"""

from __future__ import annotations

from pathlib import Path

from .render_md import README_COUNTS_TABLE_END, README_COUNTS_TABLE_START

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

README_TEMPLATE = f"""\
# claim corpus

This directory is an `evidence-docs` claim corpus: human-authored `topics/`
and `observations/` (with `provenance` back to source/tests/spec), a stable
`id-registry.yaml`, and a `gaps.yaml` ledger of known unknowns.

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
    """

    created: list[str] = []
    dir_path.mkdir(parents=True, exist_ok=True)

    for sub in ("topics", "observations"):
        p = dir_path / sub
        if not p.is_dir():
            p.mkdir(parents=True)
            (p / ".gitkeep").write_text("", encoding="utf-8")
            created.append(str(p))

    registry_path = dir_path / "id-registry.yaml"
    if not registry_path.exists():
        registry_path.write_text(ID_REGISTRY_TEMPLATE.format(today=today), encoding="utf-8")
        created.append(str(registry_path))

    gaps_path = dir_path / "gaps.yaml"
    if not gaps_path.exists():
        gaps_path.write_text(GAPS_TEMPLATE, encoding="utf-8")
        created.append(str(gaps_path))

    readme_path = dir_path / "README.md"
    if not readme_path.exists():
        readme_path.write_text(README_TEMPLATE, encoding="utf-8")
        created.append(str(readme_path))

    return created
