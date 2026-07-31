import subprocess

import pytest

from gorget.exceptions import GorgetTransientError
from gorget.fetch.vendor.pnpm import PnpmVendor


def _ok(args=None):
    return subprocess.CompletedProcess(args=args or [], returncode=0, stdout="", stderr="")


def _fail(stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


def test_pnpm_vendor_runs_fetch_with_store_dir(tmp_path, mocker):
    mock_run = mocker.patch("gorget.fetch.vendor.pnpm.run", return_value=_ok())
    store_dir = tmp_path / ".pnpm-store"
    result = PnpmVendor().vendor(tmp_path)
    assert mock_run.call_count == 1
    assert mock_run.call_args_list == [
        mocker.call(
            [
                "pnpm", "fetch",
                "--frozen-lockfile",
                "--store-dir", str(store_dir),
            ],
            cwd=tmp_path,
            env={"CI": "true"},
        ),
    ]
    assert result == store_dir


def test_pnpm_vendor_raises_on_failure(tmp_path, mocker):
    mocker.patch("gorget.fetch.vendor.pnpm.run", return_value=_fail(stderr="ERR_PNPM_OUTDATED"))
    with pytest.raises(GorgetTransientError, match="ERR_PNPM_OUTDATED"):
        PnpmVendor().vendor(tmp_path)


def test_pnpm_vendor_creates_store_dir(tmp_path, mocker):
    mocker.patch("gorget.fetch.vendor.pnpm.run", return_value=_ok())
    PnpmVendor().vendor(tmp_path)
    assert (tmp_path / ".pnpm-store").is_dir()
