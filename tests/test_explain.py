"""F1: the explanations namespace (authority: none) -- deterministic
generation, full-reconstruction validation, stale detection, the
authoritative-record -> explanation reference ban, and isolation from
bundle/ + site/ + context."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import golden_harness
import pytest
import yaml

from evidence_docs.cli import main
from evidence_docs.context import run_context_query
from evidence_docs.explain import compute_scope_digest

GENERATED_AT = "2026-08-09T10:30:00Z"
ALL_OBS = [f"OBS-00{i}" for i in range(1, 9)]


def make_scope(commit: str, paths: list[str], layers: list[str] | None = None, **overrides) -> dict:
    layers = ["core"] if layers is None else layers
    scope = {
        "scan_version": "impact-scan/1",
        "repo_commit": commit,
        "digest": compute_scope_digest(paths, layers),
        "candidate_paths": paths,
        "candidate_layers": layers,
    }
    scope.update(overrides)
    return scope


def write_scope(tmp_path: Path, scope, raw: str | None = None) -> Path:
    path = tmp_path / "scope.json"
    path.write_text(raw if raw is not None else json.dumps(scope), encoding="utf-8")
    return path


def run(capsys, argv: list[str]) -> tuple[int, str, str]:
    code = main(argv)
    out, err = capsys.readouterr()
    return code, out, err


def explain_cmd(md, scope_file: Path, generated_at: str = GENERATED_AT) -> list[str]:
    return [
        "explain", str(md.corpus_dir), "--scope-file", str(scope_file),
        "--repo-commit", md.repo_commit, "--generated-at", generated_at, "--repo-root", str(md.repo_root),
    ]


def validate_cmd(md) -> list[str]:
    return ["validate", str(md.corpus_dir), "--repo-commit", md.repo_commit, "--repo-root", str(md.repo_root)]


def generate_cmd(md) -> list[str]:
    return [
        "generate", str(md.corpus_dir), "--generated-at", GENERATED_AT,
        "--repo-commit", md.repo_commit, "--repo-root", str(md.repo_root),
    ]


@pytest.fixture
def explained(mini_domain, tmp_path, capsys):
    """mini-domain with one explanation written for src/task_store.py + src/nope.py."""

    scope = make_scope(mini_domain.repo_commit, ["src/task_store.py", "src/nope.py"])
    code, out, _ = run(capsys, explain_cmd(mini_domain, write_scope(tmp_path, scope)))
    assert code == 0
    return mini_domain, Path(out.strip()), scope


def assert_validate_fails(capsys, md, needle: str) -> str:
    code, _, err = run(capsys, validate_cmd(md))
    assert code == 1, err
    assert needle in err, err
    return err


def rewrite_json(path: Path, mutate) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def edit_yaml(path: Path, mutate) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


# --- golden: existing CLI behavior is unchanged ------------------------------


def test_golden_pre_f1_unchanged_without_explanations():
    golden = json.loads(golden_harness.GOLDEN_PATH.read_text(encoding="utf-8"))
    assert golden_harness.capture_all() == golden


def test_golden_pre_f1_unchanged_with_explanations_present():
    """Isolation (rule 5) over every corpus path in the repo: adding a valid
    explanation changes neither validate/generate output nor bundle/site."""

    def add_explanation(name, corpus_dir, repo_root, commit):
        scope = make_scope(commit, ["src/greeter.py", "src/task_store.py", "README.md"])
        scope_file = corpus_dir.parent / f"{name}-scope.json"
        scope_file.write_text(json.dumps(scope), encoding="utf-8")
        result = golden_harness._run_cli([
            "explain", str(corpus_dir), "--scope-file", str(scope_file), "--repo-commit", commit,
            "--generated-at", GENERATED_AT, "--repo-root", str(repo_root),
        ])
        assert result["exit"] == 0, result
        assert len(list((corpus_dir / "explanations").iterdir())) == 1

    golden = json.loads(golden_harness.GOLDEN_PATH.read_text(encoding="utf-8"))
    assert golden_harness.capture_all(prepare=add_explanation) == golden


# --- generation ---------------------------------------------------------------


def test_explain_selects_exact_path_matches(explained):
    _, path, scope = explained
    data = json.loads(path.read_text(encoding="utf-8"))
    ids = [s["observation_id"] for s in data["sources"]]
    # Every mini-domain observation cites src/task_store.py (affected_paths
    # or a repo-internal provenance uri), including OBS-004/005/008.
    assert ids == ALL_OBS
    assert {"OBS-004", "OBS-005", "OBS-008"} <= set(ids)
    assert data["body"]["covered_paths"] == {"src/task_store.py": ALL_OBS}
    assert data["body"]["uncovered_paths"] == ["src/nope.py"]
    assert data["authority"] == "none"
    assert data["scope"] == {"kind": "impact-scan:v1", "snapshot": scope}
    assert data["commit_mismatch"] is False
    assert "WARNING" not in data["body"]["text"]
    assert path.name == f"{data['explanation_id']}.json"
    assert data["body"]["text"].splitlines()[0] == f"# Explanation (authority: none) — impact-scan:v1 {scope['digest']}"


def test_explain_stdout_stderr_and_rerun_is_unchanged(explained, tmp_path, capsys):
    md, path, scope = explained
    before = path.read_bytes()
    code, out, err = run(capsys, explain_cmd(md, write_scope(tmp_path, scope)))
    assert (code, out, err) == (0, f"{path}\n", "unchanged\n")
    assert path.read_bytes() == before
    assert run(capsys, validate_cmd(md))[0] == 0


def test_explain_is_byte_identical_across_runs(explained, tmp_path, capsys):
    md, path, scope = explained
    first = path.read_bytes()
    shutil.rmtree(md.corpus_dir / "explanations")
    code, _, err = run(capsys, explain_cmd(md, write_scope(tmp_path, scope)))
    assert (code, err) == (0, "created\n")
    assert path.read_bytes() == first


def test_generated_at_changes_only_generated_at(explained, tmp_path, capsys):
    md, path, scope = explained
    first = json.loads(path.read_text(encoding="utf-8"))
    code, out, err = run(capsys, explain_cmd(md, write_scope(tmp_path, scope), "2026-09-01T00:00:00Z"))
    assert (code, out.strip(), err) == (0, str(path), "regenerated\n")
    second = json.loads(path.read_text(encoding="utf-8"))
    assert second["explanation_id"] == first["explanation_id"]
    assert second["generated_at"] == "2026-09-01T00:00:00Z"
    first.pop("generated_at")
    second.pop("generated_at")
    assert first == second
    assert run(capsys, validate_cmd(md))[0] == 0


def test_commit_mismatch_is_recorded_not_rejected(mini_domain, tmp_path, capsys):
    other = "f" * 40
    scope = make_scope(other, ["src/task_store.py"])
    code, out, _ = run(capsys, explain_cmd(mini_domain, write_scope(tmp_path, scope)))
    assert code == 0
    data = json.loads(Path(out.strip()).read_text(encoding="utf-8"))
    assert data["commit_mismatch"] is True
    assert data["body"]["text"].splitlines()[2] == (
        f"WARNING: scope repo_commit {other} differs from corpus_commit; claims describe the corpus commit."
    )
    assert run(capsys, validate_cmd(mini_domain))[0] == 0


def test_no_prefix_glob_or_external_uri_matching(mini_domain, tmp_path, capsys):
    paths = ["src/task_store", "src/*.py", "external-review-notes.jsonl#L118"]
    code, out, _ = run(capsys, explain_cmd(mini_domain, write_scope(tmp_path, make_scope(mini_domain.repo_commit, paths))))
    assert code == 0
    data = json.loads(Path(out.strip()).read_text(encoding="utf-8"))
    assert data["sources"] == []
    assert data["body"]["covered_paths"] == {}
    assert data["body"]["uncovered_paths"] == paths


# --- stale + full reconstruction -------------------------------------------------


def _change_obs004_statement(md) -> None:
    def mutate(doc):
        doc["observations"][0]["statement"] = "TaskStore.save() changed statement."

    edit_yaml(md.corpus_dir / "observations" / "T-02-task-store-save-contract.yaml", mutate)


def test_stale_after_corpus_change_then_regenerate_overwrites(explained, tmp_path, capsys):
    md, path, scope = explained
    _change_obs004_statement(md)
    assert_validate_fails(capsys, md, "stale explanation")
    # generate goes through the same validate and refuses too.
    assert run(capsys, generate_cmd(md))[0] == 1
    # explain only checks the authoritative records, so it can regenerate.
    code, out, err = run(capsys, explain_cmd(md, write_scope(tmp_path, scope)))
    assert (code, out.strip(), err) == (0, str(path), "regenerated\n")
    assert len(list((md.corpus_dir / "explanations").iterdir())) == 1
    assert run(capsys, validate_cmd(md))[0] == 0


def test_hand_edited_body_text_is_rejected(explained, capsys):
    md, path, _ = explained
    rewrite_json(path, lambda d: d["body"].__setitem__("text", d["body"]["text"].replace("#", "*", 1)))
    err = assert_validate_fails(capsys, md, "does not match the generator output")
    assert "edited by hand" in err and "first difference at body.text" in err


def test_authority_other_than_none_is_rejected(explained, capsys):
    md, path, _ = explained
    rewrite_json(path, lambda d: d.__setitem__("authority", "full"))
    assert_validate_fails(capsys, md, "first difference at authority")


def test_dropped_source_is_stale(explained, capsys):
    md, path, _ = explained
    rewrite_json(path, lambda d: d["sources"].pop())
    assert_validate_fails(capsys, md, "stale explanation")


def test_generator_version_edit_is_rejected(explained, capsys):
    md, path, _ = explained
    rewrite_json(path, lambda d: d["generator"].__setitem__("version", "9.9.9"))
    assert_validate_fails(capsys, md, "first difference at generator.version")


def test_explanation_id_field_mismatch_is_rejected(explained, capsys):
    md, path, _ = explained
    rewrite_json(path, lambda d: d.__setitem__("explanation_id", "EXP-0000000000000000"))
    assert_validate_fails(capsys, md, f"does not match its scope (expected {path.stem}.json)")


def test_valid_content_copied_under_another_name_is_rejected(explained, capsys):
    md, path, _ = explained
    shutil.copy(path, path.with_name("EXP-0123456789abcdef.json"))
    assert_validate_fails(capsys, md, "explanation file EXP-0123456789abcdef.json does not match its scope")


def test_candidate_paths_edited_with_stale_digest_is_rejected(explained, capsys):
    md, path, _ = explained
    rewrite_json(path, lambda d: d["scope"]["snapshot"]["candidate_paths"].append("src/extra.py"))
    assert_validate_fails(capsys, md, "scope digest mismatch")


# --- explanations/ directory shape (rule 1) ---------------------------------------


def _write_bad_entry(exp_dir: Path, valid: Path, kind: str) -> None:
    if kind == "subdir":
        (exp_dir / "nested").mkdir()
    elif kind == "txt":
        (exp_dir / "notes.txt").write_text("x", encoding="utf-8")
    elif kind == "bad_name":
        shutil.copy(valid, exp_dir / "explanation.json")
    elif kind == "symlink":
        os.symlink(valid, exp_dir / "EXP-0123456789abcdef.json")
    else:
        target = exp_dir / "EXP-0123456789abcdef.json"
        payload = json.loads(valid.read_text(encoding="utf-8"))
        if kind == "invalid_json":
            target.write_text("{not json", encoding="utf-8")
            return
        if kind == "array":
            payload = [payload]
        elif kind == "missing_key":
            payload.pop("body")
        elif kind == "unknown_key":
            payload["content_digest"] = "0" * 64
        target.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.parametrize(
    "kind, needle",
    [
        ("subdir", "may only contain regular files"),
        ("txt", "must match EXP-<16 hex>.json"),
        ("bad_name", "must match EXP-<16 hex>.json"),
        ("symlink", "may only contain regular files"),
        ("invalid_json", "is not valid JSON"),
        ("array", "top level must be a JSON object"),
        ("missing_key", "top-level keys missing ['body']"),
        ("unknown_key", "unknown ['content_digest']"),
    ],
)
def test_malformed_explanations_entries_are_rejected(explained, capsys, kind, needle):
    md, path, _ = explained
    _write_bad_entry(path.parent, path, kind)
    assert_validate_fails(capsys, md, needle)


def test_symlinked_explanations_dir_is_rejected_by_validate(mini_domain, tmp_path, capsys):
    (tmp_path / "elsewhere").mkdir()
    os.symlink(tmp_path / "elsewhere", mini_domain.corpus_dir / "explanations")
    assert_validate_fails(capsys, mini_domain, "must not be a symlink")


def test_explain_refuses_symlinked_explanations_dir(mini_domain, tmp_path, capsys):
    inside = mini_domain.corpus_dir / "inside"
    inside.mkdir()
    os.symlink(inside, mini_domain.corpus_dir / "explanations")
    scope = make_scope(mini_domain.repo_commit, ["src/task_store.py"])
    code, out, err = run(capsys, explain_cmd(mini_domain, write_scope(tmp_path, scope)))
    assert (code, out) == (1, "")
    assert "must not be a symlink" in err
    assert list(inside.iterdir()) == []


def test_explain_refuses_symlinked_target_file(explained, tmp_path, capsys):
    md, path, scope = explained
    real = md.corpus_dir / "real.json"
    path.rename(real)
    os.symlink(real, path)
    before = real.read_bytes()
    code, out, err = run(capsys, explain_cmd(md, write_scope(tmp_path, scope), "2026-09-01T00:00:00Z"))
    assert (code, out) == (1, "")
    assert "must not be a symlink" in err
    assert real.read_bytes() == before


# --- rule 4: authoritative records never reference an explanation -------------------


def test_observation_referencing_explanation_id_is_rejected(mini_domain, capsys):
    def mutate(doc):
        doc["observations"][0]["supporting_refs"] = ["EXP-0123456789abcdef"]

    edit_yaml(mini_domain.corpus_dir / "observations" / "T-02-task-store-save-contract.yaml", mutate)
    assert not (mini_domain.corpus_dir / "explanations").exists()
    assert_validate_fails(capsys, mini_domain, "observations/T-02-task-store-save-contract.yaml:")


def test_topic_mentioning_explanations_dir_is_rejected(mini_domain, capsys):
    edit_yaml(
        mini_domain.corpus_dir / "topics" / "T-01-scope-id-derivation.yaml",
        lambda t: t.__setitem__("description", "see explanations/EXP-x.json"),
    )
    assert_validate_fails(capsys, mini_domain, "topics/T-01-scope-id-derivation.yaml:")


def test_gaps_evidence_ref_pointing_at_explanations_is_rejected(mini_domain, capsys):
    def mutate(doc):
        doc["gaps"][0]["evidence_ref"] = "explanations/EXP-0123456789abcdef.json"

    edit_yaml(mini_domain.corpus_dir / "gaps.yaml", mutate)
    err = assert_validate_fails(capsys, mini_domain, "gaps.yaml:")
    assert "references an explanation (raw text)" in err


def test_id_registry_key_naming_an_explanation_is_rejected(mini_domain, capsys):
    def mutate(doc):
        doc["topics"]["T-01"]["slug"] = "EXP-0123456789abcdef"

    edit_yaml(mini_domain.corpus_dir / "id-registry.yaml", mutate)
    assert_validate_fails(capsys, mini_domain, "id-registry.yaml:")


def test_observation_file_wrapper_key_referencing_explanation_is_rejected(mini_domain, capsys):
    # A top-level key the loader never copies into a record (outside `observations:`).
    def mutate(doc):
        doc["see_also"] = "explanations/"

    edit_yaml(mini_domain.corpus_dir / "observations" / "T-02-task-store-save-contract.yaml", mutate)
    assert_validate_fails(capsys, mini_domain, "observations/T-02-task-store-save-contract.yaml:")


def test_yaml_comment_mentioning_explanations_is_rejected(mini_domain, capsys):
    f = mini_domain.corpus_dir / "topics" / "T-01-scope-id-derivation.yaml"
    f.write_text("# moved to explanations/\n" + f.read_text(encoding="utf-8"), encoding="utf-8")
    assert_validate_fails(capsys, mini_domain, "topics/T-01-scope-id-derivation.yaml:1")


def test_explain_also_refuses_a_corpus_that_references_explanations(mini_domain, tmp_path, capsys):
    edit_yaml(
        mini_domain.corpus_dir / "topics" / "T-01-scope-id-derivation.yaml",
        lambda t: t.__setitem__("description", "see explanations/"),
    )
    scope = make_scope(mini_domain.repo_commit, ["src/task_store.py"])
    code, _, err = run(capsys, explain_cmd(mini_domain, write_scope(tmp_path, scope)))
    assert code == 1 and "references an explanation" in err
    assert not (mini_domain.corpus_dir / "explanations").exists()


# --- isolation (rule 5) on mini-domain, incl. context ------------------------------------


def _bundle_and_site_digests(corpus_dir: Path) -> dict:
    files = [p for d in ("bundle", "site") for p in sorted((corpus_dir / d).rglob("*")) if p.is_file()]
    return {p.relative_to(corpus_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def test_generate_and_context_unchanged_by_explanations(mini_domain, tmp_path, capsys):
    query = {"seeds": {"paths": ["src/task_store.py"]}, "token_budget": 4000}
    assert run(capsys, generate_cmd(mini_domain))[0] == 0
    without = _bundle_and_site_digests(mini_domain.corpus_dir)
    context_without = run_context_query(mini_domain.corpus_dir / "bundle", query)

    scope = make_scope(mini_domain.repo_commit, ["src/task_store.py"])
    assert run(capsys, explain_cmd(mini_domain, write_scope(tmp_path, scope)))[0] == 0
    assert run(capsys, generate_cmd(mini_domain))[0] == 0
    assert _bundle_and_site_digests(mini_domain.corpus_dir) == without
    assert run_context_query(mini_domain.corpus_dir / "bundle", query) == context_without
    assert not any("EXP-" in p for p in without)


# --- scope input validation ----------------------------------------------------------


def _bad_scopes(commit: str) -> dict:
    good = make_scope(commit, ["src/task_store.py"])
    missing = dict(good)
    missing.pop("candidate_layers")
    return {
        "missing_key": (missing, None, "missing keys"),
        "unknown_key": ({**good, "extra": 1}, None, "unknown keys"),
        "invalid_json": (None, "{nope", "cannot read scope JSON"),
        "top_level_array": (None, json.dumps([good]), "must be a JSON object"),
        "repo_commit_39": ({**good, "repo_commit": commit[:39]}, None, "repo_commit must be"),
        "digest_mismatch": ({**good, "digest": "0" * 64}, None, "scope digest mismatch"),
        "duplicate_path": (make_scope(commit, ["a.py", "a.py"]), None, "contains duplicates"),
        "dotdot_path": (make_scope(commit, ["src/../a.py"]), None, "not a POSIX relative path"),
        "absolute_path": (make_scope(commit, ["/src/a.py"]), None, "not a POSIX relative path"),
        "non_str_layer": (make_scope(commit, ["a.py"], ["core", 1]), None, "candidate_layers must be"),
    }


@pytest.mark.parametrize(
    "case",
    ["missing_key", "unknown_key", "invalid_json", "top_level_array", "repo_commit_39", "digest_mismatch",
     "duplicate_path", "dotdot_path", "absolute_path", "non_str_layer"],
)
def test_bad_scope_file_is_rejected_and_writes_nothing(mini_domain, tmp_path, capsys, case):
    scope, raw, needle = _bad_scopes(mini_domain.repo_commit)[case]
    code, out, err = run(capsys, explain_cmd(mini_domain, write_scope(tmp_path, scope, raw)))
    assert (code, out) == (1, "")
    assert needle in err, err
    assert not (mini_domain.corpus_dir / "explanations").exists()


def test_scope_digest_matches_lane_algorithm():
    # JSON.stringify({candidate_paths, candidate_layers}) with no spaces,
    # keys in that order, non-ASCII left as-is.
    paths, layers = ["src/ü.py", "a"], ["core"]
    expected = hashlib.sha256('{"candidate_paths":["src/ü.py","a"],"candidate_layers":["core"]}'.encode()).hexdigest()
    assert compute_scope_digest(paths, layers) == expected
