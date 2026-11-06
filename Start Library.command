#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
APP="$ROOT/app"
PACKAGES="$APP/runtime/packages"
if curl --silent --fail --max-time 1 http://127.0.0.1:8765/ -o /dev/null; then
  open "http://127.0.0.1:8765"
  exit 0
fi
ARCH="$(uname -m)"
CACHE_ROOT="$HOME/Library/Caches/OfflineFieldLibrary"
case "$ARCH" in
  arm64)
    CACHE="$CACHE_ROOT/arm64"
    PY_ARCHIVE="$PACKAGES/python-macos-arm64.tar.gz"
    KIWIX_ARCHIVE=""
    KIWIX_PATH="$APP/bin/kiwix-serve"
    ;;
  x86_64)
    CACHE="$CACHE_ROOT/x86_64"
    PY_ARCHIVE="$PACKAGES/python-macos-x86_64.tar.gz"
    KIWIX_ARCHIVE="$PACKAGES/kiwix-macos-x86_64.tar.gz"
    KIWIX_PATH="$CACHE/kiwix-tools_macos-x86_64-3.8.2/kiwix-serve"
    ;;
  *)
    osascript -e 'display dialog "This Mac CPU architecture is not included. Use a supported 64-bit Intel or Apple Silicon Mac." buttons {"OK"} with icon caution'
    exit 1
    ;;
esac
mkdir -p "$CACHE"
PYTHON="$CACHE/python/bin/python3.14"
if [[ ! -x "$PYTHON" ]]; then
  if [[ ! -f "$PY_ARCHIVE" ]]; then
    osascript -e 'display dialog "The bundled Python archive is missing from app/runtime/packages." buttons {"OK"} with icon caution'
    exit 1
  fi
  tar -xzf "$PY_ARCHIVE" -C "$CACHE"
fi
if [[ ! -x "$PYTHON" ]]; then
  osascript -e 'display dialog "Could not unpack the bundled Python runtime. Check free space on this Mac." buttons {"OK"} with icon caution'
  exit 1
fi
if [[ -n "$KIWIX_ARCHIVE" && ! -x "$KIWIX_PATH" ]]; then
  tar -xzf "$KIWIX_ARCHIVE" -C "$CACHE"
fi
if ! "$PYTHON" -c 'import sqlite3, http.server' >/dev/null 2>&1; then
  osascript -e 'display dialog "The bundled Python runtime could not start on this version of macOS." buttons {"OK"} with icon caution'
  exit 1
fi
KIWIX=""
if [[ -x "$KIWIX_PATH" ]]; then
  KIWIX="$KIWIX_PATH"
elif command -v kiwix-serve >/dev/null 2>&1; then
  KIWIX="$(command -v kiwix-serve)"
fi
if [[ -n "$KIWIX" ]]; then export PATH="$(dirname "$KIWIX"):$PATH"; fi
APP_PID=""
KIWIX_PID=""
cleanup() {
  [[ -z "$APP_PID" ]] || kill "$APP_PID" 2>/dev/null || true
  [[ -z "$KIWIX_PID" ]] || kill "$KIWIX_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
ZIMS=()
while IFS= read -r -d '' archive; do ZIMS+=("$archive"); done < <(find "$ROOT/content" -type f -iname '*.zim' ! -name '._*' ! -name '.*' -print0)
if [[ -n "$KIWIX" && ${#ZIMS[@]} -gt 0 ]]; then
  "$KIWIX" --address=127.0.0.1 --port=8081 "${ZIMS[@]}" &
  KIWIX_PID=$!
fi
cd "$APP"
"$PYTHON" server.py &
APP_PID=$!
READY=0
for _ in {1..600}; do
  if curl --silent --fail --max-time 1 http://127.0.0.1:8765/ -o /dev/null; then READY=1; break; fi
  if ! kill -0 "$APP_PID" 2>/dev/null; then break; fi
  sleep 0.5
done
if [[ "$READY" -ne 1 ]]; then
  osascript -e 'display dialog "The dashboard did not become ready. Check that port 8765 is available and see app/README.md." buttons {"OK"} with icon caution'
  exit 1
fi
open "http://127.0.0.1:8765" || true
wait "$APP_PID"
