# Example: full Transform stage pipeline (Go)

Runnable, non-pytest example exercising every Transform step type gorget has,
chained into one pipeline against a real Go module fetched from a local git
repo:

| Step | What it does here |
|---|---|
| `fetch: git` | Clones `demo-repo/` |
| `transform: strip-tarball` | Removes `docs/` from the source tarball |
| `transform: vendor-bump` | Bumps `rsc.io/quote` from `v1.0.0` to `v1.5.2` |
| `transform: vendor` | Vendors the now-bumped dependency (reused from `fetch:`) |
| `transform: build-ui` | Runs `npm run build` in `ui/`, archives `dist/` |
| `transform: run` | Escape hatch: runs `go version`, archives the output file |

Requires `git`, `go`, and `npm` on `PATH`, plus network access to
`proxy.golang.org`.

## 1. Set up the demo repo (once)

```bash
./setup-demo-repo.sh
```

Creates `demo-repo/`: a tiny real Go module pinned to an old
`rsc.io/quote v1.0.0`, a `docs/` dir to be stripped, and a minimal `ui/` npm
project for `build-ui`.

## 2. Run gorget

```bash
cd examples/go-pipeline-demo   # relative paths in the pipeline YAML resolve from here
source ../../.venv/bin/activate  # skip if gorget is already installed/on PATH

gorget --version 1.0.0 \
  --package-dir . \
  --pipeline-file demo.source-pipeline.yaml \
  --output-dir /tmp/gorget-demo-output
```

## 3. Inspect the result

```bash
ls /tmp/gorget-demo-output

# strip-tarball: docs/ is gone from the source tarball
tar tzf /tmp/gorget-demo-output/demo-main.tar.gz | grep docs   # <- prints nothing

# vendor-bump + vendor: rsc.io/quote bumped and actually vendored
tar tzf /tmp/gorget-demo-output/demo-vendor.tar.gz | grep quote

# build-ui: the built dist/ output, archived
tar tzf /tmp/gorget-demo-output/demo-ui-assets.tar.gz

# run: the escape-hatch command's declared output, archived verbatim
cat /tmp/gorget-demo-output/go-version.txt

# every stage's status + every artifact's checksum
cat /tmp/gorget-demo-output/report.json
```

Re-run `./setup-demo-repo.sh` to reset `demo-repo/` back to its original
state before trying again.

## 4. `toolchain:` -- validates, doesn't fetch or switch

`demo.source-pipeline.yaml` has a commented-out `toolchain:` section at the
bottom. `setup-demo-repo.sh` prints your machine's actual installed `go`
version -- uncomment the section and paste that value in:

```yaml
toolchain:
  - name: go
    version: 1.25.10   # <- whatever setup-demo-repo.sh printed for you
```

Re-run step 2 and it passes: gorget checks the declared version against
whatever's already installed (`go version`) and matches component-wise, so
`1.25` matches an installed `1.25.10`. Change `version:` to something that
doesn't match (e.g. `1.22.0`) and it fails closed instead, before any stage
runs (even under `--dry-run`):

```
error: Required toolchain go@1.22.0 does not match the installed version
(1.25.10). gorget validates against whatever is already installed -- it
doesn't fetch or switch toolchain versions (see HUM-4990/HUM-4789).
```

That's the whole feature right now: a safety check against the ambient
environment, nothing more. An earlier design shelled out to `mise` to
actually *activate* arbitrary versions, but that was rejected as a
supply-chain trust violation (mise downloads toolchain binaries from their
own upstream release channels at runtime) -- see HUM-4990/HUM-4789 for the
real multi-version mechanism this will eventually grow into. Comment the
section back out (or match your real version) to get a working pipeline.
