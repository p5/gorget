"""`git` fetch step: clone a repo at a ref and archive the checkout (or a subdir).

Shallow (`--depth 1`) clones work cleanly for tag/branch refs. For a SHA-like
ref, a targeted `git init` + `fetch --depth 1 <repo> <sha>` + checkout is
used instead of a full clone: several git hosts (e.g. Google's
googlesource.com mirrors) support fetching an arbitrary commit SHA directly,
even when that commit isn't reachable from any advertised branch tip -- which
a full clone's checkout can't reach at all ("unable to read tree"), and which
a `--filter=blob:none` partial clone can hang on indefinitely, lazily
fetching missing blobs on demand during checkout.

`submodules` controls recursive submodule checkout after the parent is cloned:
"none" skips them, "shallow" fetches each at `--depth 1`, "full" fetches full
submodule history. It is independent of `shallow` (which governs the parent).

Note: "shallow" can fail when a submodule is pinned to a commit that isn't its
remote branch tip and the server won't serve that SHA in a depth-1 fetch (some
self-hosted servers). Use "full" if a project pins submodules that way.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from gorget.config.schema import GitStep
from gorget.exceptions import GorgetTransientError
from gorget.fetch.base import FetchContext, FetchedArtifact, build_artifact
from gorget.util.archive import make_tar_gz, strip_archive_suffix
from gorget.util.git import commit_timestamp
from gorget.util.subprocess_run import run

logger = logging.getLogger("gorget.fetch.git")

_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_SLUG_RE = re.compile(r"[^A-Za-z0-9_.-]+")
# git's own message when `clone --branch <ref>` resolves an annotated tag
# object (as opposed to a lightweight tag or branch, which point directly at
# a commit) -- purely informational, git still resolves and checks out the
# right commit. Surfaced as an explicit note (not silently dropped) since
# --debug relays raw stderr verbatim and this reads as alarming out of
# context.
_BENIGN_ANNOTATED_TAG_RE = re.compile(
    r"^warning: refs/tags/\S+ [0-9a-f]+ is not a commit!$",
    re.MULTILINE,
)


def _looks_like_sha(ref: str) -> bool:
    return bool(_SHA_RE.match(ref))


def _slug(repo_url: str) -> str:
    return _SLUG_RE.sub("_", repo_url).strip("_")


class GitHandler:
    def run(self, step: GitStep, ctx: FetchContext) -> list[FetchedArtifact]:
        archive_name = step.archive_name or f"{ctx.vars.package}-{ctx.vars.version}.tar.gz"
        archive_path = ctx.work_dir / archive_name

        if not ctx.dry_run:
            clone_dir = ctx.work_dir / "_git" / _slug(step.repo)
            self._clone(step, clone_dir)
            if step.submodules != "none":
                self._init_submodules(clone_dir, shallow=step.submodules == "shallow")
            ctx.source_dir = clone_dir
            src = (clone_dir / step.subdir) if step.subdir else clone_dir
            mtime = commit_timestamp(clone_dir)
            # The archive's internal directory is what %setup/%autosetup
            # extracts into, so it must match the archive's own filename, not
            # `ctx.vars.package` (the spec's filename stem, which can legally
            # differ from the archive's actual basename -- e.g. helm4's spec
            # is named helm.spec, or kubernetes1.35's archives are just
            # "kubernetes-*" since that's the upstream repo name, not the
            # RPM's own versioned package name).
            arcname = strip_archive_suffix(archive_name)
            make_tar_gz(src, archive_path, arcname=arcname, mtime=mtime)

        return [build_artifact(archive_path, archive_name, step.repo, ctx.dry_run)]

    def _clone(self, step: GitStep, dest: Path) -> None:
        if step.shallow and not _looks_like_sha(step.ref):
            result = self._run_git(
                [
                    "git", "clone",
                    "--branch", step.ref,
                    "--single-branch",
                    "--depth", "1",
                    step.repo, str(dest),
                ],
                f"git clone --branch {step.ref} failed for {step.repo}",
            )
            self._note_benign_annotated_tag_warning(result, step.ref)
            return

        if step.shallow and _looks_like_sha(step.ref):
            # Previously: `git clone --filter=blob:none` then `git checkout
            # <sha>`. That clone succeeded reliably, but checkout then has to
            # lazily fetch every blob the tree needs on demand, and that
            # on-demand batch fetch was observed to hang indefinitely against
            # gnu.googlesource.com (reproduced across multiple attempts). A
            # plain full clone avoids the hang but can still fail outright:
            # some commits (e.g. gcc's own snapshot pins) aren't reachable
            # from any advertised branch tip at all, so even a full
            # "all branches" clone doesn't have the object -- checkout then
            # fails with "unable to read tree". A targeted shallow fetch of
            # the exact SHA succeeds against this host even when the object
            # isn't reachable from any ref, so init an empty repo and fetch
            # just the one commit instead of cloning anything.
            dest.mkdir(parents=True, exist_ok=True)
            self._run_git(["git", "init", "--quiet", str(dest)], f"git init failed for {dest}")
            self._run_git(
                ["git", "remote", "add", "origin", step.repo],
                f"git remote add failed for {step.repo}",
                cwd=dest,
            )
            self._run_git(
                ["git", "fetch", "--quiet", "--depth", "1", "origin", step.ref],
                f"git fetch {step.ref} failed for {step.repo}",
                cwd=dest,
            )
            self._run_git(
                ["git", "checkout", "--quiet", "FETCH_HEAD"],
                f"git checkout {step.ref} failed",
                cwd=dest,
            )
            return

        clone_args = ["git", "clone", step.repo, str(dest)]
        self._run_git(clone_args, f"git clone failed for {step.repo}")
        self._run_git(["git", "checkout", step.ref], f"git checkout {step.ref} failed", cwd=dest)

    def _note_benign_annotated_tag_warning(
        self, result: subprocess.CompletedProcess, ref: str
    ) -> None:
        if _BENIGN_ANNOTATED_TAG_RE.search(result.stderr):
            logger.info(
                "Note: the \"is not a commit\" warning above is git's own message "
                "for shallow-cloning an annotated tag (%r resolves to a tag object, "
                "not directly a commit) -- git still resolves and checks out the "
                "right commit underneath it. Not an error.",
                ref,
            )

    def _init_submodules(self, dest: Path, *, shallow: bool) -> None:
        args = ["git", "submodule", "update", "--init", "--recursive"]
        if shallow:
            args += ["--depth", "1"]
        self._run_git(args, f"git submodule update failed for {dest}", cwd=dest)

    def _run_git(
        self, args: list[str], error_prefix: str, *, cwd: Path | None = None
    ) -> subprocess.CompletedProcess:
        result = run(args, cwd=cwd)
        if result.returncode != 0:
            raise GorgetTransientError(f"{error_prefix}: {result.stderr.strip()}")
        return result
