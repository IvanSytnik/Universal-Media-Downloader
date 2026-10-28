"""Our own URL validation, end to end in both locales: each rejection
reason is a keyed ``UnsupportedURLError`` subclass, and
``format_download_error`` renders it from the user's locale. Before this,
the reasons were hardcoded Russian text interpolated into
``error-bad-url``, so an English user read Russian.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from src.domain.exceptions import (
    DomainBlockedError,
    DomainNotAllowedError,
    EmptyURLError,
    MissingURLHostError,
    UnsupportedURLError,
    UnsupportedURLSchemeError,
)
from src.domain.value_objects.url_validation import validate_url_against_allowlist
from src.presentation.telegram.formatting import format_download_error
from tests.conftest import FakeI18n

_ALLOWED = frozenset({"youtube.com", "tiktok.com"})
_BLOCKED = frozenset({"music.youtube.com"})
_CYRILLIC = re.compile("[Ѐ-ӿ]")


def _reject(url: str) -> UnsupportedURLError:
    with pytest.raises(UnsupportedURLError) as info:
        validate_url_against_allowlist(url, _ALLOWED, _BLOCKED)
    return info.value


@pytest.mark.parametrize(
    ("url", "exc_type"),
    [
        ("", EmptyURLError),
        ("   ", EmptyURLError),
        ("youtube.com/watch?v=x", UnsupportedURLSchemeError),
        ("ftp://youtube.com/file", UnsupportedURLSchemeError),
        ("https:///path-without-host", MissingURLHostError),
        ("https://example.org/video", DomainNotAllowedError),
        ("https://music.youtube.com/watch?v=x", DomainBlockedError),
    ],
)
def test_each_reason_has_its_own_exception(url: str, exc_type: type[Exception]) -> None:
    exc = _reject(url)
    assert type(exc) is exc_type
    assert str(exc) == ""  # keyed, not text (bug #6)


_EN = {
    "": "The link is empty.",
    "ftp://youtube.com/file": "Only http:// and https:// links are supported.",
    "https:///path-without-host": "The link has no domain.",
    "https://example.org/video": "This site is not supported. Supported: tiktok.com, youtube.com",
    "https://music.youtube.com/watch?v=x": "This site is not supported",
}


@pytest.mark.parametrize(("url", "expected"), list(_EN.items()))
async def test_english_user_reads_english(i18n_core: Any, url: str, expected: str) -> None:
    assert format_download_error(FakeI18n(i18n_core, "en"), _reject(url)) == expected


@pytest.mark.parametrize("url", list(_EN))
async def test_russian_user_reads_russian(i18n_core: Any, url: str) -> None:
    text = format_download_error(FakeI18n(i18n_core, "ru"), _reject(url))
    assert _CYRILLIC.search(text)


async def test_blocked_subdomain_of_an_allowed_site_does_not_list_sites(i18n_core: Any) -> None:
    # music.youtube.com under an allowed youtube.com: "Supported: youtube.com"
    # would contradict the refusal.
    exc = _reject("https://music.youtube.com/watch?v=x")
    for locale in ("en", "ru"):
        i18n = FakeI18n(i18n_core, locale)
        assert format_download_error(i18n, exc) == i18n.get("error-unsupported-site")


def test_blocked_wins_over_an_empty_allowlist() -> None:
    with pytest.raises(DomainBlockedError):
        validate_url_against_allowlist("https://music.youtube.com/x", frozenset(), _BLOCKED)


async def test_alert_variant_drops_the_list_of_sites(i18n_core: Any) -> None:
    i18n = FakeI18n(i18n_core, "en")
    exc = _reject("https://example.org/video")
    assert format_download_error(i18n, exc, list_supported_sites=False) == i18n.get(
        "error-unsupported-site"
    )


async def test_ytdlp_unsupported_url_is_not_an_empty_reason(i18n_core: Any) -> None:
    # The classifier raises a bare UnsupportedURLError(); /download used to
    # render it as "Invalid link: " with nothing after the colon.
    i18n = FakeI18n(i18n_core, "en")
    assert format_download_error(i18n, UnsupportedURLError()) == "This site is not supported"
