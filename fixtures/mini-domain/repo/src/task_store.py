"""In-memory task store with scope-based isolation (fixture domain, not real product code)."""


def resolve_task_scope_id(list_id, new_list_token):
    """Derive a stable scope id for a task list.

    If list_id is given and non-blank (an existing list), returns a
    deterministic scope id derived from it, so repeated calls with the same
    list_id always agree. If list_id is missing or blank, falls back to a
    scope id derived from new_list_token instead, so concurrently created
    new lists don't collide with each other.
    """

    if list_id is not None and list_id.strip():
        return f"list:{list_id.strip()}"
    return f"new:{new_list_token}"


class TaskStore:
    """Persists tasks for a single scope, purging any legacy cache entries
    for that scope the first time the store is opened for that scope."""

    def __init__(self, scope_id, backend):
        self.scope_id = scope_id
        self.backend = backend
        self._purge_legacy_cache()

    def _purge_legacy_cache(self):
        self.backend.delete_prefix(f"legacy:{self.scope_id}:")

    def save(self, tasks):
        saved = self.backend.write(self.scope_id, tasks)
        if saved:
            self.backend.prune_old_versions(self.scope_id)
        return saved
