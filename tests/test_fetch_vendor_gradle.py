import subprocess

import pytest

from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.fetch.vendor.gradle import GradleVendor


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_gradle_vendor_builds_with_project_local_gradle_user_home(tmp_path, mocker):
    (tmp_path / "build.gradle.kts").write_text("plugins { java }")
    mock_run = mocker.patch("gorget.fetch.vendor.gradle.run", return_value=_completed())

    result = GradleVendor().vendor(tmp_path)

    mock_run.assert_called_once_with(
        ["gradle", "--no-daemon", "build"],
        cwd=tmp_path,
        env={"GRADLE_USER_HOME": str(tmp_path / "vendor")},
    )
    assert result == tmp_path / "vendor"


def test_gradle_vendor_uses_wrapper_when_present(tmp_path, mocker):
    (tmp_path / "build.gradle").write_text("plugins { id 'java' }")
    (tmp_path / "gradlew").touch()
    mock_run = mocker.patch("gorget.fetch.vendor.gradle.run", return_value=_completed())

    GradleVendor().vendor(tmp_path)

    assert mock_run.call_args.args[0] == ["./gradlew", "--no-daemon", "build"]


def test_gradle_vendor_runs_configured_task(tmp_path, mocker):
    (tmp_path / "build.gradle").write_text("plugins { id 'java' }")
    mock_run = mocker.patch("gorget.fetch.vendor.gradle.run", return_value=_completed())

    GradleVendor().vendor(tmp_path, task=":distributions-full:binDistributionZip")

    assert mock_run.call_args.args[0] == [
        "gradle",
        "--no-daemon",
        ":distributions-full:binDistributionZip",
    ]


def test_gradle_vendor_rejects_empty_task(tmp_path):
    (tmp_path / "build.gradle").write_text("plugins { id 'java' }")

    with pytest.raises(GorgetConfigError, match="task must not be empty"):
        GradleVendor().vendor(tmp_path, task="  ")


def test_gradle_vendor_removes_transient_cache_files(tmp_path, mocker):
    (tmp_path / "build.gradle").write_text("plugins { id 'java' }")

    def build_cache(*_args, **_kwargs):
        cache = tmp_path / "vendor" / "caches" / "modules-2"
        cache.mkdir(parents=True)
        (cache / "modules-2.lock").write_text("lock")
        (cache / "gc.properties").write_text("gc")
        (cache / "metadata.bin").write_text("dependency metadata")
        return _completed()

    mocker.patch("gorget.fetch.vendor.gradle.run", side_effect=build_cache)

    GradleVendor().vendor(tmp_path)

    assert not (tmp_path / "vendor/caches/modules-2/modules-2.lock").exists()
    assert not (tmp_path / "vendor/caches/modules-2/gc.properties").exists()
    assert (tmp_path / "vendor/caches/modules-2/metadata.bin").exists()


def test_gradle_vendor_requires_gradle_build_file(tmp_path):
    with pytest.raises(GorgetConfigError, match="no build.gradle"):
        GradleVendor().vendor(tmp_path)


def test_gradle_vendor_reports_build_failure(tmp_path, mocker):
    (tmp_path / "build.gradle").write_text("plugins { id 'java' }")
    mocker.patch(
        "gorget.fetch.vendor.gradle.run",
        return_value=_completed(1, stderr="dependency resolution failed"),
    )

    with pytest.raises(GorgetTransientError, match="dependency resolution failed"):
        GradleVendor().vendor(tmp_path)
