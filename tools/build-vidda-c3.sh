#!/usr/bin/env bash
# Single end-to-end path: compile KernelSU from selected upstream ref (dev by default),
# then package THAT compiled .ko in the legacy DFRoot APK. No silent fallback.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
KO_DIR="$ROOT/dist/vidda-c3-kernelsu"
APK_DIR="$ROOT/dist/vidda-c3"
KO="$KO_DIR/ViddaC3-KernelSU-Next.ko"
APK="$APK_DIR/ViddaC3-Root.apk"

# Fail immediately if CI has not been configured with one persistent signing key.
# This prevents wasting time compiling a module that cannot be packaged.
python3 "$ROOT/tools/prepare-apk-signing.py" --check

# Prevent stale results from making an unsuccessful run appear successful.
rm -rf -- "$KO_DIR" "$APK_DIR"

# No signing secret is inherited by the upstream KernelSU compilation process.
(
  unset C3U_SIGNING_KEYSTORE_B64 C3U_SIGNING_KEYSTORE_PASSWORD
  unset C3U_SIGNING_KEY_ALIAS C3U_SIGNING_KEY_PASSWORD
  bash "$ROOT/tools/build-kernelsu.sh"
)
test -s "$KO" || { echo 'FAIL: KernelSU compilation did not produce a .ko' >&2; exit 1; }

# The APK builder requires this exact freshly compiled .ko and its ABI attestations.
bash "$ROOT/tools/build-dfroot.sh"

python3 "$ROOT/tools/verify-vidda-c3-apk.py" \
  --apk "$APK" --ko "$KO" --manifest "$APK_DIR/build-manifest.json"

echo 'PASS: freshly compiled KernelSU module embedded inside APK'
echo 'WARNING: A newly built module is not automatically proven stable on this projector.'
