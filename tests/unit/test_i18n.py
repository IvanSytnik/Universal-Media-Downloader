"""Day 9 i18n tests: both locales resolve, ru pluralization, button sets."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.presentation.telegram.i18n import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    collect_button_translations,
    create_i18n_core,
)

# Day 11C stage 5: the key list is DERIVED from the FTL files, not
# maintained by hand.
#
# It used to be a literal list, and it failed open: forgetting to add a
# new key meant a green test and a live gap in a locale. That happened
# twice (11B's progress keys, 11C's error-internal), which is the whole
# argument — a guard that depends on remembering to update the guard is
# not a guard. Now a key that exists in one locale and not the other
# fails here by construction, and a new key is covered the moment it is
# written.
_LOCALES_DIR = Path(__file__).resolve().parents[2] / "locales"

# A message line is `key = value` at column 0; continuation lines are
# indented, so anchoring at the start is what separates them.
_MESSAGE_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9_-]*) *=", re.MULTILINE)
# Fluent placeables: `{ $name }` and selector heads `{ $name ->`.
_VARIABLE_RE = re.compile(r"\{\s*\$([a-zA-Z][a-zA-Z0-9_]*)")


def _ftl_text(locale: str) -> str:
    return (_LOCALES_DIR / locale / "messages.ftl").read_text(encoding="utf-8")


def _keys_in(locale: str) -> set[str]:
    return set(_MESSAGE_RE.findall(_ftl_text(locale)))


def _variables_by_key(locale: str) -> dict[str, set[str]]:
    """Map each message to the argument names it interpolates.

    Needed so the resolve test can call parametrized messages with
    something — a message rendered without its arguments doesn't prove
    much (and for plural selectors, doesn't resolve at all).
    """
    text = _ftl_text(locale)
    starts = [(m.group(1), m.start()) for m in _MESSAGE_RE.finditer(text)]
    result: dict[str, set[str]] = {}
    for i, (key, start) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else len(text)
        result[key] = set(_VARIABLE_RE.findall(text[start:end]))
    return result


def test_locales_declare_exactly_the_same_keys() -> None:
    """The parity guard. Any key present in one locale and missing in the
    other is a live hole: core.get raises with raise_key_error=True, so
    the user hits an exception instead of a message."""
    per_locale = {locale: _keys_in(locale) for locale in SUPPORTED_LOCALES}
    reference = per_locale[DEFAULT_LOCALE]
    for locale, keys in per_locale.items():
        assert keys == reference, (
            f"{locale} differs from {DEFAULT_LOCALE}: "
            f"only in {locale}: {sorted(keys - reference)}, "
            f"missing from {locale}: {sorted(reference - keys)}"
        )


def test_locales_are_not_empty() -> None:
    # Guards the parser itself: a regex that matched nothing would make
    # the parity test above pass against two empty sets.
    assert len(_keys_in(DEFAULT_LOCALE)) > 20


@pytest.fixture
async def core():
    c = create_i18n_core()
    await c.startup()
    return c


@pytest.mark.asyncio
async def test_every_key_resolves_in_every_locale(core) -> None:
    """Every message in the files actually renders — no key is a stub, a
    typo, or a broken selector. Arguments are supplied from the message's
    own placeables, so parametrized keys are covered too (1 works for
    both plural selectors and plain interpolation)."""
    variables = _variables_by_key(DEFAULT_LOCALE)
    for locale in SUPPORTED_LOCALES:
        for key in _keys_in(locale):
            value = core.get(key, locale, **{name: 1 for name in variables.get(key, ())})
            assert value and value != key, f"{locale}:{key} unresolved"


@pytest.mark.asyncio
async def test_parametrized_keys_resolve(core) -> None:
    for locale in SUPPORTED_LOCALES:
        assert core.get("help-text", locale, platforms="youtube.com",
                        downloads=10, previews=5, filesize=50)
        assert core.get("preview-card", locale, title="t", uploader="u",
                        duration="1:00", mediatype="video")
        assert core.get("error-bad-url", locale, reason="x")
        assert core.get("worker-ping-enqueued", locale, jobid="abc")
        assert core.get("progress-downloading", locale, percent=42)
        assert core.get("progress-downloading-nostream", locale, mb=1.5, speed="1.0 MB/s")


@pytest.mark.asyncio
async def test_russian_pluralization(core) -> None:
    # ru has distinct one/few/many forms — the whole reason we chose Fluent.
    one = core.get("rate-limit-seconds", "ru", seconds=1)
    few = core.get("rate-limit-seconds", "ru", seconds=3)
    many = core.get("rate-limit-seconds", "ru", seconds=5)
    assert "секунду" in one
    assert "секунды" in few
    assert "секунд" in many and "секунды" not in many
    assert "минуту" in core.get("rate-limit-minutes", "ru", minutes=1)


@pytest.mark.asyncio
async def test_english_pluralization(core) -> None:
    assert "1 second" in core.get("rate-limit-seconds", "en", seconds=1)
    assert "5 seconds" in core.get("rate-limit-seconds", "en", seconds=5)


@pytest.mark.asyncio
async def test_button_translations_cover_all_locales(core) -> None:
    translations = collect_button_translations(core)
    assert "btn-download" in translations
    assert "btn-help" in translations
    # Each button's set has one entry per locale (unless two locales share
    # an identical label, which they don't here).
    assert core.get("btn-download", "ru") in translations["btn-download"]
    assert core.get("btn-download", "en") in translations["btn-download"]
    assert len(translations["btn-download"]) == len(SUPPORTED_LOCALES)


def test_default_locale_is_supported() -> None:
    assert DEFAULT_LOCALE in SUPPORTED_LOCALES


@pytest.mark.asyncio
async def test_get_without_locale_outside_request_raises(core) -> None:
    # Regression guard (Day 9): outside an update-handling context there is
    # no current I18nContext, so core.get(key) WITHOUT an explicit locale
    # tries to read the request-scoped locale and raises LookupError. Any
    # startup-time call (e.g. set_my_commands in main.py) MUST pass a locale
    # explicitly. This test locks that contract in.
    with pytest.raises(LookupError):
        core.get("cmd-start")
    # ...while passing a locale explicitly works fine.
    assert core.get("cmd-start", "en")
