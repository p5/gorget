"""Resolve ${{ steps.<id>.<path> }} expressions against pipeline state."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

_EXPR_RE = re.compile(r"\$\{\{\s*(.+?)\s*\}\}")


def resolve_expression(value: str, get_output: Callable) -> Any:
    """Resolve ${{ }} expressions in a string value.

    If the entire value is a single expression, return the raw Python
    object (preserving type). If expressions are embedded in a larger
    string, stringify and interpolate.
    """
    # Check if the entire value is a single expression
    match = _EXPR_RE.fullmatch(value.strip())
    if match:
        return get_output(match.group(1))

    # Otherwise, interpolate into the string
    def replacer(m: re.Match) -> str:
        result = get_output(m.group(1))
        return str(result)

    resolved = _EXPR_RE.sub(replacer, value)
    return resolved


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
