import json

import pytest

from gorget.config.schema import (
    BundledProvidesStep,
    PipelineSpec,
    PostRunStep,
    PostSection,
    VendorModule,
)
from gorget.config.substitution import SubstitutionVars
from gorget.context import RunContext
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.fetch.base import FetchedArtifact
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.stages.post import PostStage
from gorget.pipeline.state import StageState


def make_ctx(package_dir, dry_run=False):
    return RunContext(
        package_dir=package_dir,
        pipeline_file=package_dir / "pipeline.yaml",
        gpg_keys_dir=package_dir / "gpg-keys",
        output_dir=package_dir / "output",
        dry_run=dry_run,
        spec_path=package_dir / "foo.spec",
        vars=SubstitutionVars(
            version="1.2.3", old_version=None, package="foo", spec_file="foo.spec"
        ),
    )


def make_state(work_dir):
    report = PipelineReport(package="foo", version="1.2.3", old_version=None, dry_run=False)
    return StageState(work_dir=work_dir, spec=None, report=report)


def test_no_post_steps_skips(tmp_path):
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    result = PostStage().run(ctx, PipelineSpec(), state)
    assert result.status == "skipped"
    assert result.reason == "no post steps declared"


def test_dry_run_skips_even_with_steps_declared(tmp_path):
    ctx = make_ctx(tmp_path, dry_run=True)
    state = make_state(tmp_path)
    spec = PipelineSpec(
        post=PostSection(steps=[PostRunStep(command=["touch", "should-not-exist"])])
    )
    result = PostStage().run(ctx, spec, state)
    assert result.status == "skipped"
    assert result.reason == "dry-run"
    assert not (tmp_path / "should-not-exist").exists()


def test_run_step_executes_with_package_dir_as_cwd(tmp_path):
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    spec = PipelineSpec(
        post=PostSection(steps=[PostRunStep(command=["sh", "-c", "echo hi > post-output.txt"])])
    )
    result = PostStage().run(ctx, spec, state)
    assert result.status == "success"
    assert (tmp_path / "post-output.txt").read_text() == "hi\n"


def test_multiple_steps_run_in_declared_order(tmp_path):
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    spec = PipelineSpec(
        post=PostSection(
            steps=[
                PostRunStep(command=["sh", "-c", "echo one >> order.txt"]),
                PostRunStep(command=["sh", "-c", "echo two >> order.txt"]),
            ]
        )
    )
    PostStage().run(ctx, spec, state)
    assert (tmp_path / "order.txt").read_text() == "one\ntwo\n"


def test_failing_step_raises_transient_error(tmp_path):
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    spec = PipelineSpec(
        post=PostSection(steps=[PostRunStep(command=["sh", "-c", "echo boom >&2; exit 1"])])
    )
    with pytest.raises(GorgetTransientError, match="boom"):
        PostStage().run(ctx, spec, state)


def test_declared_artifact_is_materialized_into_package_dir_before_command_runs(tmp_path):
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()
    fetched = scratch_dir / "foo-1.2.3.tar.gz"
    fetched.write_text("fake tarball bytes")

    ctx = make_ctx(package_dir)
    state = make_state(scratch_dir)
    state.artifacts.append(
        FetchedArtifact(
            path=fetched,
            output_name="foo-1.2.3.tar.gz",
            source_description="test",
            checksum=None,
        )
    )
    spec = PipelineSpec(
        post=PostSection(
            steps=[
                PostRunStep(
                    artifacts=["foo-1.2.3.tar.gz"],
                    command=["sh", "-c", "cat foo-1.2.3.tar.gz > read-output.txt"],
                )
            ]
        )
    )

    result = PostStage().run(ctx, spec, state)

    assert result.status == "success"
    assert (package_dir / "foo-1.2.3.tar.gz").read_text() == "fake tarball bytes"
    assert (package_dir / "read-output.txt").read_text() == "fake tarball bytes"


def test_unknown_artifact_name_raises_config_error(tmp_path):
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    spec = PipelineSpec(
        post=PostSection(steps=[PostRunStep(artifacts=["does-not-exist.tar.gz"], command=["true"])])
    )
    with pytest.raises(GorgetConfigError, match="does-not-exist.tar.gz"):
        PostStage().run(ctx, spec, state)


# -- bundled-provides --

def _write_npm_lock(source_dir, module_path, packages):
    module_dir = source_dir / module_path
    module_dir.mkdir(parents=True, exist_ok=True)
    (module_dir / "package-lock.json").write_text(json.dumps({"packages": packages}))


def test_bundled_provides_writes_inc_file(tmp_path):
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    _write_npm_lock(source_dir, "ui", {
        "node_modules/lodash": {"version": "4.17.21"},
        "node_modules/react": {"version": "18.2.0"},
        "node_modules/jest": {"version": "29.0.0", "dev": True},
    })

    ctx = make_ctx(package_dir)
    state = make_state(tmp_path)
    state.source_dir = source_dir
    spec = PipelineSpec(
        post=PostSection(
            steps=[BundledProvidesStep(ecosystem="npm", modules=[VendorModule(path="ui")])]
        )
    )

    result = PostStage().run(ctx, spec, state)

    assert result.status == "success"
    content = (package_dir / "bundled-npm-provides.inc").read_text()
    assert "Provides:       bundled(npm(lodash)) = 4.17.21" in content
    assert "Provides:       bundled(npm(react)) = 18.2.0" in content
    # scope defaults to production -- dev deps excluded
    assert "jest" not in content
    # sorted by name
    assert content.index("lodash") < content.index("react")


def test_bundled_provides_scope_all_includes_dev(tmp_path):
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    _write_npm_lock(source_dir, ".", {
        "node_modules/lodash": {"version": "4.17.21"},
        "node_modules/jest": {"version": "29.0.0", "dev": True},
    })

    ctx = make_ctx(package_dir)
    state = make_state(tmp_path)
    state.source_dir = source_dir
    spec = PipelineSpec(
        post=PostSection(steps=[BundledProvidesStep(ecosystem="npm", scope="all")])
    )

    PostStage().run(ctx, spec, state)
    content = (package_dir / "bundled-npm-provides.inc").read_text()
    assert "bundled(npm(jest)) = 29.0.0" in content
    assert "bundled(npm(lodash)) = 4.17.21" in content


def test_bundled_provides_output_override_and_rpm_version(tmp_path):
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    _write_npm_lock(source_dir, ".", {
        "node_modules/next": {"version": "14.0.0-rc.1"},
    })

    ctx = make_ctx(package_dir)
    state = make_state(tmp_path)
    state.source_dir = source_dir
    spec = PipelineSpec(
        post=PostSection(
            steps=[BundledProvidesStep(ecosystem="npm", output="provides.inc")]
        )
    )

    PostStage().run(ctx, spec, state)
    content = (package_dir / "provides.inc").read_text()
    # semver prerelease '-' -> rpm '~'
    assert "Provides:       bundled(npm(next)) = 14.0.0~rc.1" in content


def test_bundled_provides_without_source_dir_raises(tmp_path):
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)  # source_dir defaults to None
    spec = PipelineSpec(
        post=PostSection(steps=[BundledProvidesStep(ecosystem="npm")])
    )
    with pytest.raises(GorgetTransientError, match="source checkout"):
        PostStage().run(ctx, spec, state)
