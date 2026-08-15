"""`evidence-docs demo`: a self-contained, disposable walkthrough to a first
verified result.

This builds a tiny *real* git repo (1 source file + 1 test, 1 commit) in a
throwaway temp directory, authors one observation whose provenance genuinely
points at that repo and whose `content_digest` genuinely matches the git blob
at that commit, and runs it through `validate` -- the exact same
`evidence_docs.bundle.validate` entry point the `validate` subcommand calls.
It then breaks a copy of that same corpus three different ways and runs each
through the same `validate` path again, to show what each check actually
catches.

No validation logic is duplicated here: every PASS/FAIL below is a real
`evidence_docs.bundle.validate()` call. This module only builds fixtures and
narrates the result.
"""

from __future__ import annotations

import copy
import datetime
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TextIO

import yaml

from .bundle import validate as run_validate
from .errors import CorpusError
from .gitio import BlobDigestCache
from .init_templates import scaffold

SRC_V1 = '''"""A tiny function this demo will make a claim about."""


def greet(name: str) -> str:
    return f"Hello, {name}!"
'''

SRC_V2 = '''"""A tiny function this demo will make a claim about."""


def greet(name: str) -> str:
    return f"Hi there, {name}!"
'''

TEST_SRC = '''from src.greeter import greet


def test_greet_includes_name():
    assert greet("World") == "Hello, World!"
'''

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "evidence-docs demo",
    "GIT_AUTHOR_EMAIL": "demo@example.invalid",
    "GIT_COMMITTER_NAME": "evidence-docs demo",
    "GIT_COMMITTER_EMAIL": "demo@example.invalid",
}


def _git_env() -> dict:
    env = dict(os.environ)
    env.update(_GIT_ENV)
    return env


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=_git_env(),
        capture_output=True,
        text=True,
        check=True,
    )


def _init_repo(repo_root: Path) -> None:
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "tests").mkdir(parents=True)
    _run_git(["init", "-q", "-b", "main"], repo_root)


def _commit_all(repo_root: Path, message: str) -> str:
    _run_git(["add", "-A"], repo_root)
    _run_git(["-c", "commit.gpgsign=false", "commit", "-q", "-m", message], repo_root)
    return _run_git(["rev-parse", "HEAD"], repo_root).stdout.strip()


def _write_corpus(corpus_dir: Path, today: str, topic: dict, observation: dict) -> None:
    """Scaffold a corpus (reusing the same `scaffold()` `init` calls) and fill
    in one topic + one observation + its id-registry entries."""

    scaffold(corpus_dir, today)
    (corpus_dir / "topics" / "T-01-greeting.yaml").write_text(
        yaml.safe_dump(topic, sort_keys=False), encoding="utf-8"
    )
    (corpus_dir / "observations" / "T-01-greeting.yaml").write_text(
        yaml.safe_dump({"observations": [observation]}, sort_keys=False), encoding="utf-8"
    )
    registry = {
        "schema_version": "1.0",
        "minted_at_default": today,
        "topics": {"T-01": {"slug": "greeting-behavior", "minted_at": today}},
        "observations": {"OBS-001": {"topic_id": "T-01", "minted_at": today}},
    }
    (corpus_dir / "id-registry.yaml").write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")


def _try_validate(corpus_dir: Path, repo_commit: str, repo_root: Path) -> tuple[bool, str]:
    """Run the real validate() entry point and report PASS/FAIL the same way
    `_cmd_validate` in cli.py does -- this is not a demo-only check."""

    try:
        result = run_validate(corpus_dir, repo_commit, repo_root)
    except CorpusError as e:
        return False, str(e)
    lines = [f"ok: {len(result.corpus.observations)} observations across {len(result.corpus.topics)} topics validated"]
    lines += [f"warning: {w}" for w in result.warnings]
    return True, "\n".join(lines)


