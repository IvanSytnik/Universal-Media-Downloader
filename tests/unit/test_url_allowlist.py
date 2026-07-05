"""validate_url_against_allowlist — pure function, no I/O."""

from __future__ import annotations

import pytest

from src.domain.exceptions import UnsupportedURLError
from src.domain.value_objects.url_validation import validate_url_against_allowlist

_DOMAINS = frozenset({"youtube.com", "youtu.be", "tiktok.com"})


def test_accepts_exact_domain() -> None:
    url = "https://youtube.com/watch?v=abc"
    assert validate_url_against_allowlist(url, _DOMAINS) == url


def test_accepts_subdomain() -> None:
    url = "https://www.youtube.com/watch?v=abc"
    assert validate_url_against_allowlist(url, _DOMAINS) == url


def test_accepts_mobile_subdomain() -> None:
    url = "https://m.youtube.com/watch?v=abc"
    assert validate_url_against_allowlist(url, _DOMAINS) == url


def test_rejects_lookalike_domain() -> None:
    # A naive endswith("youtube.com") would let this through.
    with pytest.raises(UnsupportedURLError):
        validate_url_against_allowlist("https://evilyoutube.com/watch", _DOMAINS)


def test_rejects_unlisted_domain() -> None:
    with pytest.raises(UnsupportedURLError):
        validate_url_against_allowlist("https://example.com/video", _DOMAINS)


def test_rejects_structurally_invalid_url() -> None:
    with pytest.raises(UnsupportedURLError):
        validate_url_against_allowlist("not-a-url", _DOMAINS)


def test_case_insensitive_hostname() -> None:
    url = "https://WWW.YouTube.COM/watch?v=abc"
    assert validate_url_against_allowlist(url, _DOMAINS) == url


def test_trailing_dot_hostname_matches() -> None:
    url = "https://youtube.com./watch?v=abc"
    assert validate_url_against_allowlist(url, _DOMAINS) == url


def test_empty_allowlist_allows_everything() -> None:
    url = "https://any-random-site.example/video"
    assert validate_url_against_allowlist(url, frozenset()) == url


def test_rejects_domain_as_path_component() -> None:
    # The allowed domain appearing in the PATH must not count.
    with pytest.raises(UnsupportedURLError):
        validate_url_against_allowlist("https://evil.com/youtube.com/x", _DOMAINS)
