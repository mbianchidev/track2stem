#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3.14}"
cd "$ROOT"
PACKAGE_ARGS=()
case "${1:-}" in
  "")
    ;;
  --release-tag)
    if [[ $# -ne 2 ]]; then
      echo "Usage: bash plugin/build.sh [--release-tag vX.Y.Z]" >&2
      exit 2
    fi
    "$PYTHON" plugin/release.py --validate-tag "$2" --check-ref
    PACKAGE_ARGS=(--release-tag "$2")
    ;;
  --help)
    echo "Usage: bash plugin/build.sh [--release-tag vX.Y.Z]"
    exit 0
    ;;
  *)
    echo "Unknown build option: $1" >&2
    exit 2
    ;;
esac
"$PYTHON" plugin/build-runtime.py
(
  cd frontend
  if ! npm ls --depth=0 > /dev/null 2>&1; then
    npm ci
  fi
  npm run build -- --base=./ --outDir ../plugin/build/web --emptyOutDir
)
cmake -S plugin -B plugin/build -DCMAKE_BUILD_TYPE=Release
cmake --build plugin/build --target Track2stem-vst3 Track2stem-au --parallel 4
"$PYTHON" plugin/package.py "${PACKAGE_ARGS[@]+"${PACKAGE_ARGS[@]}"}"
