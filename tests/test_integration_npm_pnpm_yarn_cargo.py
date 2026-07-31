"""Real integration tests for npm, pnpm, yarn, and cargo vendor steps.

Uses actual package manager binaries — skipped automatically if the
required tool is missing. Each test creates a minimal project, runs
the vendor step through the real PipelineRunner, and verifies the
output archive contains the expected cache/vendor content.

Run just these tests:
    pytest tests/test_integration_npm_pnpm_yarn_cargo.py -v -s
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from gorget.cli import resolve_pipeline_spec
from gorget.context import build_run_context
from gorget.pipeline.runner import PipelineRunner

requires_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="requires git on PATH"
)
requires_npm = pytest.mark.skipif(
    shutil.which("npm") is None, reason="requires npm on PATH"
)
requires_pnpm = pytest.mark.skipif(
    shutil.which("pnpm") is None, reason="requires pnpm on PATH"
)
requires_yarn = pytest.mark.skipif(
    shutil.which("yarn") is None, reason="requires yarn on PATH"
)
requires_cargo = pytest.mark.skipif(
    shutil.which("cargo") is None, reason="requires cargo on PATH"
)


def _run_git(args: list[str], cwd: Path) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def _make_git_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    for name, content in files.items():
        p = repo_dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    _run_git(["init", "-b", "main"], repo_dir)
    _run_git(["config", "user.email", "test@example.com"], repo_dir)
    _run_git(["config", "user.name", "Test"], repo_dir)
    _run_git(["add", "."], repo_dir)
    _run_git(["commit", "-m", "initial"], repo_dir)
    return repo_dir


def _make_ctx(package_dir: Path, output_dir: Path, pipeline_yaml: str):
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "test.spec").write_text("Name: test\nVersion: 1.0.0\nRelease: 1\n")
    pipeline_file = package_dir.parent / "pipeline.yaml"
    pipeline_file.write_text(pipeline_yaml)
    args = argparse.Namespace(
        pkg_version="1.0.0",
        old_version=None,
        dry_run=False,
        package_dir=str(package_dir),
        pipeline_file=str(pipeline_file),
        gpg_keys_dir=str(package_dir.parent / "gpg-keys"),
        output_dir=str(output_dir),
        upstream_repo=None,
    )
    return build_run_context(args)


# --- npm ---


NPM_PACKAGE_JSON = """{
  "name": "test-app",
  "version": "1.0.0",
  "dependencies": {
    "is-odd": "3.0.1"
  }
}
"""

NPM_PIPELINE = """
fetch:
  - type: git
    repo: "{repo}"
    ref: "main"
  - type: vendor
    ecosystem: npm
    archive_name: "test-npm-cache.tar.bz2"
"""


@pytest.mark.integration
@requires_git
@requires_npm
def test_npm_vendor_produces_cache_archive(tmp_path):
    repo = _make_git_repo(tmp_path, {"package.json": NPM_PACKAGE_JSON})
    # Generate lockfile
    subprocess.run(["npm", "install", "--package-lock-only"], cwd=repo, capture_output=True)
    _run_git(["add", "."], repo)
    _run_git(["commit", "-m", "add lockfile"], repo)

    ctx = _make_ctx(
        tmp_path / "pkg", tmp_path / "output",
        NPM_PIPELINE.format(repo=str(repo)),
    )
    spec = resolve_pipeline_spec(ctx)
    report = PipelineRunner(ctx, spec).run()

    stage_status = {s.name: s.status for s in report.stages}
    assert stage_status["fetch"] == "success"

    output_dir = Path(ctx.output_dir)
    archive = output_dir / "test-npm-cache.tar.bz2"
    assert archive.exists()

    with tarfile.open(archive, "r:bz2") as tar:
        names = tar.getnames()
        # npm cache uses _cacache content-addressable store
        assert any("_cacache" in n for n in names), f"No _cacache in archive: {names[:10]}"


# --- pnpm ---


PNPM_PACKAGE_JSON = """{
  "name": "test-app",
  "version": "1.0.0",
  "dependencies": {
    "is-odd": "3.0.1"
  }
}
"""

PNPM_PIPELINE = """
fetch:
  - type: git
    repo: "{repo}"
    ref: "main"
  - type: vendor
    ecosystem: pnpm
    archive_name: "test-pnpm-store.tar.bz2"
