"""resolve_write_path() and its use in generate()/init: a symlinked site/,
bundle/, or README.md inside a corpus directory must not redirect a write
outside that directory."""

from __future__ import annotations

import pytest

from evidence_docs.bundle import generate
from evidence_docs.errors import CorpusError
from evidence_docs.gitio import resolve_write_path
from evidence_docs.init_templates import scaffold


def test_resolve_write_path_accepts_normal_relative_path(tmp_path):
    resolved = resolve_write_path(tmp_path, "bundle/manifest.json")
    assert resolved == (tmp_path / "bundle" / "manifest.json").resolve()


def test_resolve_write_path_rejects_path_traversal(tmp_path):
    with pytest.raises(CorpusError, match="refusing to write outside"):
        resolve_write_path(tmp_path, "../../etc/passwd")


def test_resolve_write_path_rejects_symlinked_subdirectory_escape(tmp_path):
    outside = tmp_path.parent / "outside-dir"
    outside.mkdir(exist_ok=True)
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "site").symlink_to(outside, target_is_directory=True)

    with pytest.raises(CorpusError, match="refusing to write outside"):
        resolve_write_path(corpus_dir, "site/index.md")


def test_resolve_write_path_rejects_symlinked_leaf_file_escape(tmp_path):
    outside_file = tmp_path.parent / "outside-secret.md"
    outside_file.write_text("do not touch", encoding="utf-8")
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "README.md").symlink_to(outside_file)

    with pytest.raises(CorpusError, match="refusing to write outside"):
        resolve_write_path(corpus_dir, "README.md")


def test_resolve_write_path_rejects_broken_symlink_escape(tmp_path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "bundle").symlink_to(tmp_path.parent / "nonexistent-target", target_is_directory=True)

    with pytest.raises(CorpusError, match="refusing to write outside"):
        resolve_write_path(corpus_dir, "bundle/manifest.json")


def test_resolve_write_path_accepts_symlink_pointing_back_inside_corpus_dir(tmp_path):
    corpus_dir = tmp_path / "corpus"
    real_site = corpus_dir / "real-site"
    real_site.mkdir(parents=True)
    (corpus_dir / "site").symlink_to(real_site, target_is_directory=True)

    resolved = resolve_write_path(corpus_dir, "site/index.md")
    assert resolved == (real_site / "index.md").resolve()


def test_init_scaffold_rejects_preexisting_malicious_symlink(tmp_path):
    outside = tmp_path.parent / "outside-topics"
    outside.mkdir(exist_ok=True)
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "topics").symlink_to(outside, target_is_directory=True)

    with pytest.raises(CorpusError, match="refusing to write outside"):
        scaffold(corpus_dir, "2026-08-01")


def test_generate_rejects_symlinked_site_directory(mini_domain, tmp_path):
    outside = tmp_path / "outside-site"
    outside.mkdir()
    (mini_domain.corpus_dir / "site").symlink_to(outside, target_is_directory=True)

    with pytest.raises(CorpusError, match="refusing to write outside"):
        generate(mini_domain.corpus_dir, "2026-08-09T10:30:00Z", mini_domain.repo_commit, mini_domain.repo_root)

    assert not any(outside.iterdir())  # nothing was written through the symlink


def test_generate_rejects_symlinked_bundle_directory(mini_domain, tmp_path):
    outside = tmp_path / "outside-bundle"
    outside.mkdir()
    (mini_domain.corpus_dir / "bundle").symlink_to(outside, target_is_directory=True)

    with pytest.raises(CorpusError, match="refusing to write outside"):
        generate(mini_domain.corpus_dir, "2026-08-09T10:30:00Z", mini_domain.repo_commit, mini_domain.repo_root)

    assert not any(outside.iterdir())


def test_generate_rejects_symlinked_readme(mini_domain, tmp_path):
    outside_readme = tmp_path / "outside-README.md"
    outside_readme.write_text("do not touch", encoding="utf-8")
    (mini_domain.corpus_dir / "README.md").unlink()
    (mini_domain.corpus_dir / "README.md").symlink_to(outside_readme)

    with pytest.raises(CorpusError, match="refusing to write outside"):
        generate(mini_domain.corpus_dir, "2026-08-09T10:30:00Z", mini_domain.repo_commit, mini_domain.repo_root)

    assert outside_readme.read_text(encoding="utf-8") == "do not touch"
