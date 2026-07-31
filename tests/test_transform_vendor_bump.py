import json
import subprocess

import pytest

from gorget.config.schema import ToolchainEntry, VendorModule, VendorBumpEntry, VendorBumpStep
from gorget.config.substitution import SubstitutionVars
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.state import StageState
from gorget.transform.base import TransformContext
from gorget.transform.vendor_bump import VendorBumpHandler, _CargoPin, _GoPin, _NpmPin


def _ok():
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def _fail(stderr="boom"):
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


def make_ctx(work_dir, source_dir, toolchain=(), dry_run=False):
    return TransformContext(
        work_dir=work_dir,
        source_dir=source_dir,
        vars=SubstitutionVars(
            version="1.2.3", old_version=None, package="foo", spec_file="foo.spec"
        ),
        toolchain=list(toolchain),
        dry_run=dry_run,
        package_dir=work_dir,
    )


def make_state(work_dir):
    report = PipelineReport(package="foo", version="1.2.3", old_version=None, dry_run=False)
    return StageState(work_dir=work_dir, spec=None, report=report)


# --- Go ---


def test_go_pin_runs_edit_then_tidy(tmp_path, mocker):
    mock_run = mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    entry = VendorBumpEntry(dependency="golang.org/x/net", minimum_version="0.23.0")
    _GoPin().apply(tmp_path, entry, [])
    assert mock_run.call_args_list[0].args[0] == [
        "go", "mod", "edit", "-require=golang.org/x/net@0.23.0",
    ]
    assert mock_run.call_args_list[1].args[0] == ["go", "mod", "tidy"]


def test_go_pin_toolchain_param_does_not_change_command(tmp_path, mocker):
    # toolchain activation isn't implemented yet (gorget/toolchain.py); the
    # param is accepted but wrap_command() is currently a no-op passthrough.
    mock_run = mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    entry = VendorBumpEntry(dependency="golang.org/x/net", minimum_version="0.23.0")
    _GoPin().apply(tmp_path, entry, [ToolchainEntry(name="go", version="1.22.0")])
    assert mock_run.call_args_list[0].args[0] == [
        "go", "mod", "edit", "-require=golang.org/x/net@0.23.0",
    ]


def test_go_pin_edit_failure_raises(tmp_path, mocker):
    mocker.patch("gorget.transform.vendor_bump.run", return_value=_fail("bad module"))
    entry = VendorBumpEntry(dependency="x", minimum_version="1.0.0")
    with pytest.raises(GorgetTransientError, match="bad module"):
        _GoPin().apply(tmp_path, entry, [])


def test_go_pin_tidy_failure_raises(tmp_path, mocker):
    mocker.patch(
        "gorget.transform.vendor_bump.run", side_effect=[_ok(), _fail("tidy broke")]
    )
    entry = VendorBumpEntry(dependency="x", minimum_version="1.0.0")
    with pytest.raises(GorgetTransientError, match="tidy broke"):
        _GoPin().apply(tmp_path, entry, [])


# --- npm ---


def test_npm_pin_edits_dependencies_and_installs(tmp_path, mocker):
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"left-pad": "^1.0.0"}})
    )
    mock_run = mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    entry = VendorBumpEntry(dependency="left-pad", minimum_version="1.3.0")
    _NpmPin().apply(tmp_path, entry, [])

    data = json.loads((tmp_path / "package.json").read_text())
    assert data["dependencies"]["left-pad"] == ">=1.3.0"
    assert mock_run.call_args.args[0][:2] == ["npm", "install"]
    assert "--package-lock-only" in mock_run.call_args.args[0]


def test_npm_pin_edits_dev_dependencies(tmp_path, mocker):
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"eslint": "^8.0.0"}})
    )
    mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    entry = VendorBumpEntry(dependency="eslint", minimum_version="9.0.0")
    _NpmPin().apply(tmp_path, entry, [])
    data = json.loads((tmp_path / "package.json").read_text())
    assert data["devDependencies"]["eslint"] == ">=9.0.0"


