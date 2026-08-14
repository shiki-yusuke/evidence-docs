"""update_readme_counts_table() marker-pair extraction: the adversarial cases
from the pilot's review history (0 marker pairs, 2 marker pairs, markers
appearing mid-line, markers missing entirely)."""

from __future__ import annotations

import pytest

from evidence_docs.errors import CorpusError
from evidence_docs.render_md import (
    README_COUNTS_TABLE_END,
    README_COUNTS_TABLE_START,
    update_readme_counts_table,
)

CLAIMS = [
    {"origin": "reconstructed", "epistemic_status": "execution_verified", "claim_kind": "behavior", "conformance_status": "matched"}
]


def test_missing_both_markers_is_rejected(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("# title\n\nno markers here at all\n", encoding="utf-8")
    with pytest.raises(CorpusError, match="missing the COUNTS_TABLE markers"):
        update_readme_counts_table(readme, CLAIMS)


def test_missing_end_marker_only_is_rejected(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(f"# title\n\n{README_COUNTS_TABLE_START}\nold table\n", encoding="utf-8")
    with pytest.raises(CorpusError, match="missing the COUNTS_TABLE markers"):
        update_readme_counts_table(readme, CLAIMS)


def test_single_marker_pair_is_replaced(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(
        f"# title\n\n{README_COUNTS_TABLE_START}\nold table\n{README_COUNTS_TABLE_END}\n\nfooter\n",
        encoding="utf-8",
    )
    update_readme_counts_table(readme, CLAIMS)
    text = readme.read_text(encoding="utf-8")
    assert "old table" not in text
    assert "reconstructed 1" in text
    assert text.startswith("# title")
    assert text.rstrip().endswith("footer")


def test_two_marker_pairs_only_the_first_pair_is_touched(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(
        f"{README_COUNTS_TABLE_START}\nfirst old\n{README_COUNTS_TABLE_END}\n\n"
        f"{README_COUNTS_TABLE_START}\nsecond old\n{README_COUNTS_TABLE_END}\n",
        encoding="utf-8",
    )
    update_readme_counts_table(readme, CLAIMS)
    text = readme.read_text(encoding="utf-8")
    assert "first old" not in text
    assert "second old" in text  # second pair is untouched
    assert "reconstructed 1" in text


def test_markers_mid_line_still_match(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(
        f"before-text {README_COUNTS_TABLE_START} old {README_COUNTS_TABLE_END} after-text\n",
        encoding="utf-8",
    )
    update_readme_counts_table(readme, CLAIMS)
    text = readme.read_text(encoding="utf-8")
    assert text.startswith("before-text")
    assert text.rstrip().endswith("after-text")
    assert "reconstructed 1" in text


def test_end_before_start_is_rejected(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(f"{README_COUNTS_TABLE_END}\n...\n{README_COUNTS_TABLE_START}\n", encoding="utf-8")
    with pytest.raises(CorpusError, match="out of order"):
        update_readme_counts_table(readme, CLAIMS)


def test_empty_claims_list_produces_blank_breakdown_cells(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(f"{README_COUNTS_TABLE_START}\nx\n{README_COUNTS_TABLE_END}\n", encoding="utf-8")
    update_readme_counts_table(readme, [])
    text = readme.read_text(encoding="utf-8")
    assert "| origin |  |" in text
