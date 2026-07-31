"""Resolve ${{ steps.<id>.<path> }} expressions against pipeline state."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from gorget.exceptions import GorgetConfigError

_EXPR_RE = re.compile(r"\$\{\{\s*(.+?)\s*\}\}")


def resolve_expression(value: str, get_output: Callable) -> Any:
    """Resolve ${{ }} expressions in a string value.

    If the entire value is a single expression, return the raw Python
    object (preserving type). If expressions are embedded in a larger
    string, stringify and interpolate.
    """
    def _resolve(dotpath: str) -> Any:
        try:
            return get_output(dotpath)
        except KeyError as exc:
            raise GorgetConfigError(
                f"expression ${{{{ {dotpath} }}}} could not be resolved: {exc}"
            ) from exc

    match = _EXPR_RE.fullmatch(value.strip())
    if match:
        return _resolve(match.group(1))

    def replacer(m: re.Match) -> str:
        return str(_resolve(m.group(1)))

    return _EXPR_RE.sub(replacer, value)


def resolve_step_expressions(step_dict: dict, get_output: Callable) -> dict:
    """Walk a step's fields and resolve any ${{ }} expressions."""
    resolved = {}
    for key, value in step_dict.items():
        if isinstance(value, str) and "${{" in value:
            resolved[key] = resolve_expression(value, get_output)
        elif isinstance(value, list):
            resolved[key] = [
                resolve_expression(v, get_output) if isinstance(v, str) and "${{" in v else v
                for v in value
            ]
        else:
            resolved[key] = value
    return resolved
