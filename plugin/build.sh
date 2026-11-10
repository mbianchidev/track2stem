#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3.14}"
cd "$ROOT"
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
"$PYTHON" plugin/package.py
