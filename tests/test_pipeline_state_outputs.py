"""Tests for step output tracking in StageState."""

import pytest
from unittest.mock import Mock

from gorget.pipeline.result import PipelineReport
from gorget.pipeline.state import StageState


def make_state(tmp_path):
    report = PipelineReport(package="foo", version="1.2.3", old_version=None, dry_run=False)
    return StageState(work_dir=tmp_path, spec=Mock(), report=report)


def test_set_and_get_step_output(tmp_path):
    state = make_state(tmp_path)
    state.set_step_output("npm-vendor", "bundled_provides", {"production": [("a", "1.0")]})
    result = state.get_step_output("steps.npm-vendor.bundled_provides.production")
    assert result == [("a", "1.0")]


def test_get_step_output_top_level_key(tmp_path):
    state = make_state(tmp_path)
    state.set_step_output("build", "version", "1.2.3")
    assert state.get_step_output("steps.build.version") == "1.2.3"


def test_get_step_output_missing_step_raises(tmp_path):
    state = make_state(tmp_path)
    with pytest.raises(KeyError, match="no outputs from step 'missing'"):
        state.get_step_output("steps.missing.key")


def test_get_step_output_invalid_prefix_raises(tmp_path):
    state = make_state(tmp_path)
    with pytest.raises(KeyError, match="invalid output reference"):
        state.get_step_output("invalid.path")


def test_get_step_output_too_short_raises(tmp_path):
    state = make_state(tmp_path)
    with pytest.raises(KeyError, match="invalid output reference"):
        state.get_step_output("steps.only")


def test_get_step_output_deep_nested(tmp_path):
    state = make_state(tmp_path)
    state.set_step_output("vendor", "data", {"level1": {"level2": "deep"}})
    assert state.get_step_output("steps.vendor.data.level1.level2") == "deep"


def test_get_step_output_non_dict_traversal_raises(tmp_path):
    state = make_state(tmp_path)
    state.set_step_output("vendor", "version", "1.0")
    with pytest.raises(KeyError, match="cannot resolve"):
        state.get_step_output("steps.vendor.version.sub")


def test_step_outputs_default_empty(tmp_path):
    state = make_state(tmp_path)
    assert state.step_outputs == {}
