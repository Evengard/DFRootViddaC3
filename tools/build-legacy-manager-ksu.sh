#!/usr/bin/env bash
# Manual-only C3U build: verified legacy DFRoot exploit + opt-in KernelSU stage.
# Do not fall back to a freshly compiled LKM or a bundled ksud executable.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
OLD_REF=6de62220809a678fddbd3819e4fcb3bb68aa1eae
OLD_HELPER_SHA=5135155128a90947e6ec341c36ce4b7169bdfe68f363341c9d0ed9568c60e473
WORK="$ROOT/work-legacy-manager-ksu/DFRoot"
DIST="$ROOT/dist-legacy-manager-ksu"
HELPER="$ROOT/known-good/dfroot-helper-6de6222.ko"
GOOD_KSU="$ROOT/known-good/working-v6.ko"
for cmd in git python3 docker sha256sum; do
  command -v "$cmd" >/dev/null || { echo "Missing: $cmd" >&2; exit 2; }
done
[[ -f "$HELPER" && -f "$GOOD_KSU" ]] || { echo 'Missing verified .ko input' >&2; exit 1; }
printf '%s  %s\n' "$OLD_HELPER_SHA" "$HELPER" | sha256sum -c -
( cd "$ROOT/known-good" && sha256sum -c working-v6.sha256 )
python3 -m unittest discover -s "$ROOT/tests" -p 'test_legacy_manager_ksu.py' -v
mkdir -p "$(dirname "$WORK")" "$DIST" "$ROOT/.ci-cache/gradle-legacy-manager-ksu"
rm -rf -- "$WORK"
git init -q "$WORK"
git -C "$WORK" remote add origin https://github.com/diabl0w/DFRoot.git
git -C "$WORK" -c protocol.version=2 fetch -q --depth=1 origin "$OLD_REF"
git -C "$WORK" checkout -q --detach FETCH_HEAD
python3 "$ROOT/tools/prepare-legacy-first-stage.py" "$WORK"
python3 "$ROOT/patches/dfroot/legacy-ksu/apply_stage.py" "$WORK"

# Only the userspace DFRoot app is built. Never regenerate the archived helper
# or the proven KernelSU module during this workflow.
BUILDER=dfroot-c3u-legacy-manager-ksu:local
docker build --platform linux/amd64 -t "$BUILDER" \
  -f "$ROOT/patches/dfroot/Dockerfile" "$ROOT/patches/dfroot"
docker run --rm --platform linux/amd64 \
  --mount "type=bind,src=${WORK},dst=/work" \
  --mount "type=bind,src=${ROOT}/.ci-cache/gradle-legacy-manager-ksu,dst=/gradle-cache" \
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
python3 - "$APK" "$HELPER" "$GOOD_KSU" <<'PY'
from pathlib import Path
import hashlib, sys, zipfile
apk, helper, ksu = map(Path, sys.argv[1:])
with zipfile.ZipFile(apk) as z:
    old = z.read('lib/arm64-v8a/libdfroot.so')
    loader = z.read('lib/arm64-v8a/libc3uksu.so')
    bootstrap = z.read('lib/arm64-v8a/libbootstrap.so')
    su_client = z.read('lib/arm64-v8a/libdfrootsu.so')
    dex = b''.join(z.read(n) for n in z.namelist()
                   if n.startswith('classes') and n.endswith('.dex'))
    if old.count(helper.read_bytes()) != 1:
        raise SystemExit('FAIL: the original 6de6222 DFRoot helper is not embedded byte-for-byte')
    if loader.count(ksu.read_bytes()) != 1:
        raise SystemExit('FAIL: new stage is missing byte-exact tested KernelSU module')
    if ksu.read_bytes() in bootstrap:
        raise SystemExit('FAIL: KernelSU payload embedded in legacy bootstrap rather than separate stage')
    if b'dfroot_c3u_su_v1' not in su_client and b'dfroot_c3u_su_v1' not in bootstrap:
        raise SystemExit('FAIL: independent temporary root shell not found')
    if b'c3u-ksu-request' not in dex or b'c3u-ksu-loader' not in dex:
        raise SystemExit('FAIL: opt-in Java wiring absent from final APK')
    if b'448155d297e0402ca577379131fc081387a4454392212c3b1567a9de0d58c974' not in dex:
        raise SystemExit('FAIL: Manager-staged ksud runtime pin missing')
    if b'07c12cee5bbe68c989dd4edc3189dfba6832ca0f73ff1be90727da8a0a1869c3' in loader:
        raise SystemExit('FAIL: bundled standalone ksud identity leaked into loader')
print('PASS: original DFRoot helper, standalone root shell, and opt-in staging included')
print('PASS: byte-exact device-tested KernelSU module in second stage; NO ksud bundled')
PY
cp "$APK" "$DIST/DFRoot-C3U-LEGACY-MANAGER-KSU.apk"
python3 - "$DIST" "$OLD_REF" "$OLD_HELPER_SHA" "$GOOD_KSU" <<'PY'
import hashlib,json,sys
from pathlib import Path
out=Path(sys.argv[1]); apk=out/'DFRoot-C3U-LEGACY-MANAGER-KSU.apk'; ko=Path(sys.argv[4]);
manifest={
  'status':'device_test_required',
  'dfroot':{'ref':sys.argv[2], 'helper_sha256':sys.argv[3]},
  'kernelsu':{'selection':'pinned-device-tested','sha256':hashlib.sha256(ko.read_bytes()).hexdigest(), 'bytes':ko.stat().st_size},
  'ksud':{'source':'installed Manager libksud.so, staged by DFRoot (NOT bundled)',
          'required_sha256':'448155d297e0402ca577379131fc081387a4454392212c3b1567a9de0d58c974'},
  'apk':{'filename':apk.name, 'sha256':hashlib.sha256(apk.read_bytes()).hexdigest()},
  'execution':{'legacy_activity':True,'independent_temporary_root_shell':True,
               'kernelsu_requires_explicit_ui_button':True,
               'no_boot_automatic_kernel_injection':True,
               'kernel_injection_after_original_late_load':True},
  'warning':'Never assume build success means runtime safety. First verify Temporary Root Only.'
}
(out/'build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
PY
printf 'Opt-in integrated legacy APK: %s\n' "$DIST/DFRoot-C3U-LEGACY-MANAGER-KSU.apk"
