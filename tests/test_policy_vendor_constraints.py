import json
import subprocess

import pytest

from gorget.config.schema import VendorConstraintEntry
from gorget.exceptions import GorgetConfigError
from gorget.policy.base import VendoredModule
from gorget.policy.vendor_constraints import check_vendor_constraints


def _ok(stdout=""):
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _fail(stderr="not found"):
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


def make_entry(
    package="golang.org/x/crypto", ecosystem="go", version="0.31.0", reason="CVE fix"
):
    return VendorConstraintEntry(
        package=package, ecosystem=ecosystem, version=version, reason=reason
    )


# --- Go ---


def test_go_constraint_passes(tmp_path, mocker):
    mocker.patch(
        "gorget.policy.vendor_constraints.run",
        return_value=_ok("golang.org/x/crypto v0.31.0\n"),
    )
    entry = make_entry()
    modules = [VendoredModule(ecosystem="go", path=tmp_path)]
    results = check_vendor_constraints([entry], modules)
    assert results[0].status == "passed"


def test_go_constraint_fails_when_below_minimum(tmp_path, mocker):
    mocker.patch(
        "gorget.policy.vendor_constraints.run",
        return_value=_ok("golang.org/x/crypto v0.30.0\n"),
    )
    entry = make_entry()
    modules = [VendoredModule(ecosystem="go", path=tmp_path)]
    results = check_vendor_constraints([entry], modules)
    assert results[0].status == "failed"
    assert "0.30.0" in results[0].reason
    assert "0.31.0" in results[0].reason


def test_go_constraint_fails_when_not_found(tmp_path, mocker):
    mocker.patch("gorget.policy.vendor_constraints.run", return_value=_fail())
    entry = make_entry()
    modules = [VendoredModule(ecosystem="go", path=tmp_path)]
    results = check_vendor_constraints([entry], modules)
    assert results[0].status == "failed"
    assert "not found" in results[0].reason


# --- npm ---


def test_npm_constraint_passes(tmp_path):
    pkg_dir = tmp_path / "node_modules" / "sanitize-html"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.json").write_text(json.dumps({"version": "2.17.5"}))
    entry = make_entry(package="sanitize-html", ecosystem="npm", version="2.17.5")
    modules = [VendoredModule(ecosystem="npm", path=tmp_path)]
    results = check_vendor_constraints([entry], modules)
    assert results[0].status == "passed"


def test_npm_constraint_fails_when_below_minimum(tmp_path):
    pkg_dir = tmp_path / "node_modules" / "sanitize-html"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.json").write_text(json.dumps({"version": "2.16.0"}))
    entry = make_entry(package="sanitize-html", ecosystem="npm", version="2.17.5")
    modules = [VendoredModule(ecosystem="npm", path=tmp_path)]
    results = check_vendor_constraints([entry], modules)
    assert results[0].status == "failed"


def test_npm_constraint_handles_scoped_package(tmp_path):
    pkg_dir = tmp_path / "node_modules" / "@scope" / "pkg"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.json").write_text(json.dumps({"version": "1.0.0"}))
    entry = make_entry(package="@scope/pkg", ecosystem="npm", version="1.0.0")
    modules = [VendoredModule(ecosystem="npm", path=tmp_path)]
    results = check_vendor_constraints([entry], modules)
    assert results[0].status == "passed"


def test_npm_constraint_fails_when_not_found(tmp_path):
    entry = make_entry(package="sanitize-html", ecosystem="npm", version="2.17.5")
    modules = [VendoredModule(ecosystem="npm", path=tmp_path)]
    results = check_vendor_constraints([entry], modules)
    assert results[0].status == "failed"
    assert "not found" in results[0].reason


# --- Cargo ---


def test_cargo_constraint_passes(tmp_path):
    (tmp_path / "Cargo.lock").write_text(
        '[[package]]\nname = "tokio"\nversion = "1.38.1"\n'
    )
    entry = make_entry(package="tokio", ecosystem="cargo", version="1.38.1")
    modules = [VendoredModule(ecosystem="cargo", path=tmp_path)]
    results = check_vendor_constraints([entry], modules)
    assert results[0].status == "passed"


