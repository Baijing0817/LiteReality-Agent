#!/usr/bin/env bash
# Rebuild final exports for an already-authored scene through the public CLI.
set -euo pipefail
cd "$(dirname "$(realpath "$0")")/../.."

scan="${1:?usage: scripts/ops/reexport.sh <scan>}"
exec uv run litereality stage publish "$scan" --force
