"""Tests for the yt-dlp error classifier (Day 10).

The corpus below is real-world yt-dlp error wording (from YouTube,
Instagram, TikTok extractors). Classification is the load-bearing piece
of Day 10 — a wrong category shows the user a wrong (and sometimes
misleading) message — so this covers each category with multiple phrasings
plus the ambiguous "Unsupported URL" split that needs the URL to resolve.
"""

from __future__ import annotations

import pytest

from src.domain.exceptions import (
    AgeRestrictedError,
    ContentUnavailableError,
    ExtractionError,
    GeoRestrictedError,
    PrivateContentError,
    UnsupportedMediaError,
    UnsupportedURLError,
)
from src.infrastructure.downloader.error_classifier import classify_error

_PRIVATE = [
    "ERROR: [instagram] xyz: Requested content is not available, "
    "rate-limit reached or login required",
    "ERROR: This video is only available to Music Premium members",
    "ERROR: [instagram] This account is private",
    "ERROR: Private video. Sign in if you have been granted access to this video",
    "ERROR: You need to log in to access this content",
]

_AGE = [
    "ERROR: [youtube] xyz: Sign in to confirm your age. "
    "This video may be inappropriate for some users",
    "ERROR: Age-restricted video. Use --cookies",
    "ERROR: Please confirm your age to watch this video",
]

_GEO = [
    "ERROR: [youtube] xyz: The uploader has not made this video available in your country",
    "ERROR: Video geo-restricted. This video is not available from your location.",
    "ERROR: The uploader who has blocked it in your country",
]

_UNAVAILABLE = [
    "ERROR: [youtube] xyz: Video unavailable. This video has been removed by the uploader",
    "ERROR: [youtube] xyz: This video is no longer available because the YouTube "
    "account associated with this video has been terminated",
    "ERROR: [generic] HTTP Error 404: Not Found",
    "ERROR: This content isn't available anymore",
]

_UNSUPPORTED_MEDIA_MSG = [
    "ERROR: [TikTok] 123: No video formats found!",
    "ERROR: There's no video in this post",
    "ERROR: Unable to extract video url",
]

_FALLBACK = [
    "ERROR: Unable to download webpage: The read operation timed out",
    "ERROR: [youtube] xyz: Some brand new error we have never seen",
    "ERROR: fragment 3 not found, unable to continue",
]


@pytest.mark.parametrize("msg", _PRIVATE)
def test_private(msg: str) -> None:
    assert classify_error(msg, "http://x") is PrivateContentError


@pytest.mark.parametrize("msg", _AGE)
def test_age(msg: str) -> None:
    assert classify_error(msg, "http://x") is AgeRestrictedError


@pytest.mark.parametrize("msg", _GEO)
def test_geo(msg: str) -> None:
    assert classify_error(msg, "http://x") is GeoRestrictedError


@pytest.mark.parametrize("msg", _UNAVAILABLE)
def test_unavailable(msg: str) -> None:
    assert classify_error(msg, "http://x") is ContentUnavailableError


@pytest.mark.parametrize("msg", _UNSUPPORTED_MEDIA_MSG)
def test_unsupported_media_by_message(msg: str) -> None:
    assert classify_error(msg, "http://x") is UnsupportedMediaError


@pytest.mark.parametrize("msg", _FALLBACK)
def test_fallback_to_generic(msg: str) -> None:
    assert classify_error(msg, "http://x") is ExtractionError


def test_unsupported_url_photo_is_media_not_site() -> None:
    # The real Day 10 case: a TikTok photo/slideshow post. Bare
    # "Unsupported URL", but the /photo/ path means the SITE is supported,
    # just not this media type.
    msg = "ERROR: Unsupported URL: https://www.tiktok.com/@psy.aware/photo/7658292468219186453"
    url = "https://www.tiktok.com/@psy.aware/photo/7658292468219186453"
    assert classify_error(msg, url) is UnsupportedMediaError


def test_unsupported_url_non_photo_is_unsupported_site() -> None:
    msg = "ERROR: Unsupported URL: https://example.com/whatever"
    url = "https://example.com/whatever"
    assert classify_error(msg, url) is UnsupportedURLError


def test_case_insensitive() -> None:
    assert classify_error("ERROR: THIS ACCOUNT IS PRIVATE", "http://x") is PrivateContentError


def test_error_keys_are_distinct_and_present() -> None:
    # Every category must carry a non-empty error_key, and they must all
    # differ — the whole point is category-specific messaging.
    types = [
        PrivateContentError,
        GeoRestrictedError,
        AgeRestrictedError,
        ContentUnavailableError,
        UnsupportedMediaError,
        ExtractionError,
        UnsupportedURLError,
    ]
    keys = [t.error_key for t in types]
    assert all(keys)
    assert len(keys) == len(set(keys))
