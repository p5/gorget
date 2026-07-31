import subprocess

import pytest

from gorget.config.schema import VendorPlatform
from gorget.exceptions import GorgetTransientError
from gorget.fetch.vendor.npm import NpmVendor


def _ok(args=None):
    return subprocess.CompletedProcess(args=args or [], returncode=0, stdout="", stderr="")


def _fail(stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


def test_npm_vendor_runs_install_for_each_default_platform(tmp_path, mocker):
    mock_run = mocker.patch("gorget.fetch.vendor.npm.run", return_value=_ok())
    result = NpmVendor().vendor(tmp_path)
    cache_dir = tmp_path / ".npm-cache"
    assert mock_run.call_count == 2
    assert mock_run.call_args_list == [
        mocker.call(
            [
                "npm", "install",
                "--ignore-scripts", "--no-audit", "--no-fund",
                "--cache", str(cache_dir),
                "--cpu", "x64", "--os", "linux", "--libc", "glibc",
            ],
            cwd=tmp_path,
        ),
        mocker.call(
            [
                "npm", "install",
                "--ignore-scripts", "--no-audit", "--no-fund",
                "--cache", str(cache_dir),
                "--cpu", "arm64", "--os", "linux", "--libc", "glibc",
            ],
            cwd=tmp_path,
        ),
    ]
    assert result == cache_dir


def test_npm_vendor_custom_platforms(tmp_path, mocker):
    mock_run = mocker.patch("gorget.fetch.vendor.npm.run", return_value=_ok())
    platforms = [
        VendorPlatform(cpu="s390x", os="linux", libc="glibc"),
    ]
    result = NpmVendor().vendor(tmp_path, platforms=platforms)
    cache_dir = tmp_path / ".npm-cache"
    assert mock_run.call_count == 1
    assert mock_run.call_args_list == [
        mocker.call(
            [
                "npm", "install",
                "--ignore-scripts", "--no-audit", "--no-fund",
                "--cache", str(cache_dir),
                "--cpu", "s390x", "--os", "linux", "--libc", "glibc",
            ],
            cwd=tmp_path,
        ),
    ]
    assert result == cache_dir


def test_npm_vendor_cleans_node_modules_between_iterations(tmp_path, mocker):
    node_modules = tmp_path / "node_modules"

    def create_node_modules(*args, **kwargs):
        """Simulate npm install creating node_modules."""
        node_modules.mkdir(exist_ok=True)
        return _ok()

    mocker.patch("gorget.fetch.vendor.npm.run", side_effect=create_node_modules)
    mock_rmtree = mocker.patch("gorget.fetch.vendor.npm.shutil.rmtree")
    NpmVendor().vendor(tmp_path)
    # rmtree called once per platform (2 defaults)
    assert mock_rmtree.call_count == 2
    mock_rmtree.assert_any_call(node_modules)


def test_npm_vendor_raises_on_failure(tmp_path, mocker):
    mocker.patch(
        "gorget.fetch.vendor.npm.run",
        side_effect=[_ok(), _fail(stderr="ERESOLVE could not resolve")],
    )
    with pytest.raises(
        GorgetTransientError, match="arm64/linux/glibc.*ERESOLVE could not resolve"
    ):
        NpmVendor().vendor(tmp_path)


def test_npm_vendor_creates_cache_dir(tmp_path, mocker):
    mocker.patch("gorget.fetch.vendor.npm.run", return_value=_ok())
    NpmVendor().vendor(tmp_path)
    assert (tmp_path / ".npm-cache").is_dir()
