"""End-of-stage source-tarball repack (`finalize_source_artifact`).

A transform step that edits the shared source tree in place (e.g. vendor-bump)
sets `state.source_dirty`; TransformStage then repacks the backing source
tarball once so it matches what later steps built against.
"""

from __future__ import annotations

import tarfile

from gorget.fetch.base import build_artifact
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.state import StageState
from gorget.transform.base import finalize_source_artifact
from gorget.util.archive import make_tar_gz, repack_tar_gz


def _state(work_dir):
    report = PipelineReport(package="foo", version="1.0.0", old_version=None, dry_run=False)
    return StageState(work_dir=work_dir, spec=None, report=report)


def _members(tar_path):
    with tarfile.open(tar_path) as tar:
        return {m.name for m in tar.getmembers()}


def _read(tar_path, member):
    with tarfile.open(tar_path) as tar:
        return tar.extractfile(member).read().decode()


def test_repacks_git_checkout_rewrapping_arcname(tmp_path):
    # Bare checkout: files at the root, no wrapper dir -- like a git clone.
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "go.mod").write_text("require x v1.0.0\n")
    tarball = tmp_path / "foo-1.0.0.tar.gz"
    make_tar_gz(checkout, tarball, arcname="foo-1.0.0", mtime=1700000000)
    artifact = build_artifact(tarball, "foo-1.0.0.tar.gz", "repo", dry_run=False)
    original_checksum = artifact.checksum

    state = _state(tmp_path)
    state.artifacts.append(artifact)
    state.source_dir = checkout
    state.source_artifact = artifact
    state.source_is_checkout = True

    # A step edits the tree in place and flags it.
    (checkout / "go.mod").write_text("require x v2.0.0\n")
    state.source_dirty = True

    finalize_source_artifact(state, dry_run=False)

    # Repacked, still wrapped under the tarball's original top-level dir.
    assert _read(tarball, "foo-1.0.0/go.mod") == "require x v2.0.0\n"
    assert all(name.startswith("foo-1.0.0") for name in _members(tarball))
    # Artifact replaced with a recomputed checksum, dirty flag cleared.
    assert state.artifacts[0].checksum != original_checksum
    assert state.source_artifact is state.artifacts[0]
    assert state.source_dirty is False


def test_repacks_extracted_tree_as_is(tmp_path):
    # Extracted tarball tree: the wrapper dir is already present.
    extracted = tmp_path / "extracted"
    (extracted / "foo-1.0.0").mkdir(parents=True)
    (extracted / "foo-1.0.0" / "package.json").write_text('{"v": 1}')
    tarball = tmp_path / "foo-1.0.0.tar.gz"
    repack_tar_gz(extracted, tarball)
    artifact = build_artifact(tarball, "foo-1.0.0.tar.gz", "url", dry_run=False)

    state = _state(tmp_path)
    state.artifacts.append(artifact)
    state.source_dir = extracted
    state.source_artifact = artifact
    state.source_is_checkout = False

    (extracted / "foo-1.0.0" / "package.json").write_text('{"v": 2}')
    state.source_dirty = True

    finalize_source_artifact(state, dry_run=False)
    assert _read(tarball, "foo-1.0.0/package.json") == '{"v": 2}'


def test_noop_when_not_dirty(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "f").write_text("a")
    tarball = tmp_path / "foo-1.0.0.tar.gz"
    make_tar_gz(checkout, tarball, arcname="foo-1.0.0", mtime=1700000000)
    before = tarball.read_bytes()
    artifact = build_artifact(tarball, "foo-1.0.0.tar.gz", "repo", dry_run=False)

    state = _state(tmp_path)
    state.artifacts.append(artifact)
    state.source_dir = checkout
    state.source_artifact = artifact
    state.source_is_checkout = True
    # source_dirty stays False

    (checkout / "f").write_text("changed-but-not-flagged")
    finalize_source_artifact(state, dry_run=False)
    assert tarball.read_bytes() == before  # untouched


def test_noop_under_dry_run(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "f").write_text("a")
    tarball = tmp_path / "foo-1.0.0.tar.gz"
    make_tar_gz(checkout, tarball, arcname="foo-1.0.0", mtime=1700000000)
    before = tarball.read_bytes()
    artifact = build_artifact(tarball, "foo-1.0.0.tar.gz", "repo", dry_run=False)

    state = _state(tmp_path)
    state.artifacts.append(artifact)
    state.source_dir = checkout
    state.source_artifact = artifact
    state.source_is_checkout = True
    state.source_dirty = True

    finalize_source_artifact(state, dry_run=True)
    assert tarball.read_bytes() == before


def test_noop_when_no_backing_artifact(tmp_path):
    state = _state(tmp_path)
    state.source_dirty = True
    state.source_artifact = None
    # Must not raise.
    finalize_source_artifact(state, dry_run=False)


def test_repack_is_deterministic(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "go.mod").write_text("require x v2.0.0\n")
    make = lambda p: make_tar_gz(checkout, p, arcname="foo-1.0.0", mtime=1700000000)  # noqa: E731

    def run_once(name):
        tarball = tmp_path / name
        make(tarball)
        artifact = build_artifact(tarball, "foo-1.0.0.tar.gz", "repo", dry_run=False)
        state = _state(tmp_path)
        state.artifacts.append(artifact)
        state.source_dir = checkout
        state.source_artifact = artifact
        state.source_is_checkout = True
        state.source_dirty = True
        finalize_source_artifact(state, dry_run=False)
        return tarball.read_bytes()

    assert run_once("a.tar.gz") == run_once("b.tar.gz")