def run_demo(out: TextIO | None = None) -> int:
    out = out or sys.stdout
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    checks_as_expected = True

    def p(line: str = "") -> None:
        print(line, file=out)

    def report(label: str, corpus_dir: Path, repo_commit: str, ok: bool, message: str) -> None:
        status = "PASS" if ok else "FAIL"
        p(f"    evidence-docs validate {corpus_dir.name} --repo-commit {repo_commit[:12]}...  -> {status}")
        for line in message.splitlines():
            p(f"      {line}")

    with tempfile.TemporaryDirectory(prefix="evidence-docs-demo-") as tmp:
        tmp_path = Path(tmp)
        repo_root = tmp_path / "repo"
        _init_repo(repo_root)
        (repo_root / "src" / "greeter.py").write_text(SRC_V1, encoding="utf-8")
        (repo_root / "tests" / "test_greeter.py").write_text(TEST_SRC, encoding="utf-8")
        commit1 = _commit_all(repo_root, "initial: greet() + its test")

        p("=== evidence-docs demo: first verified result ===")
        p()
        p("[1/5] built a throwaway git repo (1 source file, 1 test, 1 commit)")
        p(f"      repo path: {repo_root}")
        p(f"      commit:    {commit1}")
        p()

        cache = BlobDigestCache(repo_root)
        test_digest1 = cache.sha256_of_git_blob(commit1, "tests/test_greeter.py")
        src_digest1 = cache.sha256_of_git_blob(commit1, "src/greeter.py")

        topic = {
            "topic_id": "T-01",
            "title": "greet() greeting format",
            "description": "What greet(name) returns for a given name.",
            "representative_symbols": ["greet"],
            "representative_paths": ["src/greeter.py"],
            "related_topics": [],
        }
        observation = {
            "observation_id": "OBS-001",
            "topic_id": "T-01",
            "claim_kind": "behavior",
            "statement": "greet(name) returns the string 'Hello, {name}!' for any name.",
            "origin": "reconstructed",
            "epistemic_status": "execution_verified",
            "review_status": "unreviewed",
            "conformance_status": "matched",
            "subject_refs": ["greet"],
            "provenance": [
                {
                    "source_kind": "test",
                    "uri": "tests/test_greeter.py",
                    "selector": "test_greet_includes_name",
                    "content_digest": test_digest1,
                    "repo_commit": commit1,
                    "extraction_method": "static-read-test-assertions",
                    "observed_at": "2026-01-01T00:00:00Z",
                },
                {
                    "source_kind": "source",
                    "uri": "src/greeter.py",
                    "selector": "greet",
                    "content_digest": src_digest1,
                    "repo_commit": commit1,
                    "extraction_method": "static-read-source",
                    "observed_at": "2026-01-01T00:00:00Z",
                },
            ],
            "supporting_refs": [],
            "contradicting_refs": [],
            "valid_at_commit": commit1,
            "affected_paths": ["src/greeter.py"],
        }

        corpus_pass = tmp_path / "corpus-pass"
        _write_corpus(corpus_pass, today, topic, observation)

        p("[2/5] wrote one observation, with provenance pointing at that real test and source file")
        p(f'      OBS-001: "{observation["statement"]}"')
        p("      provenance: tests/test_greeter.py (test), src/greeter.py (source)")
        p()

        ok_pass, msg_pass = _try_validate(corpus_pass, commit1, repo_root)
        p("[3/5] validate the untouched corpus")
        report("pass", corpus_pass, commit1, ok_pass, msg_pass)
        if ok_pass:
            p("      -> what this confirmed: tests/test_greeter.py and src/greeter.py, as cited by")
            p(f"         OBS-001, are byte-for-byte identical to the actual git blobs at commit {commit1[:12]} --")
            p("         not merely recomputed from whatever happens to be on disk right now.")
        checks_as_expected = checks_as_expected and ok_pass
        p()

        # A second, real commit: the source changes, but (in Break A below) the
        # corpus gets re-pointed at it without anyone re-verifying content_digest.
        (repo_root / "src" / "greeter.py").write_text(SRC_V2, encoding="utf-8")
        commit2 = _commit_all(repo_root, "change greet() wording")

        p("[4/5] now breaking a copy of the same corpus three different ways")
        p()

        # Break A: source changed at a new commit; corpus re-pointed at it;
        # content_digest left stale (the classic "forgot to re-verify" bypass).
        obs_a = copy.deepcopy(observation)
        obs_a["valid_at_commit"] = commit2
        for prov in obs_a["provenance"]:
            prov["repo_commit"] = commit2
        corpus_a = tmp_path / "corpus-break-digest"
        _write_corpus(corpus_a, today, topic, obs_a)
        ok_a, msg_a = _try_validate(corpus_a, commit2, repo_root)
        p("  Break A: src/greeter.py changed in a new commit; the corpus was re-pointed at that")
        p("           commit, but content_digest was never recomputed (stale)")
        report("break-digest", corpus_a, commit2, ok_a, msg_a)
        checks_as_expected = checks_as_expected and not ok_a
        p()

        # Break B: source_kind typo.
        obs_b = copy.deepcopy(observation)
        obs_b["provenance"][0]["source_kind"] = "tset"
        corpus_b = tmp_path / "corpus-break-typo"
        _write_corpus(corpus_b, today, topic, obs_b)
        ok_b, msg_b = _try_validate(corpus_b, commit1, repo_root)
        p('  Break B: provenance.source_kind typo\'d ("tset" instead of "test")')
        report("break-typo", corpus_b, commit1, ok_b, msg_b)
        checks_as_expected = checks_as_expected and not ok_b
        p()

        # Break C: one provenance entry's repo_commit disagrees with --repo-commit.
        obs_c = copy.deepcopy(observation)
        obs_c["provenance"][0]["repo_commit"] = "f" * 40
        corpus_c = tmp_path / "corpus-break-commit"
        _write_corpus(corpus_c, today, topic, obs_c)
        ok_c, msg_c = _try_validate(corpus_c, commit1, repo_root)
        p("  Break C: provenance[0].repo_commit points at a different SHA than --repo-commit")
        report("break-commit", corpus_c, commit1, ok_c, msg_c)
        checks_as_expected = checks_as_expected and not ok_c
        p()

        p("[5/5] start the same thing on your own repo:")
        p("      evidence-docs init docs/claims")
        p("      # ... see docs/claims/EXAMPLE.md for a worked topic + observation to copy,")
        p("      #     registering each new topic_id/observation_id in id-registry.yaml first ...")
        p("      evidence-docs validate docs/claims --repo-commit <full-git-sha>")

    if not checks_as_expected:
        print(
            "demo: an expected PASS/FAIL did not happen as designed -- this points at a bug in "
            "the demo itself, not in validate()",
            file=sys.stderr,
        )
        return 1
    return 0
