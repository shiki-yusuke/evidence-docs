"""`evidence-docs demo`: builds a throwaway example corpus, shows a real PASS,
then breaks a copy of it three ways and shows each real FAIL.

These tests deliberately avoid asserting on exact output strings (the wording
is free to change); they check the PASS/FAIL *shape* the demo promises, and
that it cleans up after itself and never touches the caller's cwd.
"""

from __future__ import annotations

import re
from pathlib import Path

from evidence_docs.cli import main


def test_demo_exits_zero_with_no_arguments(capsys):
    rc = main(["demo"])
    assert rc == 0
    capsys.readouterr()


def test_demo_shows_one_pass_and_three_fails(capsys):
    rc = main(["demo"])
    out = capsys.readouterr().out
    assert rc == 0

    statuses = re.findall(r"->\s+(PASS|FAIL)", out)
    assert statuses.count("PASS") == 1
    assert statuses.count("FAIL") == 3

    # Each break must fail for a distinct, recognizable reason -- not just
    # "FAIL" with no explanation (that would be exactly the "0 observations,
    # ok" problem this command exists to avoid).
    assert "content_digest mismatch" in out
    assert "unknown source_kind" in out
    assert "does not match" in out


def test_demo_narrates_the_first_observation(capsys):
    main(["demo"])
    out = capsys.readouterr().out
    assert "OBS-001" in out
    assert "greet(" in out


def test_demo_points_to_getting_started_on_a_real_repo(capsys):
    main(["demo"])
    out = capsys.readouterr().out
    assert "evidence-docs init" in out
    assert "evidence-docs validate" in out


def test_demo_cleans_up_its_temp_directories(capsys):
    main(["demo"])
    out = capsys.readouterr().out

    repo_match = re.search(r"repo path:\s+(\S+)", out)
    assert repo_match, "expected the demo to print the throwaway repo path"
    repo_path = Path(repo_match.group(1))

    # The parent (evidence-docs-demo-<random>/) is the TemporaryDirectory;
    # once run_demo() returns, it must be gone entirely.
    demo_tmp_dir = repo_path.parent

    # Once run_demo() returns, the whole TemporaryDirectory must be gone.
    assert not demo_tmp_dir.exists(), f"{demo_tmp_dir} should have been cleaned up"


def test_demo_does_not_write_into_the_current_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.iterdir())

    rc = main(["demo"])

    assert rc == 0
    capsys.readouterr()
    after = set(tmp_path.iterdir())
    assert before == after
