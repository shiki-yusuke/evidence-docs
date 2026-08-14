from src.task_store import TaskStore, resolve_task_scope_id


class FakeBackend:
    def __init__(self):
        self.deleted_prefixes = []
        self.written = {}
        self.pruned = []

    def delete_prefix(self, prefix):
        self.deleted_prefixes.append(prefix)

    def write(self, scope_id, tasks):
        self.written[scope_id] = tasks
        return True

    def prune_old_versions(self, scope_id):
        self.pruned.append(scope_id)


def test_resolve_scope_id_stable_for_existing_list():
    assert resolve_task_scope_id("42", "tok") == resolve_task_scope_id("42", "tok")


def test_resolve_scope_id_uses_new_list_token_when_list_id_blank():
    assert resolve_task_scope_id("", "tok-a") != resolve_task_scope_id("", "tok-b")


def test_save_prunes_old_versions_only_when_write_succeeds():
    backend = FakeBackend()
    store = TaskStore("list:42", backend)
    store.save([{"title": "buy milk"}])
    assert backend.pruned == ["list:42"]


def test_store_purges_legacy_cache_on_open():
    backend = FakeBackend()
    TaskStore("list:42", backend)
    assert backend.deleted_prefixes == ["legacy:list:42:"]
