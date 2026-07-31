import subprocess

import pytest

from gorget.exceptions import GorgetTransientError
from gorget.fetch.vendor.yarn import YarnVendor


def _ok(args=None):
    return subprocess.CompletedProcess(args=args or [], returncode=0, stdout="", stderr="")


def _fail(stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


def test_yarn_vendor_runs_install_with_cache_folder(tmp_path, mocker):
    mock_run = mocker.patch("gorget.fetch.vendor.yarn.run", return_value=_ok())
    cache_dir = tmp_path / ".yarn-cache"
    result = YarnVendor().vendor(tmp_path)
    assert mock_run.call_count == 1
    assert mock_run.call_args_list == [
        mocker.call(
            [
                "yarn", "install",
                "--frozen-lockfile",
                "--cache-folder", str(cache_dir),
            ],
            cwd=tmp_path,
        ),
    ]
    assert result == cache_dir


def test_yarn_vendor_cleans_node_modules(tmp_path, mocker):
    node_modules = tmp_path / "node_modules"

    def create_node_modules(*args, **kwargs):
        """Simulate yarn install creating node_modules."""
        node_modules.mkdir(exist_ok=True)
        return _ok()

    mocker.patch("gorget.fetch.vendor.yarn.run", side_effect=create_node_modules)
    mock_rmtree = mocker.patch("gorget.fetch.vendor.yarn.shutil.rmtree")
    YarnVendor().vendor(tmp_path)
    assert mock_rmtree.call_count == 1
    mock_rmtree.assert_called_once_with(node_modules)


def test_yarn_vendor_raises_on_failure(tmp_path, mocker):
    mocker.patch(
        "gorget.fetch.vendor.yarn.run",
        return_value=_fail(stderr="error Couldn't find a package.json"),
    )
    with pytest.raises(GorgetTransientError, match="Couldn't find a package.json"):
        YarnVendor().vendor(tmp_path)


def test_yarn_vendor_creates_cache_dir(tmp_path, mocker):
    mocker.patch("gorget.fetch.vendor.yarn.run", return_value=_ok())
    YarnVendor().vendor(tmp_path)
    assert (tmp_path / ".yarn-cache").is_dir()
