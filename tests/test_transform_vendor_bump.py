import json
import subprocess

import pytest

from gorget.config.schema import ToolchainEntry, VendorBumpEntry, VendorBumpStep, VendorModule
from gorget.config.substitution import SubstitutionVars
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.state import StageState
from gorget.transform.base import TransformContext
from gorget.transform.vendor_bump import (
    _STRATEGIES,
    VendorBumpHandler,
    _CargoPin,
    _GoPin,
    _parse_constraint,
)

_NPM = _STRATEGIES["npm"]
_PNPM = _STRATEGIES["pnpm"]
_YARN = _STRATEGIES["yarn"]


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
    entry = VendorBumpEntry(dependency="golang.org/x/net", version="0.23.0")
    _GoPin().apply(tmp_path, entry, [])
    assert mock_run.call_args_list[0].args[0] == [
        "go", "mod", "edit", "-require=golang.org/x/net@0.23.0",
    ]
    assert mock_run.call_args_list[1].args[0] == ["go", "mod", "tidy"]


def test_go_pin_edit_failure_raises(tmp_path, mocker):
    mocker.patch("gorget.transform.vendor_bump.run", return_value=_fail("bad module"))
    entry = VendorBumpEntry(dependency="x", version="1.0.0")
    with pytest.raises(GorgetTransientError, match="bad module"):
        _GoPin().apply(tmp_path, entry, [])


def test_go_pin_tilde_prefix(tmp_path, mocker):
    mock_run = mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    entry = VendorBumpEntry(dependency="golang.org/x/text", version="~0.39")
    _GoPin().apply(tmp_path, entry, [])
    assert mock_run.call_args_list[0].args[0] == [
        "go", "mod", "edit", "-require=golang.org/x/text@0.39",
    ]


# --- npm (direct + transitive via overrides) ---


def test_npm_direct_bumps_dependency_and_adds_override(tmp_path, mocker):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"left-pad": "^1.0.0"}}))
    mock_run = mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    _NPM.apply(tmp_path, VendorBumpEntry(dependency="left-pad", version="1.3.0"), [])

    data = json.loads((tmp_path / "package.json").read_text())
    # Direct declaration reconciled AND override added (forces every copy).
    assert data["dependencies"]["left-pad"] == ">=1.3.0"
    assert data["overrides"]["left-pad"] == ">=1.3.0"
    # Full install (not --package-lock-only) -- only a real resolve applies the
    # override to a pruned transitive.
    assert mock_run.call_args.args[0] == [
        "npm", "install", "--ignore-scripts", "--no-audit", "--no-fund",
    ]


def test_npm_transitive_only_adds_override_no_error(tmp_path, mocker):
    # Dependency is NOT a direct dep -- the common CVE case. Must not error;
    # forces it via overrides.
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"express": "^4.0.0"}}))
    mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    _NPM.apply(tmp_path, VendorBumpEntry(dependency="minimist", version="1.2.6"), [])

    data = json.loads((tmp_path / "package.json").read_text())
    assert data["overrides"]["minimist"] == ">=1.2.6"
    assert "minimist" not in data.get("dependencies", {})  # not fabricated as direct


def test_npm_prunes_target_and_dependents_from_lock(tmp_path, mocker):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react-router-dom": "^7"}}))
    (tmp_path / "package-lock.json").write_text(json.dumps({"packages": {
        "": {"name": "root"},
        "mantine-ui": {"dependencies": {"react-router-dom": "^7.17.0"}},  # workspace root, keep
        "node_modules/react-router": {"version": "7.17.0"},               # target -> prune
        "node_modules/react-router-dom": {
            "version": "7.17.0", "dependencies": {"react-router": "7.17.0"}},  # dependent -> prune
        "node_modules/unrelated": {"version": "1.0.0"},                   # keep
    }}))
    mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    _NPM.apply(tmp_path, VendorBumpEntry(dependency="react-router", version="~7.18"), [])

    pkgs = json.loads((tmp_path / "package-lock.json").read_text())["packages"]
    assert "node_modules/react-router" not in pkgs        # target pruned
    assert "node_modules/react-router-dom" not in pkgs    # dependent pruned
    assert "node_modules/unrelated" in pkgs               # untouched
    assert "mantine-ui" in pkgs and "" in pkgs            # roots never pruned


