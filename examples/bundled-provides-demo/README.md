# bundled-provides demo

Shows the built-in `bundled-provides` post primitive generating an RPM
`Provides: bundled(npm(...))` block from a vendored npm lockfile -- no custom
script, no `${{ }}` expressions.

## Run it

```bash
./setup-demo-repo.sh
gorget --version 1.0.0 \
  --package-dir . \
  --pipeline-file demo.source-pipeline.yaml \
  --output-dir /tmp/gorget-examples/bundled-provides-demo \
  --debug
```

`post:` is skipped under `--dry-run` (it writes into the real `--package-dir`),
so run it for real as above.

## What to look at

After the run, `bundled-npm-provides.inc` is written next to `demo.spec`:

```
Provides:       bundled(npm(is-number)) = 6.0.0
Provides:       bundled(npm(is-odd)) = 3.0.1
```

`jest` is absent -- it's a devDependency and `scope: production` (the default)
drops it. Change the pipeline's `scope:` to `all` and re-run to see it appear.

## Wiring it into a spec

Declare the generated file as a source and `%include` it:

```spec
Source1:        bundled-npm-provides.inc
%include %{S:1}
```

(Left commented in `demo.spec` so the demo runs without a full rpmbuild.)
