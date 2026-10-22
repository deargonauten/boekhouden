#!/usr/bin/env bash
# Builds app/web/static/tailwind.css with the Tailwind standalone CLI (no Node). Pass --watch while developing.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
TW=tools/tailwindcss
if [ ! -x "$TW" ]; then
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) asset=macos-arm64 ;; Darwin-x86_64) asset=macos-x64 ;;
    Linux-aarch64) asset=linux-arm64 ;; *) asset=linux-x64 ;;
  esac
  curl -fsSL -o "$TW" "https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-$asset"
  chmod +x "$TW"
fi
"$TW" -i app/web/static/src/tailwind.css -o app/web/static/tailwind.css --minify "$@"