def test_npm_tilde_prefix(tmp_path, mocker):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"lodash": "^4.0.0"}}))
    mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    _NPM.apply(tmp_path, VendorBumpEntry(dependency="lodash", version="~4.18"), [])
    data = json.loads((tmp_path / "package.json").read_text())
    assert data["dependencies"]["lodash"] == "~4.18"
    assert data["overrides"]["lodash"] == "~4.18"


def test_npm_removes_node_modules_after_install(tmp_path, mocker):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"x": "^1.0.0"}}))

    def _install(args, cwd=None):
        (tmp_path / "node_modules").mkdir(exist_ok=True)
        return _ok()

    mocker.patch("gorget.transform.vendor_bump.run", side_effect=_install)
    _NPM.apply(tmp_path, VendorBumpEntry(dependency="x", version="1.0.0"), [])
    assert not (tmp_path / "node_modules").exists()


def test_npm_missing_package_json_raises(tmp_path):
    with pytest.raises(GorgetConfigError, match="no package.json"):
        _NPM.apply(tmp_path, VendorBumpEntry(dependency="x", version="1.0.0"), [])


def test_npm_install_failure_raises(tmp_path, mocker):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"x": "^1.0.0"}}))
    mocker.patch("gorget.transform.vendor_bump.run", return_value=_fail("npm error"))
    with pytest.raises(GorgetTransientError, match="npm error"):
        _NPM.apply(tmp_path, VendorBumpEntry(dependency="x", version="1.0.0"), [])


# --- pnpm ---


def test_pnpm_writes_overrides_to_workspace_yaml(tmp_path, mocker):
    import yaml

    # pnpm v10+ ignores package.json's `pnpm` field -- overrides must land in
    # pnpm-workspace.yaml (created here if absent).
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react": "^18.0.0"}}))
    mock_run = mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    _PNPM.apply(tmp_path, VendorBumpEntry(dependency="nanoid", version="3.3.8"), [])

    ws = yaml.safe_load((tmp_path / "pnpm-workspace.yaml").read_text())
    assert ws["overrides"]["nanoid"] == ">=3.3.8"
    # Not written to the ignored package.json `pnpm` field.
    assert "pnpm" not in json.loads((tmp_path / "package.json").read_text())
    assert mock_run.call_args.args[0][:2] == ["pnpm", "install"]
    assert "--lockfile-only" in mock_run.call_args.args[0]


def test_pnpm_merges_existing_workspace_yaml(tmp_path, mocker):
    import yaml

    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react": "^18.0.0"}}))
    (tmp_path / "pnpm-workspace.yaml").write_text('packages:\n  - "mantine-ui"\n')
    mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    _PNPM.apply(tmp_path, VendorBumpEntry(dependency="nanoid", version="3.3.8"), [])

    ws = yaml.safe_load((tmp_path / "pnpm-workspace.yaml").read_text())
    assert ws["packages"] == ["mantine-ui"]  # preserved
    assert ws["overrides"]["nanoid"] == ">=3.3.8"


# --- yarn (v1 vs Berry) ---


def test_yarn_v1_uses_resolutions_and_plain_install(tmp_path, mocker):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react": "^17.0.0"}}))
    mock_run = mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    _YARN.apply(tmp_path, VendorBumpEntry(dependency="minimist", version="1.2.6"), [])

    data = json.loads((tmp_path / "package.json").read_text())
    assert data["resolutions"]["minimist"] == ">=1.2.6"
    assert mock_run.call_args.args[0] == ["yarn", "install"]


def test_yarn_berry_uses_update_lockfile_mode(tmp_path, mocker):
    (tmp_path / "package.json").write_text(
        json.dumps({"packageManager": "yarn@4.15.0", "dependencies": {"react": "^18.0.0"}})
    )
    mock_run = mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    _YARN.apply(tmp_path, VendorBumpEntry(dependency="minimist", version="1.2.6"), [])
    assert mock_run.call_args.args[0] == ["yarn", "install", "--mode", "update-lockfile"]


# --- cargo (direct in Cargo.toml, transitive via --precise) ---


