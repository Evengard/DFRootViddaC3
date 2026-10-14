#!/usr/bin/env bash
# C3U all-in-one: reuse or build validated v6 .ko, embed inside v3 patched
# DFRoot bootstrap, then Docker-build the single KMI and APK.
# No on-device action is taken by this script.
set -euo pipefail
if [[ $# -ne 2 && $# -ne 3 ]]; then
  echo "Usage: $0 /path/to/DFRoot /path/to/working-v6.ko" >&2
  echo "   OR: $0 /path/to/DFRoot --build-v6 /path/to/KernelSU-Next" >&2
  exit 2
fi
for cmd in bash python3 docker; do
  command -v "$cmd" >/dev/null || { echo "Missing: $cmd" >&2; exit 2; }
done
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
DFROOT="$(cd "$1" && pwd -P)"
if [[ $# -eq 3 && "$2" == "--build-v6" ]]; then
  echo "=== Building v6 KO from exact local KernelSU Next revision ==="
  "$SELF/v6-builder/build-module.sh" "$3" "$SELF/v6-output"
  KO="$SELF/v6-output/aarch64_android14-5.15_kernelsu-c3u-permissive-v6-UNVERIFIED-DO-NOT-LOAD.ko"
elif [[ $# -eq 2 ]]; then
  KO="$(cd "$(dirname "$2")" && pwd -P)/$(basename "$2")"
else
  echo "Invalid arguments" >&2; exit 2
fi
[[ -s "$KO" ]] || { echo "Missing v6 .ko: $KO" >&2; exit 1; }

echo "=== Applying single-KMI + interactive temporary-root overlay ==="
python3 "$SELF/overlay/apply_overlay.py" "$DFROOT"
echo "=== Embedding exactly the selected C3U v6 KernelSU module ==="
python3 "$SELF/overlay/apply_c3u_v7.py" "$DFROOT" "$KO"
echo "=== Building the DFRoot APK ==="
"$SELF/build-in-docker.sh" "$DFROOT"

# Always validate FINAL packaged APK contents. The exact v6 KO is embedded
# into libbootstrap.so by c3u_ksu_preload.c, not into libdfroot.so or a
# nonexistent libexp.so. It is not a standalone .ko APK entry.
python3 "$SELF/../../tools/verify-apk-native.py" \
  "$DFROOT/out/DFRoot.apk" \
  --embedded-ko "$KO"
echo "PASS: APK contains native DFRoot, root client and exact v6 kernel module"
