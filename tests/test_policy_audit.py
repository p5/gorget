import json
import subprocess

import pytest

from gorget.exceptions import GorgetConfigError
from gorget.policy.audit import run_audits
from gorget.policy.base import VendoredModule


def _ok(stdout=""):
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _fail(returncode=1, stdout="", stderr="boom"):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# --- go mod verify: deterministic, fails closed ---


def test_go_mod_verify_passes(tmp_path, mocker):
    mocker.patch("gorget.policy.audit.run", return_value=_ok())
    results = run_audits([VendoredModule(ecosystem="go", path=tmp_path)])
    assert results[0].status == "passed"


def test_go_mod_verify_fails_closed(tmp_path, mocker):
    mocker.patch(
        "gorget.policy.audit.run", return_value=_fail(stderr="checksum mismatch")
    )
    results = run_audits([VendoredModule(ecosystem="go", path=tmp_path)])
    assert results[0].status == "failed"
    assert "checksum mismatch" in results[0].reason


# --- npm audit: warn-only, never raises ---


def test_npm_audit_clean_passes(tmp_path, mocker):
    mocker.patch("gorget.policy.audit.run", return_value=_ok())
    results = run_audits([VendoredModule(ecosystem="npm", path=tmp_path)])
    assert results[0].status == "passed"


def test_npm_audit_findings_are_warning_not_failure(tmp_path, mocker):
    stdout = json.dumps({"metadata": {"vulnerabilities": {"high": 2, "low": 0}}})
    mocker.patch(
        "gorget.policy.audit.run", return_value=_fail(returncode=1, stdout=stdout)
    )
    results = run_audits([VendoredModule(ecosystem="npm", path=tmp_path)])
    assert results[0].status == "warning"
    assert "2 vulnerabilities found" in results[0].reason


def test_npm_audit_unparseable_output_still_warns_not_raises(tmp_path, mocker):
    mocker.patch(
        "gorget.policy.audit.run", return_value=_fail(returncode=1, stdout="not json")
    )
    results = run_audits([VendoredModule(ecosystem="npm", path=tmp_path)])
    assert results[0].status == "warning"
    assert results[0].reason == "not json"


# --- cargo audit: requires the cargo-audit binary, warn-only when it runs ---


def test_cargo_audit_missing_binary_raises_config_error(tmp_path, mocker):
    mocker.patch("gorget.policy.audit.shutil.which", return_value=None)
    with pytest.raises(GorgetConfigError, match="cargo-audit"):
        run_audits([VendoredModule(ecosystem="cargo", path=tmp_path)])


def test_cargo_audit_findings_are_warning_not_failure(tmp_path, mocker):
    mocker.patch("gorget.policy.audit.shutil.which", return_value="/usr/bin/cargo-audit")
    mocker.patch(
        "gorget.policy.audit.run", return_value=_fail(returncode=1, stdout="1 vulnerability found")
    )
    results = run_audits([VendoredModule(ecosystem="cargo", path=tmp_path)])
    assert results[0].status == "warning"
    assert "vulnerability" in results[0].reason


def test_cargo_audit_clean_passes(tmp_path, mocker):
    mocker.patch("gorget.policy.audit.shutil.which", return_value="/usr/bin/cargo-audit")
    mocker.patch("gorget.policy.audit.run", return_value=_ok())
    results = run_audits([VendoredModule(ecosystem="cargo", path=tmp_path)])
    assert results[0].status == "passed"


# --- Maven audit: OWASP dependency-check, warn-only ---


def test_maven_audit_clean_passes(tmp_path, mocker):
    mock_run = mocker.patch("gorget.policy.audit.run", return_value=_ok())
    results = run_audits([VendoredModule(ecosystem="maven", path=tmp_path)])
    assert results[0].status == "passed"
    assert mock_run.call_args.args[0] == [
        "mvn",
        "org.owasp:dependency-check-maven:13.0.0:check",
        "-DfailBuildOnCVSS=0",
        "-DnvdApiKeyEnvironmentVariable=NVD_API_KEY",
    ]


def test_maven_audit_findings_are_warning_not_failure(tmp_path, mocker):
    mocker.patch(
        "gorget.policy.audit.run",
        return_value=_fail(stdout="One or more dependencies were identified with vulnerabilities"),
    )
    results = run_audits([VendoredModule(ecosystem="maven", path=tmp_path)])
    assert results[0].status == "warning"
    assert "vulnerabilities" in results[0].reason


# --- dispatch across multiple modules ---


def test_run_audits_dispatches_per_ecosystem(tmp_path, mocker):
    mocker.patch("gorget.policy.audit.shutil.which", return_value="/usr/bin/cargo-audit")
    mocker.patch("gorget.policy.audit.run", return_value=_ok())
    modules = [
        VendoredModule(ecosystem="go", path=tmp_path / "a"),
        VendoredModule(ecosystem="npm", path=tmp_path / "b"),
        VendoredModule(ecosystem="cargo", path=tmp_path / "c"),
    ]
    results = run_audits(modules)
    assert len(results) == 3
    assert {r.target.split(":")[0] for r in results} == {"go", "npm", "cargo"}
