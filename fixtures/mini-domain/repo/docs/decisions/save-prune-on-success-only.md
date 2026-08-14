# Decision: only prune old versions after a successful write

`TaskStore.save()` calls `backend.prune_old_versions(scope_id)` only when
`backend.write(...)` returned a truthy result. If pruning ran unconditionally,
a failed write would leave the newly-pruned version metadata pointing at
content that was never actually persisted, corrupting any restore-from-version
feature built on top of it later.

Decided: 2026-07-20. Status: accepted.
