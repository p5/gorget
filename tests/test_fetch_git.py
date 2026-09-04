import subprocess
import tarfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from gorget.config.schema import GitStep
from gorget.config.substitution import SubstitutionVars
from gorget.exceptions import GorgetTransientError
from gorget.fetch.base import FetchContext
from gorget.fetch.git import GitHandler


def make_ctx(work_dir, dry_run=False):
    return FetchContext(
        work_dir=work_dir,
        package_dir=work_dir,
        spec=Mock(),
        vars=SubstitutionVars(
            version="1.2.3", old_version=None, package="foo", spec_file="foo.spec"
        ),
        dry_run=dry_run,
    )


def _ok(stdout=""):
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _fail(stderr="boom"):
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


def _fake_clone(args, cwd=None):
    """Simulate `git clone ... <dest>` by creating a fake checkout on disk."""
    if len(args) >= 2 and args[1] == "clone":
        dest = Path(args[-1])
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "README.md").write_text("hello\n")
        git_dir = dest / ".git"
        git_dir.mkdir(exist_ok=True)
        (git_dir / "config").write_text("")
    return _ok()


def _fake_init_fetch_checkout(args, cwd=None):
    """Simulate `git init <dest>` + `fetch`/`checkout` run with cwd=<dest>,
    the SHA-ref path's targeted-fetch sequence, by creating a fake checkout
    on disk once `git init` runs.
    """
    if len(args) >= 2 and args[1] == "init":
        dest = Path(args[-1])
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "README.md").write_text("hello\n")
        git_dir = dest / ".git"
        git_dir.mkdir(exist_ok=True)
        (git_dir / "config").write_text("")
    return _ok()


def test_shallow_clone_of_tag_uses_branch_and_depth(tmp_path, mocker):
    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    mock_run = mocker.patch("gorget.fetch.git.run", side_effect=_fake_clone)
    step = GitStep(repo="https://example.com/repo.git", ref="v1.2.3", shallow=True)
    artifacts = GitHandler().run(step, make_ctx(tmp_path))

    clone_args = mock_run.call_args_list[0].args[0]
    assert clone_args[:2] == ["git", "clone"]
    assert "--branch" in clone_args and "v1.2.3" in clone_args
    assert "--depth" in clone_args and "1" in clone_args
    assert mock_run.call_count == 1  # branch clone alone checks out the ref, no separate checkout

    # Default output_name uses the bare version, not the ref -- consistent
    # with the archive's internal directory (see
    # test_archive_internal_prefix_uses_bare_version_not_ref below).
    assert artifacts[0].output_name == "foo-1.2.3.tar.gz"
    assert artifacts[0].checksum is not None
    assert (tmp_path / "foo-1.2.3.tar.gz").exists()


def test_shallow_clone_of_sha_ref_uses_targeted_fetch(tmp_path, mocker):
    """A SHA-like ref uses `git init` + `fetch --depth 1 <repo> <sha>` +
    `checkout FETCH_HEAD` instead of a full/partial clone: some git hosts
    (e.g. googlesource.com mirrors) can fetch an arbitrary commit SHA
    directly even when it isn't reachable from any advertised branch tip,
    which neither a full clone (checkout fails: "unable to read tree") nor a
    `--filter=blob:none` partial clone (checkout can hang lazily fetching
    missing blobs) can reliably reach.
    """
    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    mock_run = mocker.patch("gorget.fetch.git.run", side_effect=_fake_init_fetch_checkout)
    step = GitStep(repo="https://example.com/repo.git", ref="abc1234", shallow=True)
    GitHandler().run(step, make_ctx(tmp_path))

    calls = [c.args[0] for c in mock_run.call_args_list]
    assert calls[0][:2] == ["git", "init"]
    assert calls[1] == ["git", "remote", "add", "origin", "https://example.com/repo.git"]
    assert calls[2] == ["git", "fetch", "--quiet", "--depth", "1", "origin", "abc1234"]
    assert calls[3] == ["git", "checkout", "--quiet", "FETCH_HEAD"]
    assert not any("--filter=blob:none" in c for c in calls)


def test_full_clone_performs_explicit_checkout(tmp_path, mocker):
    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    mock_run = mocker.patch("gorget.fetch.git.run", side_effect=_fake_clone)
    step = GitStep(repo="https://example.com/repo.git", ref="main", shallow=False)
    GitHandler().run(step, make_ctx(tmp_path))

    clone_args = mock_run.call_args_list[0].args[0]
    assert clone_args == ["git", "clone", "https://example.com/repo.git", clone_args[-1]]
    assert "--depth" not in clone_args
    assert "--filter=blob:none" not in clone_args
    checkout_args = mock_run.call_args_list[1].args[0]
    assert checkout_args == ["git", "checkout", "main"]


