#!/usr/bin/env bash
set -euo pipefail

mkdir -p \
  /workspace/.cache/huggingface \
  /workspace/.cache/torch \
  /workspace/.claude \
  /workspace/.config/anthropic \
  /workspace/run \
  /workspace/scans

# Claude Code releases have used both the traditional ~/.claude location and the newer
# configurable Anthropic directory. Point both at the persistent RunPod volume.
if [[ ! -e /root/.claude ]]; then
  ln -s /workspace/.claude /root/.claude
fi
mkdir -p /root/.config
if [[ ! -e /root/.config/anthropic ]]; then
  ln -s /workspace/.config/anthropic /root/.config/anthropic
fi

exec "$@"

