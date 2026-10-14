#!/usr/bin/env bash
# Explicit C3U root request over an authorized ADB shell.
# Does not install, flash, automatically retry exploits, or change system settings.
set -euo pipefail

if ! command -v adb >/dev/null; then echo 'adb not found' >&2; exit 2; fi

if [[ "${1:-}" == "--launch-only" ]]; then
  echo 'Requesting C3U root (the am start result only confirms launch) ...'
  adb shell am start -n df.root/.C3UAdbRootActivity
  echo 'Follow progress with: adb logcat -s C3UAdbRoot:I C3URootService:I'
  exit 0
fi

if adb shell 'su -c id 2>/dev/null' 2>/dev/null | grep -q 'uid=0(root)'; then
  echo 'Already rooted; not relaunching DFRoot.'
  exit 0
fi

printf 'Requesting root via DFRoot protected ADB intent ...\n'
# am start may succeed before any exploit is attempted.
adb shell am start -n df.root/.C3UAdbRootActivity

# Status is checked using actual SU elevation, not DFRoot's SUCCESS markers.
for attempt in $(seq 1 50); do
  sleep 2
  if adb shell 'su -c id 2>/dev/null' 2>/dev/null | grep -q 'uid=0(root)'; then
    echo 'VERIFIED: su -c id returned uid=0(root)'
    exit 0
  fi
done

echo 'No verified SU elevation; inspect the app logs below.' >&2
adb logcat -d -s C3UAdbRoot:I C3URootService:I 2>/dev/null | tail -45 >&2 || true
echo 'Do not automatically retry DirtyFrag on the same boot.' >&2
exit 1
