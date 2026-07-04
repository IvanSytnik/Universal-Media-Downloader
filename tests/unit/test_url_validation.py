"""validate_url tests — pure function, no I/O, no mocks needed."""

from __future__ import annotations

import pytest

from src.domain.exceptions import UnsupportedURLError
from src.domain.value_objects.url_validation import validate_url


def test_accepts_valid_https_url() -> None:
    assert validate_url("https://youtube.com/watch?v=abc123") == "https://youtube.com/watch?v=abc123"


def test_accepts_valid_http_url() -> None:
    assert validate_url("http://example.com/video") == "http://example.com/video"


def test_strips_whitespace() -> None:
    assert validate_url("  https://example.com/video  ") == "https://example.com/video"


def test_rejects_empty_string() -> None:
    with pytest.raises(UnsupportedURLError):
        validate_url("")


def test_rejects_whitespace_only() -> None:
    with pytest.raises(UnsupportedURLError):
        validate_url("   ")


def test_rejects_missing_scheme() -> None:
    with pytest.raises(UnsupportedURLError):
        validate_url("youtube.com/watch?v=abc123")


def test_rejects_unsupported_scheme() -> None:
    with pytest.raises(UnsupportedURLError):
        validate_url("ftp://example.com/file")


def test_rejects_missing_host() -> None:
    with pytest.raises(UnsupportedURLError):
        validate_url("https:///path-without-host")
