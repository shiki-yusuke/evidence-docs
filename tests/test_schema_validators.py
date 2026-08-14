from evidence_docs.schema import (
    canonical_json,
    is_full_git_sha,
    is_sha256_hex,
    is_valid_iso8601_utc,
    sha256_hex,
)


def test_is_valid_iso8601_utc_accepts_z_suffix():
    assert is_valid_iso8601_utc("2026-08-09T10:30:00Z") is True


def test_is_valid_iso8601_utc_accepts_explicit_utc_offset():
    assert is_valid_iso8601_utc("2026-08-09T10:30:00+00:00") is True


def test_is_valid_iso8601_utc_rejects_naive_datetime():
    assert is_valid_iso8601_utc("2026-08-09T10:30:00") is False


def test_is_valid_iso8601_utc_rejects_non_utc_offset():
    assert is_valid_iso8601_utc("2026-08-09T10:30:00+09:00") is False


def test_is_valid_iso8601_utc_rejects_garbage_string():
    assert is_valid_iso8601_utc("not-an-iso-date") is False


def test_is_valid_iso8601_utc_rejects_non_string():
    assert is_valid_iso8601_utc(None) is False
    assert is_valid_iso8601_utc(12345) is False


def test_is_sha256_hex_accepts_64_hex_chars():
    assert is_sha256_hex("a" * 64) is True


def test_is_sha256_hex_rejects_wrong_length_or_non_hex():
    assert is_sha256_hex("a" * 63) is False
    assert is_sha256_hex("z" * 64) is False
    assert is_sha256_hex(12345) is False


def test_is_full_git_sha_accepts_40_hex_chars():
    assert is_full_git_sha("f" * 40) is True


def test_is_full_git_sha_rejects_short_or_non_hex():
    assert is_full_git_sha("f" * 39) is False
    assert is_full_git_sha("z" * 40) is False


def test_canonical_json_is_stable_regardless_of_key_order():
    a = canonical_json({"b": 1, "a": 2})
    b = canonical_json({"a": 2, "b": 1})
    assert a == b


def test_sha256_hex_is_deterministic():
    assert sha256_hex("hello") == sha256_hex("hello")
    assert sha256_hex("hello") != sha256_hex("hello2")
