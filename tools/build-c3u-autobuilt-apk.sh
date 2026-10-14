#!/usr/bin/env bash
# Single end-to-end path: compile KernelSU from exact tested source revision,
# then package THAT compiled .ko in the legacy DFRoot APK. No silent fallback.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
KO_DIR="$ROOT/dist-ksunext-reference"
APK_DIR="$ROOT/dist-legacy-manager-ksu"
KO="$KO_DIR/KernelSU-Next-C3U-REBUILT-UNVERIFIED-DO-NOT-LOAD.ko"
APK="$APK_DIR/DFRoot-C3U-AUTOBUILT-KSUNEXT-UNVERIFIED.apk"

# Prevent stale results from making an unsuccessful run appear successful.
rm -rf -- "$KO_DIR" "$APK_DIR"

bash "$ROOT/tools/build-ksunext-tested-ref-candidate.sh"
test -s "$KO" || { echo 'FAIL: KernelSU compilation did not produce a .ko' >&2; exit 1; }

# This flag changes the payload and native size guard used by the APK builder.
# When anything is missing, that builder fails rather than using working-v6.ko.
C3U_EMBED_REBUILT_KSU=1 bash "$ROOT/tools/build-legacy-manager-ksu.sh"

python3 "$ROOT/tools/verify-c3u-autobuilt-apk.py" \
  --apk "$APK" --ko "$KO" --manifest "$APK_DIR/build-manifest.json"

echo 'PASS: freshly compiled KernelSU module embedded inside APK'
echo 'WARNING: A newly built module is not automatically proven stable on this projector.'
