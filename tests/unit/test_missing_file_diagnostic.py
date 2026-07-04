"""Tests for _build_missing_file_diagnostic.

This function exists because the same "file missing after reported
success" bug recurred for the same video across multiple guesses at the
root cause. Rather than guess a fourth time, the error message itself
now carries ground truth (directory contents, post_hooks output, info
fields) so the next occurrence is diagnosable directly from the log.
"""

from __future__ import annotations

from src.infrastructure.downloader.ytdlp_downloader import _build_missing_file_diagnostic


def test_diagnostic_includes_directory_contents(tmp_path) -> None:
    (tmp_path / "unexpected_name.mkv").write_bytes(b"x")

    message = _build_missing_file_diagnostic(
        filename=str(tmp_path / "expected.mp4"),
        output_dir=str(tmp_path),
        used_post_hook_filename=True,
        post_hook_filenames=[str(tmp_path / "expected.mp4")],
        info={"id": "abc123", "ext": "mp4"},
    )

    assert "unexpected_name.mkv" in message
    assert "used_post_hook_filename=True" in message
    assert "abc123" in message


def test_diagnostic_handles_missing_directory() -> None:
    message = _build_missing_file_diagnostic(
        filename="/nonexistent/expected.mp4",
        output_dir="/nonexistent",
        used_post_hook_filename=False,
        post_hook_filenames=[],
        info=None,
    )

    assert "could not list directory" in message
    assert "info_summary=None" in message
