import subprocess

import pytest

from gorget.config.schema import ToolchainEntry
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.fetch.vendor.maven import MavenVendor


def _completed(returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr=stderr)


def test_maven_vendor_populates_project_local_repository(tmp_path, mocker):
    (tmp_path / "pom.xml").write_text("<project/>")
    mock_run = mocker.patch("gorget.fetch.vendor.maven.run", return_value=_completed())

    result = MavenVendor().vendor(
        tmp_path, [ToolchainEntry(name="maven", version="3.9")]
    )

    assert mock_run.call_args.args[0] == [
        "mvn",
        "dependency:go-offline",
        f"-Dmaven.repo.local={tmp_path / 'vendor'}",
        "-DskipTests",
    ]
    assert mock_run.call_args.kwargs["cwd"] == tmp_path
    assert result == tmp_path / "vendor"


def test_maven_vendor_requires_pom(tmp_path):
    with pytest.raises(GorgetConfigError, match="no pom.xml"):
        MavenVendor().vendor(tmp_path)


def test_maven_vendor_reports_command_failure(tmp_path, mocker):
    (tmp_path / "pom.xml").write_text("<project/>")
    mocker.patch(
        "gorget.fetch.vendor.maven.run", return_value=_completed(1, "resolution failed")
    )
    with pytest.raises(GorgetTransientError, match="resolution failed"):
        MavenVendor().vendor(tmp_path)


def test_maven_vendor_has_no_archive_root_files(tmp_path):
    assert MavenVendor().archive_root_files(tmp_path) == []
