#!/usr/bin/env bash
# Creates demo-repo/: a tiny upstream checkout with an npm UI project whose
# package-lock.json has both production and dev dependencies. The
# `bundled-provides` post step parses that lockfile and generates the RPM
# `Provides: bundled(npm(...))` block -- no npm install needed, the lockfile
# is committed as-is.
set -euo pipefail
cd "$(dirname "$0")"

rm -rf demo-repo
mkdir demo-repo
cd demo-repo

mkdir -p ui

cat > ui/package.json <<'EOF'
{
  "name": "demo-ui",
  "version": "1.0.0",
  "dependencies": {
    "is-odd": "^3.0.1"
  },
  "devDependencies": {
    "jest": "^29.0.0"
  }
}
EOF

# A minimal lockfileVersion 3 package-lock.json. The parser only needs the
# `packages` map: production deps (is-odd + its transitive is-number) and one
# dev dep (jest, marked "dev": true) so the demo shows scope: production
# dropping devDependencies.
cat > ui/package-lock.json <<'EOF'
{
  "name": "demo-ui",
  "version": "1.0.0",
  "lockfileVersion": 3,
  "requires": true,
  "packages": {
    "": {
      "name": "demo-ui",
      "version": "1.0.0",
      "dependencies": { "is-odd": "^3.0.1" },
      "devDependencies": { "jest": "^29.0.0" }
    },
    "node_modules/is-number": { "version": "6.0.0" },
    "node_modules/is-odd": {
      "version": "3.0.1",
      "dependencies": { "is-number": "^6.0.0" }
    },
    "node_modules/jest": { "version": "29.7.0", "dev": true }
  }
}
EOF

git init -q -b main
git config user.email "demo@example.com"
git config user.name "Demo"
git add .
git commit -q -m "initial"

echo "Demo repo created at $(pwd)"
