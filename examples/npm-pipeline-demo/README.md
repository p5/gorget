# npm Pipeline Demo

Demonstrates gorget's npm vendor pipeline features:

1. **Multi-arch npm cache** — `type: vendor, ecosystem: npm` produces an offline
   npm cache tarball with packages for both x86_64 and aarch64 (configurable via
   `platforms:`).

2. **Step IDs and `${{ }}` expressions** — the vendor step declares `id: ui-deps`
   and `bundled_provides: true`. Downstream steps reference its outputs with
   `${{ steps.ui-deps.bundled_provides.production }}`.

3. **vendor-bump with skip-if-satisfied** — bumps a dependency to a minimum
   version, but skips the bump if the lockfile already satisfies the constraint.

4. **bundled-provides post step** — reads the dependency list from the vendor
   step's output and writes `bundled-npm-provides.inc`, a file of RPM `Provides:`
   lines imported by the spec with `%include %{S:N}`.

## Running the demo

```bash
# 1. Create the demo git repo (requires npm)
./setup-demo-repo.sh

# 2. Run the pipeline
gorget \
  --version 1.0.0 \
  --package-dir . \
  --pipeline-file demo.source-pipeline.yaml \
  --output-dir ./output \
  --debug

# 3. Inspect the output
ls output/
cat bundled-npm-provides.inc
```

## Pipeline YAML walkthrough

See `demo.source-pipeline.yaml` for inline comments explaining each step.

## Custom platforms

By default, npm/pnpm vendors fetch for x64 + arm64 on linux/glibc. Override
with `platforms:`:

```yaml
- type: vendor
  ecosystem: npm
  platforms:
    - {cpu: x64, os: linux, libc: glibc}
    - {cpu: arm64, os: linux, libc: glibc}
    - {cpu: s390x, os: linux, libc: glibc}
```

## pnpm and yarn

Replace `ecosystem: npm` with `pnpm` or `yarn`. The vendor step handles
multi-arch automatically:

- **npm**: loops `--cpu`/`--os`/`--libc` per platform
- **pnpm**: loops `--cpu`/`--os` per platform
- **yarn**: writes `supportedArchitectures` to `.yarnrc.yml` (yarn v4), yarn v1
  caches all platforms automatically