def test_archive_internal_prefix_uses_bare_version_not_ref(tmp_path, mocker):
    """Regression test: the archive's internal top-level directory must match
    RPM's `%{name}-%{version}` convention (no `v` prefix), since that's what
    `%setup`/`%autosetup` extracts into. `step.ref` needs the tag's own prefix
    to check out (e.g. "v1.2.3"), but the archive prefix must come from the
    bare version instead, or the build's %prep fails to find the directory.
    """
    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    mocker.patch("gorget.fetch.git.run", side_effect=_fake_clone)
    step = GitStep(repo="https://example.com/repo.git", ref="v1.2.3", shallow=True)
    artifacts = GitHandler().run(step, make_ctx(tmp_path))

    with tarfile.open(artifacts[0].path) as tar:
        names = tar.getnames()
    assert any(name.startswith("foo-1.2.3/") for name in names)
    assert not any(name.startswith("foo-v1.2.3/") for name in names)


def test_archive_internal_prefix_follows_explicit_archive_name_not_package_var(tmp_path, mocker):
    """Regression test: `ctx.vars.package` (the spec's filename stem) can
    legally differ from an archive's real basename -- e.g. helm4's spec is
    named helm.spec, or kubernetes1.35's upstream tarballs are just
    "kubernetes-*" since that's the plain repo name, not the RPM's own
    versioned package name. The archive's internal directory must follow
    whatever `archive_name` the pipeline actually declares, not `ctx.vars.
    package`, or %setup/%autosetup looks for the wrong directory.
    """
    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    mocker.patch("gorget.fetch.git.run", side_effect=_fake_clone)
    step = GitStep(
        repo="https://example.com/repo.git",
        ref="v1.2.3",
        shallow=True,
        archive_name="helm-1.2.3.tar.gz",
    )
    artifacts = GitHandler().run(step, make_ctx(tmp_path))

    assert artifacts[0].output_name == "helm-1.2.3.tar.gz"
    with tarfile.open(artifacts[0].path) as tar:
        names = tar.getnames()
    assert any(name.startswith("helm-1.2.3/") for name in names)
    assert not any(name.startswith("foo-1.2.3/") for name in names)


def test_archive_excludes_dot_git_directory(tmp_path, mocker):
    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    mocker.patch("gorget.fetch.git.run", side_effect=_fake_clone)
    step = GitStep(repo="https://example.com/repo.git", ref="v1.0.0", shallow=True)
    artifacts = GitHandler().run(step, make_ctx(tmp_path))

    with tarfile.open(artifacts[0].path) as tar:
        names = tar.getnames()
    assert any(name.endswith("README.md") for name in names)
    assert not any(".git" in Path(name).parts for name in names)


def test_archive_members_use_commit_timestamp_not_checkout_time(tmp_path, mocker):
    """Regression test for non-reproducible archives: `tarfile.add()` used to
    preserve each file's live filesystem mtime from the checkout (i.e. wall-clock
    clone time), so re-fetching an unchanged ref produced a different checksum
    every run. Every member should now carry the commit's own timestamp instead.
    """
    mock_commit_timestamp = mocker.patch(
        "gorget.fetch.git.commit_timestamp", return_value=1700000000
    )
    mocker.patch("gorget.fetch.git.run", side_effect=_fake_clone)
    step = GitStep(repo="https://example.com/repo.git", ref="v1.0.0", shallow=True)
    artifacts = GitHandler().run(step, make_ctx(tmp_path))

    mock_commit_timestamp.assert_called_once()
    with tarfile.open(artifacts[0].path) as tar:
        mtimes = {member.mtime for member in tar.getmembers()}
    assert mtimes == {1700000000}


def test_subdir_archives_only_that_subdirectory(tmp_path, mocker):
    def _clone_with_subdir(args, cwd=None):
        _fake_clone(args, cwd)
        if args[1] == "clone":
            dest = Path(args[-1])
            (dest / "sub").mkdir(exist_ok=True)
            (dest / "sub" / "inner.txt").write_text("x")
        return _ok()

    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    mocker.patch("gorget.fetch.git.run", side_effect=_clone_with_subdir)
    step = GitStep(repo="https://example.com/repo.git", ref="v1.0.0", shallow=True, subdir="sub")
    artifacts = GitHandler().run(step, make_ctx(tmp_path))

    with tarfile.open(artifacts[0].path) as tar:
        names = tar.getnames()
    assert any(name.endswith("inner.txt") for name in names)
    assert not any(name.endswith("README.md") for name in names)


def test_clone_failure_raises_transient_error(tmp_path, mocker):
    mocker.patch("gorget.fetch.git.run", return_value=_fail("repository not found"))
    step = GitStep(repo="https://example.com/repo.git", ref="v1.0.0", shallow=True)
    with pytest.raises(GorgetTransientError, match="repository not found"):
        GitHandler().run(step, make_ctx(tmp_path))


def test_checkout_failure_raises_transient_error(tmp_path, mocker):
    def _run(args, cwd=None):
        if args[1] == "clone":
            return _fake_clone(args, cwd)
        return _fail("unknown revision")

    mocker.patch("gorget.fetch.git.run", side_effect=_run)
    step = GitStep(repo="https://example.com/repo.git", ref="deadbeef", shallow=False)
    with pytest.raises(GorgetTransientError, match="unknown revision"):
        GitHandler().run(step, make_ctx(tmp_path))