def test_cargo_constraint_fails_when_below_minimum(tmp_path):
    (tmp_path / "Cargo.lock").write_text(
        '[[package]]\nname = "tokio"\nversion = "1.30.0"\n'
    )
    entry = make_entry(package="tokio", ecosystem="cargo", version="1.38.1")
    modules = [VendoredModule(ecosystem="cargo", path=tmp_path)]
    results = check_vendor_constraints([entry], modules)
    assert results[0].status == "failed"


def test_cargo_constraint_uses_highest_of_multiple_resolved_versions(tmp_path):
    (tmp_path / "Cargo.lock").write_text(
        '[[package]]\nname = "tokio"\nversion = "1.20.0"\n\n'
        '[[package]]\nname = "tokio"\nversion = "1.38.1"\n'
    )
    entry = make_entry(package="tokio", ecosystem="cargo", version="1.38.1")
    modules = [VendoredModule(ecosystem="cargo", path=tmp_path)]
    results = check_vendor_constraints([entry], modules)
    assert results[0].status == "passed"


def test_cargo_constraint_fails_when_not_found(tmp_path):
    (tmp_path / "Cargo.lock").write_text('[[package]]\nname = "other"\nversion = "1.0.0"\n')
    entry = make_entry(package="tokio", ecosystem="cargo", version="1.0.0")
    modules = [VendoredModule(ecosystem="cargo", path=tmp_path)]
    results = check_vendor_constraints([entry], modules)
    assert results[0].status == "failed"


# --- Maven ---


def test_maven_constraint_passes(tmp_path, mocker):
    mock_run = mocker.patch(
        "gorget.policy.vendor_constraints.run",
        return_value=_ok("[INFO] +- org.apache.commons:commons-text:jar:1.12.0:compile\n"),
    )
    entry = make_entry(
        package="org.apache.commons:commons-text", ecosystem="maven", version="1.12.0"
    )
    results = check_vendor_constraints(
        [entry], [VendoredModule(ecosystem="maven", path=tmp_path)]
    )
    assert results[0].status == "passed"
    assert mock_run.call_args.args[0] == [
        "mvn",
        "dependency:tree",
        "-Dincludes=org.apache.commons:commons-text",
        "-DoutputType=text",
    ]


def test_maven_constraint_uses_vendor_repository_offline(tmp_path, mocker):
    (tmp_path / "vendor").mkdir()
    mock_run = mocker.patch(
        "gorget.policy.vendor_constraints.run",
        return_value=_ok("[INFO] \\- org.example:lib:jar:2.0.0:runtime\n"),
    )
    entry = make_entry(package="org.example:lib", ecosystem="maven", version="2.0.0")
    results = check_vendor_constraints(
        [entry], [VendoredModule(ecosystem="maven", path=tmp_path)]
    )
    assert results[0].status == "passed"
    assert mock_run.call_args.args[0][:3] == [
        "mvn",
        "-o",
        f"-Dmaven.repo.local={tmp_path / 'vendor'}",
    ]


def test_maven_constraint_fails_when_not_found(tmp_path, mocker):
    mocker.patch("gorget.policy.vendor_constraints.run", return_value=_ok("[INFO] BUILD SUCCESS"))
    entry = make_entry(package="org.example:lib", ecosystem="maven", version="1.0.0")
    results = check_vendor_constraints(
        [entry], [VendoredModule(ecosystem="maven", path=tmp_path)]
    )
    assert results[0].status == "failed"


# --- module discovery / dispatch ---


def test_no_matching_ecosystem_module_raises_config_error(tmp_path):
    entry = make_entry(ecosystem="npm")
    modules = [VendoredModule(ecosystem="go", path=tmp_path)]
    with pytest.raises(GorgetConfigError, match="npm"):
        check_vendor_constraints([entry], modules)


def test_checks_across_all_modules_for_ecosystem(tmp_path, mocker):
    mocker.patch(
        "gorget.policy.vendor_constraints.run",
        side_effect=[_ok("golang.org/x/crypto v0.31.0\n"), _ok("golang.org/x/crypto v0.20.0\n")],
    )
    entry = make_entry()
    modules = [
        VendoredModule(ecosystem="go", path=tmp_path / "server"),
        VendoredModule(ecosystem="go", path=tmp_path / "etcdctl"),
    ]
    results = check_vendor_constraints([entry], modules)
    assert len(results) == 2
    assert results[0].status == "passed"
    assert results[1].status == "failed"
