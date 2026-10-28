"""Guard: no Cyrillic in string literals under ``src/``.

User-facing text lives in ``locales/*/messages.ftl``; a Cyrillic literal
in code is either text a non-Russian user would read (the bug this guard
was written after: URL rejection reasons, "Untitled", "MB/s") or a log
line, which is English by convention. Docstrings are documentation, not
literals the program emits, and are left out.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
_CYRILLIC = re.compile("[Ѐ-ӿ]")


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


def test_scanner_sees_plain_and_fstring_literals_but_not_docstrings() -> None:
    """Guards the guard."""
    source = 'def f(x):\n    """Документация."""\n    a = "текст"\n    return f"{x} МБ"\n'
    assert _cyrillic_literals(source) == [3, 4]