def test_cargo_direct_bumps_toml_and_updates(tmp_path, mocker):
    (tmp_path / "Cargo.toml").write_text('[dependencies]\nserde = "1.0.0"\nlibc = "0.2.0"\n')
    mock_run = mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    _CargoPin().apply(tmp_path, VendorBumpEntry(dependency="serde", version="1.0.190"), [])

    text = (tmp_path / "Cargo.toml").read_text()
    assert 'serde = ">=1.0.190"' in text
    assert 'libc = "0.2.0"' in text  # untouched
    assert mock_run.call_args.args[0] == ["cargo", "update", "-p", "serde"]


def test_cargo_transitive_uses_precise(tmp_path, mocker):
    # Not a direct dependency in Cargo.toml -> pin exact version in the lockfile.
    (tmp_path / "Cargo.toml").write_text('[dependencies]\nlibc = "0.2.0"\n')
    mock_run = mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    _CargoPin().apply(tmp_path, VendorBumpEntry(dependency="smallvec", version="1.13.2"), [])
    assert mock_run.call_args.args[0] == [
        "cargo", "update", "-p", "smallvec", "--precise", "1.13.2",
    ]


def test_cargo_missing_toml_raises(tmp_path):
    with pytest.raises(GorgetConfigError, match="no Cargo.toml"):
        _CargoPin().apply(tmp_path, VendorBumpEntry(dependency="serde", version="1.0.0"), [])


def test_cargo_update_failure_raises(tmp_path, mocker):
    (tmp_path / "Cargo.toml").write_text('[dependencies]\nserde = "1.0.0"\n')
    mocker.patch("gorget.transform.vendor_bump.run", return_value=_fail("cargo error"))
    with pytest.raises(GorgetTransientError, match="cargo error"):
        _CargoPin().apply(tmp_path, VendorBumpEntry(dependency="serde", version="1.0.190"), [])


# --- VendorBumpHandler ---


def test_handler_applies_pins_per_module(tmp_path, mocker):
    source_dir = tmp_path / "src"
    (source_dir / "server").mkdir(parents=True)
    (source_dir / "server" / "go.mod").write_text("module example\n")
    mock_run = mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    # No resolver -> skip both skip-check and post-verify; isolate dispatch.
    mocker.patch.dict("gorget.transform.vendor_bump._RESOLVERS", clear=True)

    ctx = make_ctx(tmp_path / "work", source_dir=source_dir)
    state = make_state(tmp_path / "work")
    step = VendorBumpStep(
        ecosystem="go",
        pins=[VendorBumpEntry(dependency="x", version="1.0.0")],
        modules=[VendorModule(path="server")],
    )
    VendorBumpHandler().run(step, ctx, state)

    assert mock_run.call_args_list[0].kwargs["cwd"] == source_dir / "server"
    assert state.source_dirty is True


def test_handler_dry_run_does_nothing(tmp_path, mocker):
    mock_run = mocker.patch("gorget.transform.vendor_bump.run")
    ctx = make_ctx(tmp_path / "work", source_dir=None, dry_run=True)
    state = make_state(tmp_path / "work")
    step = VendorBumpStep(ecosystem="go", pins=[VendorBumpEntry(dependency="x", version="1.0.0")])
    VendorBumpHandler().run(step, ctx, state)
    mock_run.assert_not_called()


# --- Skip-if-satisfied ---


def test_handler_skips_when_version_already_satisfies_minimum(tmp_path, mocker):
    source = tmp_path / "src"
    source.mkdir()
    (source / "package.json").write_text(json.dumps({"dependencies": {"lodash": "^4.17.21"}}))
    (source / "package-lock.json").write_text(
        json.dumps({"packages": {"node_modules/lodash": {"version": "4.18.0"}}})
    )
    mock_run = mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    step = VendorBumpStep(
        ecosystem="npm",
        pins=[VendorBumpEntry(dependency="lodash", version="4.17.21")],
        modules=[VendorModule(path=".")],
    )
    VendorBumpHandler().run(step, make_ctx(tmp_path, source), make_state(tmp_path))
    mock_run.assert_not_called()


