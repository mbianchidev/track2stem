#!/bin/bash
set -euo pipefail

PACKAGE="$(cd "$(dirname "$0")" && pwd)"
RUNTIME="$PACKAGE/Runtime/track2stem-worker"
if [ ! -x "$RUNTIME" ]; then
  printf '%s\n' "The Track2stem runtime is missing. Extract the complete package before installing." >&2
  exit 1
fi
printf '%s\n' "Close your DAW before installing. Existing installations are never overwritten."
"$RUNTIME" --install "$PACKAGE"
