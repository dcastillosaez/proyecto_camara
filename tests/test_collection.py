"""TEST-01: ningún test puede quedar fuera de la recolección por cómo se llama.

`pytest.ini` declaraba solo `python_functions = TEST_*`. En Windows la comparación
ignora mayúsculas y también entraban los `test_*`; en Linux, donde corre CI, no, y
79 funciones (entre ellas las de `tests/test_architecture.py`) pasaban en local y
nunca se ejecutaban en CI. Este test compara con `fnmatchcase`, como hace pytest en
Linux, así que falla en cualquier sistema si un nombre no encaja en los patrones.
"""

from __future__ import annotations

import ast
import configparser
import fnmatch
from pathlib import Path

TESTS_DIR = Path(__file__).parent
PYTEST_INI = TESTS_DIR.parent / "pytest.ini"


def _patterns() -> list[str]:
    parser = configparser.ConfigParser()
    parser.read(PYTEST_INI, encoding="utf-8")
    return parser.get("pytest", "python_functions").split()


def _candidate_functions(tree: ast.Module):
    """Funciones de módulo y métodos de clases `Test*` cuyo nombre parece un test."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield item


def TEST_every_test_function_matches_python_functions():
    patterns = _patterns()
    missed: list[str] = []
    for path in sorted(TESTS_DIR.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in _candidate_functions(tree):
            if not fn.name.lower().startswith("test"):
                continue
            if not any(fnmatch.fnmatchcase(fn.name, p) for p in patterns):
                missed.append(f"{path.relative_to(TESTS_DIR.parent)}:{fn.lineno} {fn.name}")
    assert not missed, (
        f"Funciones que pytest no recogería en Linux con python_functions={patterns}:\n"
        + "\n".join(missed)
    )


def TEST_both_naming_styles_are_collected():
    patterns = _patterns()
    assert any(fnmatch.fnmatchcase("test_x", p) for p in patterns)
    assert any(fnmatch.fnmatchcase("TEST_x", p) for p in patterns)
