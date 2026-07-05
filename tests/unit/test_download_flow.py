"""Unit tests for the guided download flow's pure parts: keyboards
(callback_data budget, structure) and the plain-URL routing predicate.
Handler behavior against Telegram itself is covered by manual smoke
testing per the project's contract-test policy for presentation.
"""

from __future__ import annotations

from src.presentation.telegram.handlers.download_flow import _looks_like_url
from src.presentation.telegram.keyboards import (
    CB_CANCEL_PREFIX,
    CB_CONFIRM_PREFIX,
    main_menu_keyboard,
    preview_confirm_keyboard,
)

# --- keyboards --------------------------------------------------------------


def test_main_menu_has_download_and_help() -> None:
    kb = main_menu_keyboard()
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "flow:download" in callbacks
    assert "flow:help" in callbacks


def test_confirm_keyboard_callback_data_fits_telegram_limit() -> None:
    token = "a" * 32  # uuid4().hex length
    kb = preview_confirm_keyboard(token)
    for row in kb.inline_keyboard:
        for button in row:
            assert button.callback_data is not None
            # Telegram hard limit: 64 bytes.
            assert len(button.callback_data.encode("utf-8")) <= 64


def test_confirm_keyboard_embeds_token_in_both_buttons() -> None:
    kb = preview_confirm_keyboard("cafebabe")
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert CB_CONFIRM_PREFIX + "cafebabe" in callbacks
    assert CB_CANCEL_PREFIX + "cafebabe" in callbacks


# --- plain-URL routing predicate --------------------------------------------


def test_url_predicate_accepts_https() -> None:
    assert _looks_like_url("https://youtube.com/watch?v=abc")


def test_url_predicate_accepts_http() -> None:
    assert _looks_like_url("http://example.com/x")


def test_url_predicate_accepts_leading_whitespace() -> None:
    assert _looks_like_url("  https://youtube.com/x  ")


def test_url_predicate_ignores_chatter() -> None:
    assert not _looks_like_url("привет, как скачать видео?")


def test_url_predicate_ignores_commands() -> None:
    # Commands are handled by earlier routers anyway, but the predicate
    # itself must not claim them either.
    assert not _looks_like_url("/preview https://youtube.com/x")


def test_url_predicate_ignores_bare_domain() -> None:
    # Deliberate: without a scheme we don't guess — the user gets no
    # confusing error for a message that merely mentions a site.
    assert not _looks_like_url("youtube.com/watch?v=abc")
