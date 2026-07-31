#!/usr/bin/env bash
# Creates demo-repo/: a tiny real Go module with a bit of everything the
# pipeline in this directory exercises -- a dependency pinned to an old
# version (vendor-bump), a docs/ dir that gets stripped from the source
# tarball (strip-tarball), and a minimal npm UI project (build-ui).
set -euo pipefail
cd "$(dirname "$0")"

rm -rf demo-repo
mkdir demo-repo
cd demo-repo

cat > go.mod <<'EOF'
module example.com/demo

go 1.21

require rsc.io/quote v1.0.0
EOF

cat > main.go <<'EOF'
package main

import (
	"fmt"

	"rsc.io/quote"
)

func main() {
	fmt.Println(quote.Hello())
}
EOF

mkdir -p docs
cat > docs/internal-notes.md <<'EOF'
Internal notes that shouldn't ship in the source tarball -- stripped by the
`strip-tarball` transform step.
EOF

mkdir -p ui
cat > ui/package.json <<'EOF'
{
  "name": "demo-ui",
  "version": "1.0.0",
  "scripts": {
    "build": "mkdir -p dist && printf '<html><body>hello</body></html>' > dist/index.html"
  }
}
EOF

git init -q -b main
git config user.email "demo@example.com"
git config user.name "Demo"
git add .
git commit -q -m "initial"

echo "Demo repo created at $(pwd)"

if command -v go >/dev/null; then
  installed_go=$(go version | grep -oE 'go[0-9]+\.[0-9]+\.[0-9]+' | sed 's/^go//')
  echo ""
  echo "Detected installed go version: ${installed_go}"
  echo "To try the toolchain: section in demo.source-pipeline.yaml (see its"
  echo "bottom and README.md section 4), use this version -- e.g.:"
  echo "    toolchain:"
  echo "      - name: go"
  echo "        version: ${installed_go}"
fi
