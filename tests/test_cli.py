"""CLI subcommand behavior: init / validate / generate / context, exit codes,
and stdout/stderr shape."""

from __future__ import annotations

import json

from evidence_docs.cli import main


def test_init_creates_scaffold_and_exits_zero(tmp_path, capsys):
    corpus_dir = tmp_path / "new-corpus"
    rc = main(["init", str(corpus_dir)])
    assert rc == 0
    assert (corpus_dir / "id-registry.yaml").is_file()
    assert (corpus_dir / "gaps.yaml").is_file()
    assert (corpus_dir / "README.md").is_file()
    assert (corpus_dir / "topics").is_dir()
    assert (corpus_dir / "observations").is_dir()


def test_init_twice_is_idempotent(tmp_path, capsys):
    corpus_dir = tmp_path / "new-corpus"
    main(["init", str(corpus_dir)])
    capsys.readouterr()
    rc = main(["init", str(corpus_dir)])
    assert rc == 0
    assert "nothing to do" in capsys.readouterr().err


def test_validate_passes_on_mini_domain(mini_domain, capsys):
    rc = main(
        [
            "validate",
            str(mini_domain.corpus_dir),
            "--repo-commit",
            mini_domain.repo_commit,
            "--repo-root",
            str(mini_domain.repo_root),
        ]
    )
    assert rc == 0
    assert "ok:" in capsys.readouterr().err


def test_validate_rejects_malformed_repo_commit(mini_domain, capsys):
    rc = main(
        [
            "validate",
            str(mini_domain.corpus_dir),
            "--repo-commit",
            "not-a-sha",
            "--repo-root",
            str(mini_domain.repo_root),
        ]
    )
    assert rc == 1
    assert "40-character hex git SHA" in capsys.readouterr().err


def test_validate_rejects_mismatched_repo_commit(mini_domain, capsys):
    rc = main(
        [
            "validate",
            str(mini_domain.corpus_dir),
            "--repo-commit",
            "b" * 40,
            "--repo-root",
            str(mini_domain.repo_root),
        ]
    )
    assert rc == 1
    assert "does not match" in capsys.readouterr().err


def test_generate_writes_bundle_and_exits_zero(mini_domain, capsys):
    rc = main(
        [
            "generate",
            str(mini_domain.corpus_dir),
            "--generated-at",
            "2026-08-09T10:30:00Z",
            "--repo-commit",
            mini_domain.repo_commit,
            "--repo-root",
            str(mini_domain.repo_root),
        ]
    )
    assert rc == 0
    assert (mini_domain.corpus_dir / "bundle" / "manifest.json").is_file()
    err = capsys.readouterr().err
    assert "generated 8 observations across 3 topics" in err
    assert "corpus_digest=" in err


def test_generate_rejects_bad_generated_at(mini_domain, capsys):
    rc = main(
        [
            "generate",
            str(mini_domain.corpus_dir),
            "--generated-at",
            "not-a-date",
            "--repo-commit",
            mini_domain.repo_commit,
            "--repo-root",
            str(mini_domain.repo_root),
        ]
    )
    assert rc == 1
    assert "ISO 8601" in capsys.readouterr().err


def test_context_returns_json_on_stdout(mini_domain, capsys):
    main(
        [
            "generate",
            str(mini_domain.corpus_dir),
            "--generated-at",
            "2026-08-09T10:30:00Z",
            "--repo-commit",
            mini_domain.repo_commit,
            "--repo-root",
            str(mini_domain.repo_root),
        ]
    )
    capsys.readouterr()

    rc = main(
        [
            "context",
            str(mini_domain.corpus_dir),
            "--query",
            json.dumps({"seeds": {"topic_ids": ["T-01"]}}),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert "claims" in payload
    assert len(payload["claims"]) >= 3


def test_context_accepts_query_from_file(mini_domain, tmp_path, capsys):
    main(
        [
            "generate",
            str(mini_domain.corpus_dir),
            "--generated-at",
            "2026-08-09T10:30:00Z",
            "--repo-commit",
            mini_domain.repo_commit,
            "--repo-root",
            str(mini_domain.repo_root),
        ]
    )
    capsys.readouterr()

    query_file = tmp_path / "query.json"
    query_file.write_text(json.dumps({"seeds": {"topic_ids": ["T-02"]}}), encoding="utf-8")
    rc = main(["context", str(mini_domain.corpus_dir), "--query", str(query_file)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["claims"]) >= 1


def test_context_rejects_invalid_json(mini_domain, capsys):
    rc = main(["context", str(mini_domain.corpus_dir), "--query", "{not json"])
    assert rc == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_context_before_generate_fails_helpfully(mini_domain, capsys):
    rc = main(["context", str(mini_domain.corpus_dir), "--query", "{}"])
    assert rc == 1


def test_context_rejects_malformed_query_shape_with_exit_2(mini_domain, capsys):
    main(
        [
            "generate",
            str(mini_domain.corpus_dir),
            "--generated-at",
            "2026-08-09T10:30:00Z",
            "--repo-commit",
            mini_domain.repo_commit,
            "--repo-root",
            str(mini_domain.repo_root),
        ]
    )
    capsys.readouterr()

    rc = main(["context", str(mini_domain.corpus_dir), "--query", json.dumps({"token_budget": -1})])
    assert rc == 2
    assert "--query is invalid" in capsys.readouterr().err

