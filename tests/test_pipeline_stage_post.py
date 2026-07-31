import pytest

from gorget.config.schema import BundledProvidesStep, PipelineSpec, PostRunStep, PostSection
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


def test_bundled_provides_writes_inc_file(tmp_path):
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    # Simulate step outputs from a vendor step
    state.set_step_output("npm-vendor", "bundled_provides", {
        "production": [("lodash", "4.17.21"), ("react", "18.2.0")],
    })
    spec = PipelineSpec(
        post=PostSection(steps=[
            BundledProvidesStep(
                id="gen-provides",
                input="${{ steps.npm-vendor.bundled_provides.production }}",
            )
        ])
    )
    result = PostStage().run(ctx, spec, state)
    assert result.status == "success"

    inc_file = tmp_path / "bundled-npm-provides.inc"
    assert inc_file.exists()
    content = inc_file.read_text()
    assert "Provides:       bundled(npm(lodash)) = 4.17.21" in content
    assert "Provides:       bundled(npm(react)) = 18.2.0" in content


def test_bundled_provides_rpm_version_conversion(tmp_path):
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    state.set_step_output("npm-vendor", "bundled_provides", {
        "production": [("pkg", "1.0.0-beta.1")],
    })
    spec = PipelineSpec(
        post=PostSection(steps=[
            BundledProvidesStep(
                input="${{ steps.npm-vendor.bundled_provides.production }}",
            )
        ])
    )
    PostStage().run(ctx, spec, state)
    content = (tmp_path / "bundled-npm-provides.inc").read_text()
    # Pre-release "1.0.0-beta.1" -> "1.0.0~beta.1" in RPM
    assert "1.0.0~beta.1" in content


def test_bundled_provides_non_list_input_raises(tmp_path):
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    state.set_step_output("npm-vendor", "version", "1.0.0")
    spec = PipelineSpec(
        post=PostSection(steps=[
            BundledProvidesStep(
                input="${{ steps.npm-vendor.version }}",
            )
        ])
    )
    with pytest.raises(GorgetTransientError, match="must resolve to a list"):
        PostStage().run(ctx, spec, state)
