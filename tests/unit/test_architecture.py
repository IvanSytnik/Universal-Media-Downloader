"""Architecture tests: the Clean Architecture dependency rule, enforced.

Every module under ``src/`` is parsed with ``ast`` and its imports are
checked against the layer it lives in. Imports inside ``if TYPE_CHECKING:``
blocks count too — a type-only dependency is still a dependency.

- domain       → standard library and ``src.domain`` only (no frameworks)
- application  → standard library, ``src.domain``, ``src.application``,
                 and the cross-cutting ``src.shared`` kernel (logging)
- presentation → anything except ``src.infrastructure``

Composition roots (``src/main.py``, ``src/composition.py`` and the worker's
``src/infrastructure/queue/worker_settings.py``) sit outside these rules by
design: wiring concrete adapters to ports is their whole job.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
STDLIB = frozenset(sys.stdlib_module_names) | {"__future__"}


def _imported_modules(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # The codebase uses absolute imports only; a relative one would
            # dodge these checks, so it is a violation in its own right.
            assert node.level == 0, f"relative import at line {node.lineno}"
            assert node.module is not None
            found.append((node.lineno, node.module))
    return found


def _layer_imports(layer: str) -> list[tuple[str, int, str]]:
    files = sorted((SRC / layer).rglob("*.py"))
    assert files, f"no modules found under src/{layer} — the scan would pass vacuously"
    result: list[tuple[str, int, str]] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(SRC.parent).as_posix()
        result.extend((rel, line, module) for line, module in _imported_modules(tree))
    return result


def _is_under(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")


def _top_level(module: str) -> str:
    return module.split(".", 1)[0]


def _format(violations: list[tuple[str, int, str]]) -> str:
    return "\n".join(f"  {path}:{line} imports {module}" for path, line, module in violations)


def test_domain_imports_only_stdlib_and_itself() -> None:
    violations = [
        (path, line, module)
        for path, line, module in _layer_imports("domain")
        if not (_top_level(module) in STDLIB or _is_under(module, "src.domain"))
    ]
    assert not violations, "domain must not depend on anything outside itself:\n" + _format(
        violations
    )


def test_application_imports_only_domain() -> None:
    allowed = ("src.domain", "src.application", "src.shared")
    violations = [
        (path, line, module)
        for path, line, module in _layer_imports("application")
        if not (_top_level(module) in STDLIB or any(_is_under(module, p) for p in allowed))
    ]
    assert not violations, "application may depend only on domain:\n" + _format(violations)


def test_presentation_never_imports_infrastructure() -> None:
    violations = [
        (path, line, module)
        for path, line, module in _layer_imports("presentation")
        if _is_under(module, "src.infrastructure")
    ]
    assert not violations, (
        "presentation must receive adapters via the composition root, "
        "not import them:\n" + _format(violations)
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import src.infrastructure.health", "src.infrastructure.health"),
        ("from src.infrastructure.queue import jobs", "src.infrastructure.queue"),
        (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from src.infrastructure.health import ConnectivityHealthCheck\n",
            "src.infrastructure.health",
        ),
    ],
)
def test_scanner_detects_every_import_form(source: str, expected: str) -> None:
    """Guards the guard: a scanner that missed an import form would let the
    layer tests above pass while the rule is broken."""
    modules = [module for _, module in _imported_modules(ast.parse(source))]
    assert expected in modules
