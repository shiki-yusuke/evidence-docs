"""Deterministic capture of `validate` / `generate` CLI behavior over every
corpus path that ships with this repo (the mini-domain fixture, the `init`
scaffold, and the corpus `demo` builds), for the pre-F1 golden in
tests/golden/pre-f1.json.

Run `python tests/golden_harness.py` to (re)write the golden. It was
recorded on main before the explanations namespace existed; test_explain.py
re-runs the same capture and compares.

Git author/committer dates and `today` are pinned so commit SHAs (and thus
every output that embeds them) are reproducible across runs and machines.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

REPO_DIR = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_DIR / "fixtures" / "mini-domain"
GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "pre-f1.json"

GENERATED_AT = "2026-08-09T10:30:00Z"
TODAY = "2026-08-09"
PINNED_GIT_ENV = {
    "GIT_AUTHOR_NAME": "evidence-docs golden",
    "GIT_AUTHOR_EMAIL": "golden@example.invalid",
    "GIT_COMMITTER_NAME": "evidence-docs golden",
    "GIT_COMMITTER_EMAIL": "golden@example.invalid",
    "GIT_AUTHOR_DATE": "2026-08-09T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-08-09T00:00:00+00:00",
}
SCAFFOLD_COMMIT = "0" * 40


def _git(args: list[str], cwd: Path) -> str:
    env = dict(os.environ)
    env.update(PINNED_GIT_ENV)
    return subprocess.run(
        ["git", *args], cwd=str(cwd), env=env, capture_output=True, text=True, check=True
    ).stdout.strip()


def build_mini_domain(tmp: Path) -> tuple[Path, Path, str]:
    repo_root = tmp / "repo"
    shutil.copytree(FIXTURES_DIR / "repo", repo_root)
    _git(["init", "-q", "-b", "main"], repo_root)
    _git(["add", "-A"], repo_root)
    _git(["-c", "commit.gpgsign=false", "commit", "-q", "-m", "mini-domain fixture snapshot"], repo_root)
    commit = _git(["rev-parse", "HEAD"], repo_root)
    digests = {
        f.relative_to(repo_root).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in repo_root.rglob("*")
        if f.is_file() and ".git" not in f.parts
    }
    corpus_dir = tmp / "corpus"
    shutil.copytree(FIXTURES_DIR / "corpus", corpus_dir)
    for f in corpus_dir.rglob("*"):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8")
        text = text.replace("__REPO_COMMIT__", commit)
        for rel, digest in digests.items():
            text = text.replace(f"__DIGEST:{rel}__", digest)
        f.write_text(text, encoding="utf-8")
    return corpus_dir, repo_root, commit


def build_scaffold(tmp: Path) -> tuple[Path, Path, str]:
    from evidence_docs.init_templates import scaffold

    corpus_dir = tmp / "scaffold"
    scaffold(corpus_dir, TODAY)
    return corpus_dir, corpus_dir, SCAFFOLD_COMMIT


class _FixedDatetime(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 8, 9, tzinfo=tz)


def build_demo(tmp: Path) -> tuple[Path, Path, str]:
    """Run the real `demo` and copy out the first (passing) corpus it builds."""

    from evidence_docs import demo

    captured: dict = {}
    real_validate = demo.run_validate

    def spy(corpus_dir: Path, repo_commit: str, repo_root: Path):
        if not captured:
            shutil.copytree(repo_root, tmp / "demo-repo", symlinks=True)
            shutil.copytree(corpus_dir, tmp / "demo-corpus", symlinks=True)
            captured["commit"] = repo_commit
        return real_validate(corpus_dir, repo_commit, repo_root)

    fake_dt_module = mock.Mock(wraps=_dt)
    fake_dt_module.datetime = _FixedDatetime
    fake_dt_module.timezone = _dt.timezone
    with mock.patch.dict(os.environ, PINNED_GIT_ENV), mock.patch.object(
        demo, "run_validate", spy
    ), mock.patch.object(demo, "datetime", fake_dt_module):
        demo.run_demo(out=io.StringIO())
    corpus_dir = tmp / "demo-corpus"
    # The corpus sits next to its repo inside the demo's tempdir; keep that
    # relative layout so --repo-root resolves the same way.
    return corpus_dir, tmp / "demo-repo", captured["commit"]


def _run_cli(argv: list[str]) -> dict:
    from evidence_docs.cli import main

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return {"exit": code, "stdout": out.getvalue(), "stderr": err.getvalue()}


def _output_digests(corpus_dir: Path) -> dict:
    files = sorted((corpus_dir / "bundle").glob("*.jsonl")) + sorted(
        p for p in (corpus_dir / "site").rglob("*") if p.is_file()
    )
    return {
        p.relative_to(corpus_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
    }


def capture_one(corpus_dir: Path, repo_root: Path, commit: str) -> dict:
    common = ["--repo-commit", commit, "--repo-root", str(repo_root)]
    validate = _run_cli(["validate", str(corpus_dir), *common])
    generate = _run_cli(["generate", str(corpus_dir), "--generated-at", GENERATED_AT, *common])
    return {"validate": validate, "generate": generate, "outputs": _output_digests(corpus_dir)}


BUILDERS = {"mini-domain": build_mini_domain, "init-scaffold": build_scaffold, "demo": build_demo}


def capture_all(prepare=None) -> dict:
    """Build every corpus fresh and capture its CLI behavior. `prepare`, if
    given, is called with each corpus_dir before validate/generate run (used
    to show an unrelated explanations/ directory changes nothing)."""

    results = {}
    for name, build in BUILDERS.items():
        with tempfile.TemporaryDirectory(prefix="evidence-docs-golden-") as t:
            corpus_dir, repo_root, commit = build(Path(t).resolve())
            if prepare is not None:
                prepare(name, corpus_dir, repo_root, commit)
            results[name] = capture_one(corpus_dir, repo_root, commit)
    return results


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_DIR))
    GOLDEN_PATH.parent.mkdir(exist_ok=True)
    GOLDEN_PATH.write_text(json.dumps(capture_all(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(GOLDEN_PATH)
