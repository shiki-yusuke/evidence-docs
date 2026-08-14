"""evidence-docs command-line interface: init / validate / generate / context."""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

from . import __version__
from .bundle import generate as run_generate
from .bundle import resolve_repo_root
from .bundle import validate as run_validate
from .context import QueryError, run_context_query
from .errors import CorpusError
from .init_templates import scaffold


def _cmd_init(args: argparse.Namespace) -> int:
    dir_path = Path(args.dir)
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    created = scaffold(dir_path, today)
    if created:
        print(f"initialized corpus scaffold under {dir_path}:", file=sys.stderr)
        for p in created:
            print(f"  created {p}", file=sys.stderr)
    else:
        print(f"{dir_path} already has a full corpus scaffold; nothing to do", file=sys.stderr)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    corpus_dir = Path(args.dir)
    repo_root = resolve_repo_root(corpus_dir, args.repo_root)
    try:
        result = run_validate(corpus_dir, args.repo_commit, repo_root)
    except CorpusError as e:
        print(f"corpus validation failed: {e}", file=sys.stderr)
        return 1
    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)
    print(
        f"ok: {len(result.corpus.observations)} observations across "
        f"{len(result.corpus.topics)} topics validated",
        file=sys.stderr,
    )
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    corpus_dir = Path(args.dir)
    repo_root = resolve_repo_root(corpus_dir, args.repo_root)
    try:
        result = run_generate(
            corpus_dir,
            args.generated_at,
            args.repo_commit,
            repo_root,
            corpus_title=args.title,
        )
    except CorpusError as e:
        print(f"corpus validation failed: {e}", file=sys.stderr)
        return 1
    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)
    print(
        f"generated {len(result.claims)} observations across {len(result.topics)} topics",
        file=sys.stderr,
    )
    print(f"corpus_digest={result.manifest['corpus_digest']}", file=sys.stderr)
    return 0


def _cmd_context(args: argparse.Namespace) -> int:
    corpus_dir = Path(args.dir)
    bundle_dir = corpus_dir / "bundle"

    query_arg = args.query
    query_path = Path(query_arg)
    if query_path.is_file():
        query_text = query_path.read_text(encoding="utf-8")
    else:
        query_text = query_arg
    try:
        query = json.loads(query_text)
    except json.JSONDecodeError as e:
        # Exit 2 (not 1): this is a malformed --query argument, a usage
        # error, not a corpus/bundle validation failure.
        print(f"--query is not valid JSON (and not an existing file path): {e}", file=sys.stderr)
        return 2

    try:
        result = run_context_query(bundle_dir, query)
    except QueryError as e:
        print(f"--query is invalid: {e}", file=sys.stderr)
        return 2
    except CorpusError as e:
        print(f"context query failed: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evidence-docs", description=__doc__)
    parser.add_argument("--version", action="version", version=f"evidence-docs {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="scaffold a new corpus directory")
    p_init.add_argument("dir", help="corpus directory to create/fill in")
    p_init.set_defaults(func=_cmd_init)

    p_validate = sub.add_parser("validate", help="validate a corpus (no output written)")
    p_validate.add_argument("dir", help="corpus directory")
    p_validate.add_argument("--repo-commit", required=True, help="full 40-char git SHA this corpus is authored against")
    p_validate.add_argument(
        "--repo-root",
        default=None,
        help="path to the git repo provenance uris are relative to; relative paths are "
        "resolved against `dir`. Defaults to `dir` itself.",
    )
    p_validate.set_defaults(func=_cmd_validate)

    p_generate = sub.add_parser("generate", help="validate and deterministically generate site/ + bundle/")
    p_generate.add_argument("dir", help="corpus directory")
    p_generate.add_argument("--generated-at", required=True, help="ISO8601 UTC, e.g. 2026-08-09T10:30:00Z")
    p_generate.add_argument("--repo-commit", required=True, help="full 40-char git SHA this corpus is authored against")
    p_generate.add_argument(
        "--repo-root",
        default=None,
        help="path to the git repo provenance uris are relative to; relative paths are "
        "resolved against `dir`. Defaults to `dir` itself.",
    )
    p_generate.add_argument("--title", default="claim corpus", help="heading used in site/index.md")
    p_generate.set_defaults(func=_cmd_generate)

    p_context = sub.add_parser("context", help="select claims from bundle/ for a query")
    p_context.add_argument("dir", help="corpus directory (must already have bundle/ from `generate`)")
    p_context.add_argument(
        "--query",
        required=True,
        help="JSON query, or a path to a file containing one, e.g. "
        '\'{"seeds": {"paths": ["src/foo.py"]}, "token_budget": 4000}\'',
    )
    p_context.set_defaults(func=_cmd_context)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