def test_npm_pin_missing_package_json_raises(tmp_path):
    entry = VendorBumpEntry(dependency="x", minimum_version="1.0.0")
    with pytest.raises(GorgetConfigError, match="no package.json"):
        _NpmPin().apply(tmp_path, entry, [])


def test_npm_pin_dependency_not_found_raises(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {}}))
    entry = VendorBumpEntry(dependency="missing-pkg", minimum_version="1.0.0")
    with pytest.raises(GorgetConfigError, match="missing-pkg"):
        _NpmPin().apply(tmp_path, entry, [])


def test_npm_pin_install_failure_raises(tmp_path, mocker):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"x": "^1.0.0"}}))
    mocker.patch("gorget.transform.vendor_bump.run", return_value=_fail("npm error"))
    entry = VendorBumpEntry(dependency="x", minimum_version="1.0.0")
    with pytest.raises(GorgetTransientError, match="npm error"):
        _NpmPin().apply(tmp_path, entry, [])


# --- cargo ---


def test_cargo_pin_edits_toml_and_updates(tmp_path, mocker):
    (tmp_path / "Cargo.toml").write_text(
        '[dependencies]\nserde = "1.0.0"\nlibc = "0.2.0"\n'
    )
    mock_run = mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    entry = VendorBumpEntry(dependency="serde", minimum_version="1.0.190")
    _CargoPin().apply(tmp_path, entry, [])

    text = (tmp_path / "Cargo.toml").read_text()
    assert 'serde = ">=1.0.190"' in text
    assert 'libc = "0.2.0"' in text  # untouched
    assert mock_run.call_args.args[0] == ["cargo", "update"]


def test_cargo_pin_missing_toml_raises(tmp_path):
    entry = VendorBumpEntry(dependency="serde", minimum_version="1.0.0")
    with pytest.raises(GorgetConfigError, match="no Cargo.toml"):
        _CargoPin().apply(tmp_path, entry, [])


def test_cargo_pin_dependency_not_found_raises(tmp_path):
    (tmp_path / "Cargo.toml").write_text('[dependencies]\nlibc = "0.2.0"\n')
    entry = VendorBumpEntry(dependency="serde", minimum_version="1.0.0")
    with pytest.raises(GorgetConfigError, match="not found as a simple inline dependency"):
        _CargoPin().apply(tmp_path, entry, [])


def test_cargo_pin_update_failure_raises(tmp_path, mocker):
    (tmp_path / "Cargo.toml").write_text('[dependencies]\nserde = "1.0.0"\n')
    mocker.patch("gorget.transform.vendor_bump.run", return_value=_fail("cargo error"))
    entry = VendorBumpEntry(dependency="serde", minimum_version="1.0.190")
    with pytest.raises(GorgetTransientError, match="cargo error"):
        _CargoPin().apply(tmp_path, entry, [])


# --- VendorBumpHandler ---


def test_handler_applies_pins_per_module(tmp_path, mocker):
    source_dir = tmp_path / "src"
    (source_dir / "server").mkdir(parents=True)
    (source_dir / "server" / "go.mod").write_text("module example\n")
    mock_run = mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())

    ctx = make_ctx(tmp_path / "work", source_dir=source_dir)
    state = make_state(tmp_path / "work")
    step = VendorBumpStep(
        ecosystem="go",
        pins=[VendorBumpEntry(dependency="x", minimum_version="1.0.0")],
        modules=[VendorModule(path="server")],
    )
    VendorBumpHandler().run(step, ctx, state)

    edit_call = mock_run.call_args_list[0]
    assert edit_call.kwargs["cwd"] == source_dir / "server"


def test_handler_dry_run_does_nothing(tmp_path, mocker):
    mock_run = mocker.patch("gorget.transform.vendor_bump.run")
    ctx = make_ctx(tmp_path / "work", source_dir=None, dry_run=True)
    state = make_state(tmp_path / "work")
    step = VendorBumpStep(
        ecosystem="go", pins=[VendorBumpEntry(dependency="x", minimum_version="1.0.0")]
    )
    VendorBumpHandler().run(step, ctx, state)
    mock_run.assert_not_called()
