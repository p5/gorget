#!/usr/bin/env bash
# Creates demo-repo/: a tiny npm project for the npm pipeline demo.
# Requires `npm` on PATH.
set -euo pipefail
cd "$(dirname "$0")"

rm -rf demo-repo
mkdir demo-repo
cd demo-repo

cat > package.json <<'EOF'
{
  "name": "demo-ui",
  "version": "1.0.0",
  "scripts": {
    "build": "mkdir -p dist && printf '<html><body>hello</body></html>' > dist/index.html"
  }
}
EOF

mkdir -p ui
cat > ui/package.json <<'EOF'
{
  "name": "demo-ui",
  "version": "1.0.0",
  "dependencies": {
    "is-odd": "3.0.1"
  },
  "scripts": {
    "build": "mkdir -p dist && printf '<html><body>hello</body></html>' > dist/index.html"
  }
}
EOF

# Generate lockfile
(cd ui && npm install --package-lock-only --ignore-scripts 2>/dev/null)

git init -q -b main
git config user.email "demo@example.com"
git config user.name "Demo"
git add .
git commit -q -m "initial"

echo "Demo repo created at $(pwd)"