def test_handler_skips_when_version_matches_prefix(tmp_path, mocker):
    source = tmp_path / "src"
    source.mkdir()
    (source / "package.json").write_text(json.dumps({"dependencies": {"lodash": "^4.18.0"}}))
    (source / "package-lock.json").write_text(
        json.dumps({"packages": {"node_modules/lodash": {"version": "4.18.2"}}})
    )
    mock_run = mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    step = VendorBumpStep(
        ecosystem="npm",
        pins=[VendorBumpEntry(dependency="lodash", version="~4.18")],
        modules=[VendorModule(path=".")],
    )
    VendorBumpHandler().run(step, make_ctx(tmp_path, source), make_state(tmp_path))
    mock_run.assert_not_called()


def test_handler_applies_when_version_does_not_satisfy(tmp_path, mocker):
    source = tmp_path / "src"
    source.mkdir()
    (source / "package.json").write_text(json.dumps({"dependencies": {"lodash": "^4.17.0"}}))
    lock = source / "package-lock.json"
    lock.write_text(json.dumps({"packages": {"node_modules/lodash": {"version": "4.17.0"}}}))

    # Simulate `npm install` updating the lockfile to the bumped version, so the
    # post-apply verification sees the new version.
    def _install(args, cwd=None):
        lock.write_text(json.dumps({"packages": {"node_modules/lodash": {"version": "4.18.0"}}}))
        return _ok()

    mock_run = mocker.patch("gorget.transform.vendor_bump.run", side_effect=_install)
    step = VendorBumpStep(
        ecosystem="npm",
        pins=[VendorBumpEntry(dependency="lodash", version="4.18.0")],
        modules=[VendorModule(path=".")],
    )
    VendorBumpHandler().run(step, make_ctx(tmp_path, source), make_state(tmp_path))
    mock_run.assert_called_once()


# --- Post-apply verification ---


def test_handler_raises_when_dependency_absent_after_bump(tmp_path, mocker):
    source = tmp_path / "src"
    source.mkdir()
    (source / "package.json").write_text(json.dumps({"dependencies": {"express": "^4.0.0"}}))
    (source / "package-lock.json").write_text(json.dumps({"packages": {}}))  # dep never appears
    mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    step = VendorBumpStep(
        ecosystem="npm",
        pins=[VendorBumpEntry(dependency="not-in-tree", version="1.0.0")],
        modules=[VendorModule(path=".")],
    )
    with pytest.raises(GorgetConfigError, match="not present in the dependency tree"):
        VendorBumpHandler().run(step, make_ctx(tmp_path, source), make_state(tmp_path))


def test_handler_raises_when_bump_did_not_take(tmp_path, mocker):
    # Lockfile still shows the old version after install (e.g. npm too old to
    # honor overrides) -> the tool must fail loudly, not ship a vulnerable dep.
    source = tmp_path / "src"
    source.mkdir()
    (source / "package.json").write_text(json.dumps({"dependencies": {"minimist": "^1.2.0"}}))
    lock = source / "package-lock.json"
    lock.write_text(json.dumps({"packages": {"node_modules/minimist": {"version": "1.2.0"}}}))

    # Simulate npm reinstalling the OLD version (override not honored): the
    # handler must fail closed on the version, not silently pass.
    def _install(args, cwd=None):
        lock.write_text(json.dumps({"packages": {"node_modules/minimist": {"version": "1.2.0"}}}))
        return _ok()

    mocker.patch("gorget.transform.vendor_bump.run", side_effect=_install)
    step = VendorBumpStep(
        ecosystem="npm",
        pins=[VendorBumpEntry(dependency="minimist", version="1.2.6")],
        modules=[VendorModule(path=".")],
    )
    with pytest.raises(GorgetTransientError, match="does not satisfy"):
        VendorBumpHandler().run(step, make_ctx(tmp_path, source), make_state(tmp_path))


# --- _parse_constraint ---


def test_parse_constraint_plain_version():
    assert _parse_constraint("0.39.0") == ("minimum", "0.39.0")


def test_parse_constraint_tilde_prefix():
    assert _parse_constraint("~4.18") == ("prefix", "4.18")


def test_toolchain_param_does_not_change_command(tmp_path, mocker):
    mock_run = mocker.patch("gorget.transform.vendor_bump.run", return_value=_ok())
    entry = VendorBumpEntry(dependency="golang.org/x/net", version="0.23.0")
    _GoPin().apply(tmp_path, entry, [ToolchainEntry(name="go", version="1.22.0")])
    assert mock_run.call_args_list[0].args[0][:3] == ["go", "mod", "edit"]
