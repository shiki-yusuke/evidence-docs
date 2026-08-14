# Design note: legacy cache cleanup placement (superseded)

This note originally called for legacy cache cleanup to be exposed as a
module-level `purge_legacy_cache(scope_id, backend)` function next to
`resolve_task_scope_id`, so callers could invoke it independently of
constructing a `TaskStore`.

The implementation instead added it as a private `TaskStore._purge_legacy_cache()`
method invoked from `__init__`. This was accepted as-is: no caller needs to
purge a scope without also opening a store for it, and keeping it private
avoids a second, separately-tested public entry point for the same cleanup.
