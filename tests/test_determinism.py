"""generate() must be a pure function of (corpus files, generated_at, repo_commit,
repo_root): the same inputs run twice produce byte-identical output."""

from __future__ import annotations

import shutil

from evidence_docs.bundle import generate


def _snapshot(corpus_dir):
    out = {}
    for sub in ("site", "bundle"):
        d = corpus_dir / sub
        for f in sorted(d.rglob("*")):
            if f.is_file():
                out[str(f.relative_to(corpus_dir))] = f.read_bytes()
    return out


def test_generate_twice_is_byte_identical(mini_domain, tmp_path):
    run_a = tmp_path / "run-a"
    run_b = tmp_path / "run-b"
    shutil.copytree(mini_domain.corpus_dir, run_a)
    shutil.copytree(mini_domain.corpus_dir, run_b)

    generate(run_a, "2026-08-09T10:30:00Z", mini_domain.repo_commit, mini_domain.repo_root)
    generate(run_b, "2026-08-09T10:30:00Z", mini_domain.repo_commit, mini_domain.repo_root)

    snap_a = _snapshot(run_a)
    snap_b = _snapshot(run_b)
    assert snap_a.keys() == snap_b.keys()
    for name in snap_a:
        assert snap_a[name] == snap_b[name], f"{name} differs between runs"


def test_regenerating_in_place_is_byte_identical(mini_domain):
    generate(mini_domain.corpus_dir, "2026-08-09T10:30:00Z", mini_domain.repo_commit, mini_domain.repo_root)
    first = _snapshot(mini_domain.corpus_dir)

    generate(mini_domain.corpus_dir, "2026-08-09T10:30:00Z", mini_domain.repo_commit, mini_domain.repo_root)
    second = _snapshot(mini_domain.corpus_dir)

    assert first == second
