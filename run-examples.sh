#!/usr/bin/env bash
# Runs every example under examples/ in one shot: sets up the venv if needed,
# runs each demo's setup script where one exists, then runs gorget against
# each pipeline YAML with the same command shown in that example's README.
#
# Requires: rpmspec, gpg, git, go, npm, cargo on PATH, plus network access
# (real fetches/vendoring -- these are not mocked, same as the examples
# themselves).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "==> Creating .venv"
  python3 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -e ".[dev]"
else
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

run_demo() {
  local name="$1"
  echo
  echo "=================================================================="
  echo "==> ${name}"
  echo "=================================================================="
}

run_demo "spec-source-demo"
(
  cd examples/spec-source-demo
  gorget --version 2.12.1 \
    --package-dir . \
    --pipeline-file hello.source-pipeline.yaml \
    --output-dir /tmp/gorget-examples/spec-source-demo \
    --debug
)

run_demo "go-pipeline-demo"
(
  cd examples/go-pipeline-demo
  ./setup-demo-repo.sh
  gorget --version 1.0.0 \
    --package-dir . \
    --pipeline-file demo.source-pipeline.yaml \
    --output-dir /tmp/gorget-examples/go-pipeline-demo \
    --debug
)

run_demo "native-cargo-demo"
(
  cd examples/native-cargo-demo
  ./setup-demo-repo.sh
  gorget --version 1.0.0 \
    --package-dir . \
    --pipeline-file demo.source-pipeline.yaml \
    --output-dir /tmp/gorget-examples/native-cargo-demo \
    --debug
)

run_demo "bundled-provides-demo"
(
  cd examples/bundled-provides-demo
  ./setup-demo-repo.sh
  gorget --version 1.0.0 \
    --package-dir . \
    --pipeline-file demo.source-pipeline.yaml \
    --output-dir /tmp/gorget-examples/bundled-provides-demo \
    --debug
  echo "--- generated bundled-npm-provides.inc ---"
  cat bundled-npm-provides.inc
)

run_demo "verify-demo"
(
  cd examples/verify-demo
  gorget --version 2.12.1 \
    --package-dir . \
    --pipeline-file hello.source-pipeline.yaml \
    --gpg-keys-dir gpg-keys \
    --output-dir /tmp/gorget-examples/verify-demo \
    --debug
)

run_demo "policy-demo"
(
  cd examples/policy-demo
  ./setup-demo-repo.sh
  gorget --version 1.0.0 \
    --package-dir . \
    --pipeline-file demo.source-pipeline.yaml \
    --output-dir /tmp/gorget-examples/policy-demo \
    --debug
)

run_demo "full-pipeline-demo"
(
  cd examples/full-pipeline-demo
  ./setup-demo-repo.sh
  gorget --version 1.0.0 \
    --package-dir . \
    --pipeline-file demo.source-pipeline.yaml \
    --gpg-keys-dir gpg-keys \
    --output-dir /tmp/gorget-examples/full-pipeline-demo \
    --debug
)

run_demo "emit-on-failure-demo"
(
  # This demo is deliberately broken -- it's meant to exit non-zero. Assert
  # that explicitly (exit 1 + report.json present) rather than letting the
  # outer `set -e` just stop the whole script on an "unexpected" failure.
  cd examples/emit-on-failure-demo
  set +e
  gorget --version 2.12.1 \
    --package-dir . \
    --pipeline-file demo.source-pipeline.yaml \
    --output-dir /tmp/gorget-examples/emit-on-failure-demo \
    --debug
  status=$?
  set -e
  if [ "$status" -ne 1 ]; then
    echo "expected exit code 1, got ${status}" >&2
    exit 1
  fi
  if [ ! -f /tmp/gorget-examples/emit-on-failure-demo/report.json ]; then
    echo "expected report.json to exist despite the failure" >&2
    exit 1
  fi
  echo "Confirmed: exit code 1, report.json written despite the failure."
)

echo
echo "=================================================================="
echo "All examples ran successfully. Output dirs under /tmp/gorget-examples/"
echo "=================================================================="
