"""`run` transform step: escape hatch for an arbitrary declared command, with
declared output paths collected as new artifacts afterward. `outputs:` covers
names known upfront; `discovered-outputs:` covers names only known once the
command has run (e.g. a version string it discovered from the source tree).
`artifacts:` materializes already-fetched artifacts' raw bytes into the
step's cwd, e.g. for checksum-verifying one before a later transform step in
the same list mutates it (verify: only runs after all of transform:, so it
can't see pristine bytes once something upstream has already changed them).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from gorget.config.schema import RunStep
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.fetch.base import build_artifact
from gorget.pipeline.state import StageState
from gorget.toolchain import wrap_command
from gorget.transform.base import TransformContext, ensure_source_dir
from gorget.util.archive import repack_tar_gz
from gorget.util.subprocess_run import run


class RunHandler:
    def run(self, step: RunStep, ctx: TransformContext, state: StageState) -> None:
        # Unlike vendor (one fixed, known-ahead-of-time archive name), a
        # `run:` step's declared outputs could each be a file or a directory --
        # which one isn't knowable without actually running the command. So,
        # unlike those steps, dry-run here produces no placeholder artifacts at
        # all rather than guessing.
        if ctx.dry_run:
            return

        source_dir = ensure_source_dir(ctx, state, step.target)
        cwd = source_dir / step.path

        for name in step.artifacts:
            artifact = state.find_artifact(name)
            shutil.copyfile(artifact.path, cwd / name)

        result = run(wrap_command(step.command, ctx.toolchain), cwd=cwd)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"run step ({' '.join(step.command)}) failed in {cwd}: {result.stderr.strip()}"
            )

        for output in step.outputs:
            output_path = cwd / output
            if not output_path.exists():
                raise GorgetConfigError(f"Declared run: output not found: {output_path}")

            name = Path(output).name
            if output_path.is_dir():
                archive_name = f"{name}.tar.gz"
                dest = ctx.work_dir / archive_name
                repack_tar_gz(output_path, dest)
            else:
                archive_name = name
                dest = ctx.work_dir / archive_name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(output_path, dest)

            description = f"run:{' '.join(step.command)}"
            state.artifacts.append(build_artifact(dest, archive_name, description, ctx.dry_run))

        if step.discovered_outputs is not None:
            self._collect_discovered_outputs(step, step.discovered_outputs, cwd, ctx, state)

    def _collect_discovered_outputs(
        self,
        step: RunStep,
        discovered_outputs: str,
        cwd: Path,
        ctx: TransformContext,
        state: StageState,
    ) -> None:
        manifest_path = cwd / discovered_outputs
        if not manifest_path.exists():
            raise GorgetConfigError(f"discovered-outputs manifest not found: {manifest_path}")

        for line_no, raw_line in enumerate(manifest_path.read_text().splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) != 2:
                raise GorgetConfigError(
                    f"{manifest_path} line {line_no}: expected "
                    f"'<output_name>\\t<path>', got {raw_line!r}"
                )
            output_name, rel_path = parts
            src_path = cwd / rel_path
            if not src_path.exists():
                raise GorgetConfigError(
                    f"{manifest_path} line {line_no}: discovered output not found: {src_path}"
                )

            dest = ctx.work_dir / output_name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src_path, dest)

            description = f"run:{' '.join(step.command)} (discovered)"
            state.artifacts.append(build_artifact(dest, output_name, description, ctx.dry_run))
