"""Tests for ${{ }} expression resolution."""

import pytest

from gorget.config.expression import resolve_expression, resolve_step_expressions


def _mock_output(dotpath: str):
    """Simulate state.get_step_output for testing."""
    store = {
        "steps.npm-vendor.bundled_provides.production": [("lodash", "4.17.21")],
        "steps.npm-vendor.bundled_provides.all": [("lodash", "4.17.21"), ("jest", "29.0.0")],
        "steps.build.version": "1.2.3",
    }
    if dotpath in store:
        return store[dotpath]
    raise KeyError(f"no outputs: {dotpath}")


def test_single_expression_returns_raw_object():
    result = resolve_expression("${{ steps.npm-vendor.bundled_provides.production }}", _mock_output)
    assert result == [("lodash", "4.17.21")]
    assert isinstance(result, list)


def test_single_expression_with_whitespace():
    result = resolve_expression("  ${{   steps.build.version   }}  ", _mock_output)
    assert result == "1.2.3"


def test_embedded_expression_stringifies():
    result = resolve_expression("version is ${{ steps.build.version }}!", _mock_output)
    assert result == "version is 1.2.3!"


def test_no_expression_returns_string_unchanged():
    result = resolve_expression("plain text", _mock_output)
    assert result == "plain text"


def test_invalid_dotpath_raises():
    with pytest.raises(KeyError):
        resolve_expression("${{ invalid.path }}", _mock_output)


def test_resolve_step_expressions_walks_dict():
    step_dict = {
        "type": "bundled-provides",
        "input": "${{ steps.npm-vendor.bundled_provides.production }}",
        "keep": "literal",
    }
    resolved = resolve_step_expressions(step_dict, _mock_output)
    assert resolved["type"] == "bundled-provides"
    assert resolved["input"] == [("lodash", "4.17.21")]
    assert resolved["keep"] == "literal"


def test_resolve_step_expressions_handles_lists():
    step_dict = {
        "items": ["${{ steps.build.version }}", "static"],
    }
    resolved = resolve_step_expressions(step_dict, _mock_output)
    assert resolved["items"] == ["1.2.3", "static"]
