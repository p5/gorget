import subprocess
from pathlib import Path

import pytest

from gorget.config.schema import VendorPlatform
from gorget.exceptions import GorgetTransientError
from gorget.fetch.vendor.pnpm import PnpmVendor


def _ok(args=None):
    return subprocess.CompletedProcess(args=args or [], returncode=0, stdout="", stderr="")


def _fail(stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


def test_pnpm_vendor_runs_install_per_default_platform(tmp_path, mocker):
    mock_run = mocker.patch("gorget.fetch.vendor.pnpm.run", return_value=_ok())
    result = PnpmVendor().vendor(tmp_path)
    assert mock_run.call_count == 2
    assert mock_run.call_args_list[0] == mocker.call(
        [
            "pnpm", "fetch",
            "--ignore-scripts", "--frozen-lockfile",
            "--store-dir", str(result),
            "--cpu", "x64", "--os", "linux",
        ],
        cwd=tmp_path,
        env={"CI": "true"},
    )
    assert mock_run.call_args_list[1] == mocker.call(
        [
            "pnpm", "fetch",
            "--ignore-scripts", "--frozen-lockfile",
            "--store-dir", str(result),
            "--cpu", "arm64", "--os", "linux",
        ],
        cwd=tmp_path,
        env={"CI": "true"},
    )
    assert result.is_dir()
    assert result.parent != tmp_path
    PnpmVendor().cleanup(result)


def test_pnpm_vendor_with_custom_platforms(tmp_path, mocker):
    mock_run = mocker.patch("gorget.fetch.vendor.pnpm.run", return_value=_ok())
    platforms = [VendorPlatform(cpu="s390x", os="linux", libc="glibc")]
    result = PnpmVendor().vendor(tmp_path, platforms=platforms)
    assert mock_run.call_count == 1
    assert "--cpu" in mock_run.call_args_list[0].args[0]
    assert "s390x" in mock_run.call_args_list[0].args[0]
    PnpmVendor().cleanup(result)


def test_pnpm_vendor_raises_on_failure_and_cleans_workspace(tmp_path, mocker):
    member = tmp_path / "packages" / "web"
    member.mkdir(parents=True)
    store_dirs = []

    def fail_with_output(command, **_kwargs):
        store_dir = command[command.index("--store-dir") + 1]
        store_dirs.append(store_dir)
        (tmp_path / "node_modules").mkdir()
        (member / "node_modules").mkdir()
        return _fail(stderr="ERR_PNPM_OUTDATED")

    mocker.patch("gorget.fetch.vendor.pnpm.run", side_effect=fail_with_output)
    with pytest.raises(GorgetTransientError, match="ERR_PNPM_OUTDATED"):
        PnpmVendor().vendor(tmp_path)
    assert not (tmp_path / "node_modules").exists()
    assert not (member / "node_modules").exists()
    assert all(not Path(path).exists() for path in store_dirs)


def test_pnpm_vendor_cleans_all_workspace_node_modules_and_preserves_upstream(
    tmp_path, mocker
):
    existing = tmp_path / "packages" / "tracked" / "node_modules"
    existing.mkdir(parents=True)
    (existing / "upstream.txt").write_text("keep")

    def install(command, **_kwargs):
        store_dir = Path(command[command.index("--store-dir") + 1])
        (store_dir / "v3" / "files").mkdir(parents=True, exist_ok=True)
        (store_dir / "v3" / "files" / command[-3]).write_text("cached")
        (tmp_path / "node_modules").mkdir(exist_ok=True)
        (tmp_path / "packages" / "a" / "node_modules").mkdir(parents=True, exist_ok=True)
        (existing / "generated.txt").write_text("remove")
        return _ok()

    mocker.patch("gorget.fetch.vendor.pnpm.run", side_effect=install)
    result = PnpmVendor().vendor(tmp_path)

    assert not (tmp_path / "node_modules").exists()
    assert not (tmp_path / "packages" / "a" / "node_modules").exists()
    assert (existing / "upstream.txt").read_text() == "keep"
    assert not (existing / "generated.txt").exists()
    assert any(result.rglob("*"))
    PnpmVendor().cleanup(result)
