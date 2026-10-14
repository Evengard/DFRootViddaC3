#!/usr/bin/env bash
# Opt-in diagnostic rollback: build the original 6de6222 DFRoot first stage
# with the exact historical DFRoot kernel helper. NO KernelSU preload,
# v3.1-specific patchers, service-owned worker, or automatic device access.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
OLD_REF=6de62220809a678fddbd3819e4fcb3bb68aa1eae
OLD_HELPER_SHA=5135155128a90947e6ec341c36ce4b7169bdfe68f363341c9d0ed9568c60e473
WORK="$ROOT/work-legacy/DFRoot"
DIST="$ROOT/dist-legacy"
HELPER="$ROOT/known-good/dfroot-helper-6de6222.ko"
for cmd in git python3 docker sha256sum; do
  command -v "$cmd" >/dev/null || { echo "Missing dependency: $cmd" >&2; exit 2; }
done
[[ -f "$HELPER" ]] || { echo "Missing verified legacy DFRoot kernel helper: $HELPER" >&2; exit 1; }
printf '%s  %s\n' "$OLD_HELPER_SHA" "$HELPER" | sha256sum -c -
mkdir -p "$(dirname "$WORK")" "$DIST" "$ROOT/.ci-cache/gradle-legacy"
rm -rf -- "$WORK"
git init -q "$WORK"
git -C "$WORK" remote add origin https://github.com/diabl0w/DFRoot.git
git -C "$WORK" -c protocol.version=2 fetch -q --depth=1 origin "$OLD_REF"
git -C "$WORK" checkout -q --detach FETCH_HEAD
python3 "$ROOT/tools/prepare-legacy-first-stage.py" "$WORK"

# The original helper is copied by prepare-legacy-first-stage.py. Do not
# call any LKM make target: an updated compiler could change CFI/relocations.
# Only build the userspace application and verify the packaged helper bytes.
BUILDER=dfroot-c3u-legacy-first-stage:local
docker build --platform linux/amd64 -t "$BUILDER" \
  -f "$ROOT/patches/dfroot/Dockerfile" "$ROOT/patches/dfroot"
docker run --rm --platform linux/amd64 \
  --mount "type=bind,src=${WORK},dst=/work" \
  --mount "type=bind,src=${ROOT}/.ci-cache/gradle-legacy,dst=/gradle-cache" \
  --workdir /work \
  --env GRADLE_USER_HOME=/gradle-cache \
  "$BUILDER" bash -euc '
    make signing.properties
    ./gradlew :app:assembleRelease --build-cache
    mkdir -p out
    shopt -s nullglob
    apks=(app/build/outputs/apk/release/DFRoot_*.apk)
    (( ${#apks[@]} == 1 )) || { echo "Expected exactly one APK" >&2; exit 1; }
    cp "${apks[0]}" out/DFRoot.apk
  '
APK="$WORK/out/DFRoot.apk"
python3 "$ROOT/tools/verify-apk-native.py" "$APK"
python3 - "$APK" "$HELPER" <<'PY'
import sys, zipfile
from pathlib import Path
apk, helper = map(Path, sys.argv[1:])
with zipfile.ZipFile(apk) as z:
    root = z.read('lib/arm64-v8a/libdfroot.so')
    bootstrap = z.read('lib/arm64-v8a/libbootstrap.so')
    ko = helper.read_bytes()
    if root.count(ko) != 1:
        raise SystemExit('FAIL: expected exactly one byte-exact archived DFRoot .ko inside libdfroot.so')
    if b'C3U_V7_KSU_PRELOAD' in bootstrap:
        raise SystemExit('FAIL: automatic KernelSU preloader found in diagnostic build')
print('PASS: archived first-stage helper embedded exactly; no integrated preloader')
PY
cp -f "$APK" "$DIST/DFRoot-C3U-LEGACY-FIRST-STAGE.apk"
python3 - "$DIST" "$OLD_REF" "$OLD_HELPER_SHA" <<'PY'
import hashlib,json,sys
from pathlib import Path
dest=Path(sys.argv[1]); apk=dest/'DFRoot-C3U-LEGACY-FIRST-STAGE.apk'
manifest={
    'status':'diagnostic_candidate_not_device_tested',
    'purpose':'Restore archived DFRoot first-stage behavior and independent temporary-root shell',
    'dfroot':{'ref':sys.argv[2]},
    'helper':{'sha256':sys.argv[3],'bytes':12232},
    'apk':{'filename':apk.name,'sha256':hashlib.sha256(apk.read_bytes()).hexdigest()},
    'kernelsu_preload':False,
    'foreground_service':False,
    'automatic_deployment':False,
    'note':'Not identical to previously device-tested APK: rebuilt userspace/native binaries and signing key. No device test was performed.'
}
(dest/'build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
PY
printf 'Legacy diagnostic APK: %s\n' "$DIST/DFRoot-C3U-LEGACY-FIRST-STAGE.apk"
