"""Real Maven vendor-bump and offline-vendor integration test."""

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

requires_git_and_maven = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("mvn") is None,
    reason="requires git and Maven on PATH",
)


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


@pytest.mark.integration
@requires_git_and_maven
def test_maven_bump_vendor_repack_and_offline_build(tmp_path):
    repo = tmp_path / "upstream"
    repo.mkdir()
    (repo / "pom.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
        "  <modelVersion>4.0.0</modelVersion>\n"
        "  <groupId>org.example</groupId>\n"
        "  <artifactId>maven-integration</artifactId>\n"
        "  <version>1.0.0</version>\n"
        "  <dependencies><dependency>\n"
        "    <groupId>org.apache.commons</groupId>\n"
        "    <artifactId>commons-lang3</artifactId>\n"
        "    <version>3.12.0</version>\n"
        "  </dependency></dependencies>\n"
        "</project>\n"
    )
    for command in (
        ["git", "init", "-b", "main"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test"],
        ["git", "add", "."],
        ["git", "commit", "-m", "initial"],
    ):
        result = _run(command, repo)
        assert result.returncode == 0, result.stderr

    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / "demo.spec").write_text("Name: demo\nVersion: 1.0.0\nRelease: 1\n")
    pipeline_file = tmp_path / "pipeline.yaml"
    pipeline_file.write_text(
        f"""fetch:
  - type: git
    repo: {repo}
    ref: main
transform:
  - type: vendor-bump
    ecosystem: maven
    pins:
      - dependency: org.apache.commons:commons-lang3
        version: 3.14.0
  - type: vendor
    ecosystem: maven
policy:
  vendor-constraints:
    - package: org.apache.commons:commons-lang3
      ecosystem: maven
      version: 3.14.0
      reason: integration test
"""
    )
    output_dir = tmp_path / "output"
    ctx = build_run_context(
        argparse.Namespace(
            pkg_version="1.0.0",
            old_version=None,
            dry_run=False,
            package_dir=str(package_dir),
            pipeline_file=str(pipeline_file),
            gpg_keys_dir=str(tmp_path / "gpg-keys"),
            output_dir=str(output_dir),
            upstream_repo=None,
        )
    )

    report = PipelineRunner(ctx, resolve_pipeline_spec(ctx)).run()
    assert {stage.name: stage.status for stage in report.stages}["emit"] == "success"

    source_archive = output_dir / "demo-1.0.0.tar.gz"
    vendor_archive = output_dir / "demo-vendor.tar.gz"
    with tarfile.open(source_archive) as archive:
        pom_name = next(name for name in archive.getnames() if name.endswith("/pom.xml"))
        assert "<version>3.14.0</version>" in archive.extractfile(pom_name).read().decode()
    with tarfile.open(vendor_archive) as archive:
        assert any(
            name.endswith("commons-lang3/3.14.0/commons-lang3-3.14.0.jar")
            for name in archive.getnames()
        )

    build_dir = tmp_path / "offline-build"
    build_dir.mkdir()
    with tarfile.open(source_archive) as archive:
        archive.extractall(build_dir, filter="data")
    source_root = next(path.parent for path in build_dir.rglob("pom.xml"))
    with tarfile.open(vendor_archive) as archive:
        archive.extractall(source_root, filter="data")
    result = _run(
        ["mvn", "-o", f"-Dmaven.repo.local={source_root / 'vendor'}", "test"],
        source_root,
    )
    assert result.returncode == 0, result.stdout + result.stderr
