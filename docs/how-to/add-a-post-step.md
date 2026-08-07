# How-to: add a `post:` step to refresh generated metadata

Some packages need something in their spec file kept in sync with what was
actually fetched/vendored -- the canonical case is a generated `Provides:`
block listing bundled dependency versions, regenerated on every version
bump. `post:` is the stage for this: it runs last, after Fetch/Transform/
Verify/Policy have all validated the real inputs, and it's the one stage
that's allowed to write into `--package-dir` -- because the whole point is to
land a change in the tracked spec file.

> **Before you write a script:** if you just need a bundled `Provides:` block
> for vendored JS dependencies, use the built-in `bundled-provides` step
> instead -- it parses `package-lock.json`/`pnpm-lock.yaml`/`yarn.lock` and
> writes the `Provides: bundled(npm(...))` lines for you, no script required.
> See [the README's `post:` reference](../../README.md#post). Reach for a
> custom `run` step (below) only when you need something `bundled-provides`
> doesn't cover.
>
> ```yaml
> post:
>   - type: bundled-provides
>     ecosystem: npm
>     modules:
>       - path: "ui"
> ```
>
> Then in the spec: `%include %{S:N}` (matching the `.inc`'s `SourceN:` entry).

## 1. Decide what needs regenerating, and mark it with BEGIN/END markers

A common, simple pattern: wrap the generated block in the spec file with
comment markers a script can find and replace between, leaving everything
else in the file untouched:

```spec
# BEGIN generated bundled Provides
# END generated bundled Provides
```

## 2. If the script needs to read what was fetched, declare it in `artifacts:`

Most real scripts don't just reuse `${VERSION}` (that's already in the spec
via `Version:` -- no `post:` step needed for that); they derive the
generated content from the *fetched tarball itself*, e.g. a bundled
dependency's version read out of a vendored manifest. That tarball isn't
sitting in `--package-dir` when `post:` runs -- it's still in gorget's
internal scratch work dir until Emit (which runs after Post) copies it out.
Name it in `artifacts:` and gorget materializes it into `--package-dir`
under its `output_name` immediately before the command runs:

```yaml
post:
  - type: run
    artifacts: ["${PACKAGE}-${VERSION}.tar.gz"]
    command: ["./refresh-bundled-provides.sh", "${VERSION}"]
```

## 3. Write the script

The script's job is: extract whatever it needs from the materialized
artifact, and rewrite everything between the markers. It runs with
`--package-dir` as its working directory, so both the artifact (from
`artifacts:`) and the spec file are right there to read/write directly:

```bash
#!/bin/sh
# refresh-bundled-provides.sh <version>
set -eu
version="$1"
spec="example.spec"
tarball="example-${version}.tar.gz"

lib_version="$(tar -xOf "$tarball" --wildcards '*/vendor/example-lib/VERSION')"

awk -v version="$lib_version" '
  /# BEGIN generated bundled Provides/ { print; print "Provides: bundled(example-lib) = " version; skip=1; next }
  /# END generated bundled Provides/   { skip=0 }
  !skip
' "$spec" > "$spec.tmp"
mv "$spec.tmp" "$spec"
```

Multiple steps run in declared order if you need more than one script; each
declares its own `artifacts:` independently.

## 4. Know the two things that make `post:` different from `transform: run:`

- **It writes to the real `--package-dir`**, not a scratch copy -- see the
  README's [`post:`](../../README.md#post) reference. Every other stage
  (including `transform: run:`) operates against a temporary working copy
  that's discarded when the pipeline finishes; `post:` is the one place a
  change actually lands where it'll get committed.
- **It's skipped entirely under `--dry-run`** -- on purpose, since dry-run's
  whole point is "touch nothing real." Don't rely on a dry run to validate a
  `post:` script's *output*; validate it by running the script directly
  first (see below), then confirm the pipeline picks it up with a real run.

## 5. Test it

Run the script directly first, against a scratch copy of the spec and the
tarball it needs, before wiring it into the pipeline at all -- this is the
fastest way to iterate:

```bash
cp example.spec example-1.2.3.tar.gz /tmp/
(cd /tmp && /path/to/refresh-bundled-provides.sh 1.2.3)
diff example.spec /tmp/example.spec
```

Once the script itself is right, run the full pipeline for real (not
`--dry-run`, since that skips `post:` entirely) and confirm the spec file in
`--package-dir` was updated as expected:

```bash
gorget --version 1.2.3 \
  --package-dir /path/to/your/package \
  --pipeline-file /path/to/your/package/pipeline.yaml \
  --output-dir /tmp/gorget-output

git -C /path/to/your/package diff example.spec
```
