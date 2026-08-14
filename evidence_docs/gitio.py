"""Git-backed provenance verification: resolving repo-relative uris safely,
and hashing the *declared-commit* content of a file rather than trusting
whatever is on disk right now.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from .errors import CorpusError


def _resolve_within(root: Path, relative: str) -> Path | None:
    """Resolve `root / relative` and return it only if it's still inside
    `root` once symlinks are followed and `..` is normalized; None if it
    escapes. Shared by the read-side guard (resolve_repo_path) and the
    write-side guard (resolve_write_path) below -- both need the exact same
    "does this really stay inside the root" check, just against different
    roots and with different error messages for the two directions.
    """

    root_resolved = root.resolve()
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return None
    return resolved


def resolve_repo_path(repo_root: Path, uri: str) -> Path:
    """Resolve a provenance uri as a repo-root-relative path, safely.

    resolve() follows symlinks to their real target and normalizes `..`
    segments, so "does this really live under repo_root" can be decided by
    whether relative_to() succeeds. That single check rejects both path
    traversal (e.g. `../../etc/passwd`) and symlink-based escape from the
    repo root.
    """

    resolved = _resolve_within(repo_root, uri)
    if resolved is None:
        raise CorpusError(f"provenance uri escapes repo root: {uri!r} -> {(repo_root / uri).resolve()}")
    return resolved


def resolve_write_path(corpus_dir: Path, relative: str) -> Path:
    """Resolve a path evidence-docs is about to WRITE to (site/, bundle/,
    README.md, and init's scaffold files), guaranteeing the write stays
    inside corpus_dir even if some path component -- an existing `site` or
    `bundle` directory, or README.md itself -- turns out to be a symlink.

    This is the write-side mirror of resolve_repo_path()'s read-side guard:
    without it, a corpus directory containing (or having had substituted
    in) a malicious symlink could redirect a `generate`/`init` write to an
    arbitrary path outside the corpus directory.
    """

    resolved = _resolve_within(corpus_dir, relative)
    if resolved is None:
        raise CorpusError(
            f"refusing to write outside the corpus directory: {relative!r} under "
            f"{corpus_dir} would resolve to {(corpus_dir / relative).resolve()}"
        )
    return resolved


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def is_safe_repo_relative_uri(uri) -> bool:
    """Structural check before handing `uri` to `git show <sha>:<uri>`.

    Rejects absolute paths, empty segments, and `..` segments. This is a
    separate check from resolve_repo_path(): that one resolves against the
    worktree filesystem, while `git show` walks the commit tree using plain
    string paths and never touches the filesystem, so it needs its own
    independent traversal guard.
    """

    if not isinstance(uri, str) or not uri or uri.startswith("/"):
        return False
    parts = uri.split("/")
    return not any(p in ("", "..") for p in parts)


class BlobDigestCache:
    """Memoizes `git show <repo_commit>:<uri>` blob hashing by (repo_commit, uri).

    A corpus with N observations frequently cites the same file (e.g. a
    shared source file backing several claims) across many provenance
    entries; without memoization each one triggers its own `git show`
    subprocess. The cache is instantiated fresh per generate/validate run
    so it never leaks state across unrelated corpora or repo roots.
    """

    def __init__(self, repo_root: Path):
        self._repo_root = repo_root
        self._cache: dict[tuple[str, str], str] = {}
        self.call_count = 0

    def sha256_of_git_blob(self, repo_commit: str, uri: str) -> str:
        key = (repo_commit, uri)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        digest = self._compute(repo_commit, uri)
        self._cache[key] = digest
        return digest

    def _compute(self, repo_commit: str, uri: str) -> str:
        """Hash the content of `uri` as it existed at `repo_commit` (the git blob),
        not whatever the worktree currently has on disk.

        Hashing the worktree file instead would let someone edit the file,
        update content_digest to match the new content, and leave
        repo_commit pointing at an older SHA -- the digest would "verify"
        against a state the declared commit never actually had.
        """

        if not is_safe_repo_relative_uri(uri):
            raise CorpusError(f"provenance uri is not a safe repo-relative path: {uri!r}")
        self.call_count += 1
        result = subprocess.run(
            ["git", "show", f"{repo_commit}:{uri}"],
            cwd=str(self._repo_root),
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", "replace").strip()
            raise CorpusError(
                f"git show {repo_commit}:{uri} failed (uri did not exist at that commit, or "
                f"repo_commit is unreachable in this checkout): {stderr}"
            )
        return hashlib.sha256(result.stdout).hexdigest()
