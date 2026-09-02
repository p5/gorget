"""`audit`: run each ecosystem's own integrity/vulnerability check against every
vendored module.

`go mod verify` checks module cache checksums against `go.sum` -- deterministic,
no network -- so a failure fails closed. `npm audit`/`cargo audit` query live
vulnerability databases over the network: results can change with no code change,
the same category of non-determinism that got `mise` rejected for toolchain
activation (HUM-4990). They're warn-only -- findings are recorded, but never raise.
"""

from __future__ import annotations

import json
import shutil

from gorget.exceptions import GorgetConfigError
from gorget.policy.base import CheckResult, VendoredModule
from gorget.util.subprocess_run import run


def _go_mod_verify(module: VendoredModule) -> CheckResult:
    result = run(["go", "mod", "verify"], cwd=module.path)
    if result.returncode != 0:
        return CheckResult(
            type="audit",
            target=f"go:{module.path}",
            status="failed",
            reason=(result.stderr or result.stdout).strip(),
        )
    return CheckResult(type="audit", target=f"go:{module.path}", status="passed")


def _summarize_npm_audit(stdout: str) -> str:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout.strip()
    vulnerabilities = data.get("metadata", {}).get("vulnerabilities", {})
    total = sum(count for count in vulnerabilities.values() if isinstance(count, int))
    if total:
        return f"{total} vulnerabilit{'y' if total == 1 else 'ies'} found: {vulnerabilities}"
    return stdout.strip()


def _npm_audit(module: VendoredModule) -> CheckResult:
    # npm audit exits nonzero when vulnerabilities are found -- that's the
    # expected signal, not a tool failure. Warn-only: never raise on it.
    result = run(["npm", "audit", "--json"], cwd=module.path)
    if result.returncode != 0:
        return CheckResult(
            type="audit",
            target=f"npm:{module.path}",
            status="warning",
            reason=_summarize_npm_audit(result.stdout),
        )
    return CheckResult(type="audit", target=f"npm:{module.path}", status="passed")


def _cargo_audit(module: VendoredModule) -> CheckResult:
    if shutil.which("cargo-audit") is None:
        raise GorgetConfigError(
            "policy audit requires 'cargo-audit' on PATH for Cargo packages "
            "(https://github.com/rustsec/rustsec/tree/main/cargo-audit)"
        )
    result = run(["cargo", "audit"], cwd=module.path)
    if result.returncode != 0:
        return CheckResult(
            type="audit",
            target=f"cargo:{module.path}",
            status="warning",
            reason=(result.stdout or result.stderr).strip(),
        )
    return CheckResult(type="audit", target=f"cargo:{module.path}", status="passed")


def _maven_audit(module: VendoredModule) -> CheckResult:
    cmd = [
        "mvn",
        "org.owasp:dependency-check-maven:13.0.0:check",
        "-DfailBuildOnCVSS=0",
        "-DnvdApiKeyEnvironmentVariable=NVD_API_KEY",
    ]
    result = run(cmd, cwd=module.path)
    if result.returncode != 0:
        return CheckResult(
            type="audit",
            target=f"maven:{module.path}",
            status="warning",
            reason=(result.stdout or result.stderr).strip(),
        )
    return CheckResult(type="audit", target=f"maven:{module.path}", status="passed")


_AUDITORS = {
    "go": _go_mod_verify,
    "npm": _npm_audit,
    "cargo": _cargo_audit,
    "maven": _maven_audit,
}


def run_audits(modules: list[VendoredModule]) -> list[CheckResult]:
    return [_AUDITORS[module.ecosystem](module) for module in modules]