def test_annotated_tag_warning_gets_a_benign_note(tmp_path, mocker, caplog):
    """git's own `warning: refs/tags/<tag> <hash> is not a commit!` during a
    shallow --branch clone of an annotated tag is purely informational (git
    still resolves and checks out the right commit) -- --debug relays raw
    subprocess stderr verbatim, so without an explicit note this reads as an
    unexplained error to anyone scanning CI logs.
    """

    def _clone_with_tag_warning(args, cwd=None):
        _fake_clone(args, cwd)
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="warning: refs/tags/v1.2.3 abc1234 is not a commit!\n",
        )

    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    mocker.patch("gorget.fetch.git.run", side_effect=_clone_with_tag_warning)
    step = GitStep(repo="https://example.com/repo.git", ref="v1.2.3", shallow=True)
    with caplog.at_level("INFO", logger="gorget.fetch.git"):
        GitHandler().run(step, make_ctx(tmp_path))

    assert any("Not an error" in record.getMessage() for record in caplog.records)


def test_no_benign_note_when_clone_has_no_warning(tmp_path, mocker, caplog):
    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    mocker.patch("gorget.fetch.git.run", side_effect=_fake_clone)
    step = GitStep(repo="https://example.com/repo.git", ref="v1.2.3", shallow=True)
    with caplog.at_level("INFO", logger="gorget.fetch.git"):
        GitHandler().run(step, make_ctx(tmp_path))

    assert not caplog.records


def test_dry_run_skips_clone_entirely(tmp_path, mocker):
    mock_run = mocker.patch("gorget.fetch.git.run")
    step = GitStep(repo="https://example.com/repo.git", ref="v1.0.0", shallow=True)
    artifacts = GitHandler().run(step, make_ctx(tmp_path, dry_run=True))
    mock_run.assert_not_called()
    assert artifacts[0].checksum is None
    assert not artifacts[0].path.exists()


def _submodule_calls(mock_run):
    return [
        c.args[0]
        for c in mock_run.call_args_list
        if len(c.args[0]) >= 2 and c.args[0][:2] == ["git", "submodule"]
    ]


def test_submodules_none_skips_submodule_update(tmp_path, mocker):
    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    mock_run = mocker.patch("gorget.fetch.git.run", side_effect=_fake_clone)
    step = GitStep(repo="https://example.com/repo.git", ref="v1.2.3", shallow=True)
    GitHandler().run(step, make_ctx(tmp_path))
    assert _submodule_calls(mock_run) == []


def test_submodules_shallow_inits_recursively_at_depth_1(tmp_path, mocker):
    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    mock_run = mocker.patch("gorget.fetch.git.run", side_effect=_fake_clone)
    step = GitStep(
        repo="https://example.com/repo.git", ref="v1.2.3", shallow=True, submodules="shallow"
    )
    GitHandler().run(step, make_ctx(tmp_path))

    sub = _submodule_calls(mock_run)
    assert sub == [["git", "submodule", "update", "--init", "--recursive", "--depth", "1"]]
    # submodule update runs inside the clone dir
    sub_call = next(c for c in mock_run.call_args_list if c.args[0][:2] == ["git", "submodule"])
    assert sub_call.kwargs["cwd"] is not None


def test_submodules_full_inits_recursively_without_depth(tmp_path, mocker):
    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    mock_run = mocker.patch("gorget.fetch.git.run", side_effect=_fake_clone)
    step = GitStep(
        repo="https://example.com/repo.git", ref="v1.2.3", shallow=True, submodules="full"
    )
    GitHandler().run(step, make_ctx(tmp_path))

    sub = _submodule_calls(mock_run)
    assert sub == [["git", "submodule", "update", "--init", "--recursive"]]


def test_submodules_init_on_sha_ref_after_checkout(tmp_path, mocker):
    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    mock_run = mocker.patch("gorget.fetch.git.run", side_effect=_fake_clone)
    step = GitStep(
        repo="https://example.com/repo.git", ref="abc1234", shallow=True, submodules="shallow"
    )
    GitHandler().run(step, make_ctx(tmp_path))

    ops = [c.args[0][1] for c in mock_run.call_args_list]
    # Targeted SHA fetch, then checkout, then submodule update, in that order.
    assert ops == ["init", "remote", "fetch", "checkout", "submodule"]


def test_submodule_update_failure_raises_transient_error(tmp_path, mocker):
    def _run(args, cwd=None):
        if args[1] == "submodule":
            return _fail("submodule fetch failed")
        return _fake_clone(args, cwd)

    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    mocker.patch("gorget.fetch.git.run", side_effect=_run)
    step = GitStep(
        repo="https://example.com/repo.git", ref="v1.2.3", shallow=True, submodules="shallow"
    )
    with pytest.raises(GorgetTransientError, match="submodule fetch failed"):
        GitHandler().run(step, make_ctx(tmp_path))