"""


@pytest.mark.integration
@requires_git
@requires_pnpm
def test_pnpm_vendor_produces_store_archive(tmp_path):
    repo = _make_git_repo(tmp_path, {"package.json": PNPM_PACKAGE_JSON})
    subprocess.run(["pnpm", "install", "--frozen-lockfile=false"], cwd=repo, capture_output=True)
    _run_git(["add", "."], repo)
    _run_git(["commit", "-m", "add lockfile"], repo)

    ctx = _make_ctx(
        tmp_path / "pkg", tmp_path / "output",
        PNPM_PIPELINE.format(repo=str(repo)),
    )
    spec = resolve_pipeline_spec(ctx)
    report = PipelineRunner(ctx, spec).run()

    stage_status = {s.name: s.status for s in report.stages}
    assert stage_status["fetch"] == "success"

    output_dir = Path(ctx.output_dir)
    archive = output_dir / "test-pnpm-store.tar.bz2"
    assert archive.exists()

    with tarfile.open(archive, "r:bz2") as tar:
        names = tar.getnames()
        assert len(names) > 0, "pnpm store archive is empty"


# --- yarn ---


YARN_PIPELINE = """
fetch:
  - type: git
    repo: "{repo}"
    ref: "main"
  - type: vendor
    ecosystem: yarn
    archive_name: "test-yarn-cache.tar.bz2"
"""


@pytest.mark.integration
@requires_git
@requires_yarn
def test_yarn_vendor_produces_cache_archive(tmp_path):
    repo = _make_git_repo(tmp_path, {"package.json": NPM_PACKAGE_JSON})
    subprocess.run(["yarn", "install"], cwd=repo, capture_output=True)
    _run_git(["add", "."], repo)
    _run_git(["commit", "-m", "add lockfile"], repo)

    ctx = _make_ctx(
        tmp_path / "pkg", tmp_path / "output",
        YARN_PIPELINE.format(repo=str(repo)),
    )
    spec = resolve_pipeline_spec(ctx)
    report = PipelineRunner(ctx, spec).run()

    stage_status = {s.name: s.status for s in report.stages}
    assert stage_status["fetch"] == "success"

    output_dir = Path(ctx.output_dir)
    archive = output_dir / "test-yarn-cache.tar.bz2"
    assert archive.exists()

    with tarfile.open(archive, "r:bz2") as tar:
        names = tar.getnames()
        assert len(names) > 0, "yarn cache archive is empty"


# --- cargo ---


CARGO_TOML = """[package]
name = "test-crate"
version = "0.1.0"
edition = "2021"

[dependencies]
itoa = "1.0.0"
"""

CARGO_PIPELINE = """
fetch:
  - type: git
    repo: "{repo}"
    ref: "main"
  - type: vendor
    ecosystem: cargo
    archive_name: "test-cargo-vendor.tar.bz2"
"""


@pytest.mark.integration
@requires_git
@requires_cargo
def test_cargo_vendor_produces_vendor_archive(tmp_path):
    repo = _make_git_repo(tmp_path, {
        "Cargo.toml": CARGO_TOML,
        "src/lib.rs": "",
    })
    # Generate Cargo.lock
    subprocess.run(["cargo", "generate-lockfile"], cwd=repo, capture_output=True)
    _run_git(["add", "."], repo)
    _run_git(["commit", "-m", "add lockfile"], repo)

    ctx = _make_ctx(
        tmp_path / "pkg", tmp_path / "output",
        CARGO_PIPELINE.format(repo=str(repo)),
    )
    spec = resolve_pipeline_spec(ctx)
    report = PipelineRunner(ctx, spec).run()

    stage_status = {s.name: s.status for s in report.stages}
    assert stage_status["fetch"] == "success"

    output_dir = Path(ctx.output_dir)
    archive = output_dir / "test-cargo-vendor.tar.bz2"
    assert archive.exists()

    with tarfile.open(archive, "r:bz2") as tar:
        names = tar.getnames()
        assert any("itoa" in n for n in names), f"No itoa in cargo vendor: {names[:10]}"
