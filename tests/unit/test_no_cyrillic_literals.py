"""Guard: no Cyrillic anywhere in ``src/`` — literals, comments, docstrings.

User-facing text lives in ``locales/*/messages.ftl``; a Cyrillic literal
in code is either text a non-Russian user would read (the bug this guard
was written after: URL rejection reasons, "Untitled", "MB/s") or a log
line. Comments and docstrings are English by project convention; they are
checked separately so a failure says which kind it is.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
_CYRILLIC = re.compile("[\u0400-\u04ff]")


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _cyrillic_literals(source: str) -> list[int]:
    tree = ast.parse(source)
    docstrings = _docstring_nodes(tree)
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and _CYRILLIC.search(node.value)
    ]


def test_no_cyrillic_string_literals_in_src() -> None:
    files = sorted(SRC.rglob("*.py"))
    assert files, "no modules found under src/ — the scan would pass vacuously"
    violations = [
        f"  {path.relative_to(SRC.parent).as_posix()}:{line}"
        for path in files
        for line in _cyrillic_literals(path.read_text(encoding="utf-8"))
    ]
    assert not violations, "move user-facing text to locales/*.ftl:\n" + "\n".join(violations)


def _cyrillic_comments_and_docstrings(source: str) -> list[int]:
    tree = ast.parse(source)
    lines = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and id(node) in _docstring_nodes(tree)
        and _CYRILLIC.search(str(node.value))
    ]
    lines += [
        token.start[0]
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT and _CYRILLIC.search(token.string)
    ]
    return sorted(lines)


def test_no_cyrillic_comments_or_docstrings_in_src() -> None:
    violations = [
        f"  {path.relative_to(SRC.parent).as_posix()}:{line}"
        for path in sorted(SRC.rglob("*.py"))
        for line in _cyrillic_comments_and_docstrings(path.read_text(encoding="utf-8"))
    ]
    assert not violations, "comments and docstrings are English:\n" + "\n".join(violations)


def test_comment_scanner_sees_comments_and_docstrings() -> None:
    """Guards the guard."""
    source = 'def f():\n    """Документация."""\n    return 1  # комментарий\n'
    assert _cyrillic_comments_and_docstrings(source) == [2, 3]


def test_scanner_sees_plain_and_fstring_literals_but_not_docstrings() -> None:
    """Guards the guard."""
    source = 'def f(x):\n    """Документация."""\n    a = "текст"\n    return f"{x} МБ"\n'
    assert _cyrillic_literals(source) == [3, 4]
