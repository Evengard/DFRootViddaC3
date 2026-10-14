#!/usr/bin/env bash
# Legacy DFRoot (verified first stage) + opt-in KernelSU injection.
# C3U_EMBED_REBUILT_KSU=1 embeds the .ko produced by the immediately preceding
# pinned source compilation. Never silently falls back to known-good bytes.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
OLD_REF=6de62220809a678fddbd3819e4fcb3bb68aa1eae
OLD_HELPER_SHA=5135155128a90947e6ec341c36ce4b7169bdfe68f363341c9d0ed9568c60e473
WORK="$ROOT/work-legacy-manager-ksu/DFRoot"
DIST="$ROOT/dist-legacy-manager-ksu"
HELPER="$ROOT/known-good/dfroot-helper-6de6222.ko"
GOOD_KSU="$ROOT/known-good/working-v6.ko"
REBUILT_KSU="$ROOT/dist-ksunext-reference/KernelSU-Next-C3U-REBUILT-UNVERIFIED-DO-NOT-LOAD.ko"
EMBED_REBUILT="${C3U_EMBED_REBUILT_KSU:-0}"
[[ "$EMBED_REBUILT" == 0 || "$EMBED_REBUILT" == 1 ]] || {
  echo 'C3U_EMBED_REBUILT_KSU must be 0 or 1' >&2; exit 2;
}
SELECTED_KSU="$GOOD_KSU"
MODULE_SELECTION=pinned-device-tested
APK_NAME=DFRoot-C3U-LEGACY-MANAGER-KSU.apk
STAGE_ARG=()
if [[ "$EMBED_REBUILT" == 1 ]]; then
  SELECTED_KSU="$REBUILT_KSU"
  MODULE_SELECTION=ci-compiled-unverified
  APK_NAME=DFRoot-C3U-AUTOBUILT-KSUNEXT-UNVERIFIED.apk
  STAGE_ARG=(--compiled)
  # Must exist in this run: checks are repeated by the source integration
  # patcher; there is NO fallback to the known-good .ko when rebuilt is set.
  [[ -s "$REBUILT_KSU" && -s "$ROOT/dist-ksunext-reference/module-comparison.json" ]] || {
    echo 'ERROR: compiled KernelSU artifact missing. Refusing to create an APK.' >&2; exit 1;
  }
fi
for cmd in git python3 docker sha256sum; do
  command -v "$cmd" >/dev/null || { echo "Missing: $cmd" >&2; exit 2; }
done
[[ -f "$HELPER" && -f "$GOOD_KSU" ]] || { echo 'Missing verified .ko input' >&2; exit 1; }
printf '%s  %s\n' "$OLD_HELPER_SHA" "$HELPER" | sha256sum -c -
( cd "$ROOT/known-good" && sha256sum -c working-v6.sha256 )
python3 -m unittest discover -s "$ROOT/tests" -p 'test_legacy_manager_ksu.py' -v
mkdir -p "$(dirname "$WORK")" "$ROOT/.ci-cache/gradle-legacy-manager-ksu"
rm -rf -- "$WORK" "$DIST"
mkdir -p "$DIST"
git init -q "$WORK"
git -C "$WORK" remote add origin https://github.com/diabl0w/DFRoot.git
git -C "$WORK" -c protocol.version=2 fetch -q --depth=1 origin "$OLD_REF"
git -C "$WORK" checkout -q --detach FETCH_HEAD
python3 "$ROOT/tools/prepare-legacy-first-stage.py" "$WORK"
python3 "$ROOT/patches/dfroot/legacy-ksu/apply_stage.py" "$WORK" "${STAGE_ARG[@]}"

# Only the userspace DFRoot app is built at this stage; the chosen .ko was
# compiled in the preceding CI step. Do not regenerate the DFRoot helper.
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
python3 - "$APK" "$HELPER" "$SELECTED_KSU" <<'PY'
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
        raise SystemExit('FAIL: new stage is missing the byte-exact SELECTED KernelSU module')
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
print('PASS: byte-exact SELECTED KernelSU module embedded in libc3uksu.so; NO ksud bundled')
PY
cp "$APK" "$DIST/$APK_NAME"
python3 - "$DIST" "$OLD_REF" "$OLD_HELPER_SHA" "$SELECTED_KSU" "$MODULE_SELECTION" "$APK_NAME" <<'PY'
import hashlib,json,sys
from pathlib import Path
out=Path(sys.argv[1]); apk=out/sys.argv[6]; ko=Path(sys.argv[4]);
manifest={
  'status': 'device_test_required' if sys.argv[5]=='pinned-device-tested' else 'CI_REBUILT_UNVERIFIED_DEVICE_TEST_REQUIRED',
  'dfroot':{'ref':sys.argv[2], 'helper_sha256':sys.argv[3]},
  'kernelsu':{'selection':sys.argv[5], 'sha256':hashlib.sha256(ko.read_bytes()).hexdigest(),
              'bytes':ko.stat().st_size, 'source_revision':
              '78ed5d1f5b5041a197f0b55291876d62a6bd7c67' if sys.argv[5]=='ci-compiled-unverified'
              else 'device-tested-binary'},
  'ksud':{'source':'installed Manager libksud.so, staged by DFRoot (NOT bundled)',
          'required_sha256':'448155d297e0402ca577379131fc081387a4454392212c3b1567a9de0d58c974'},
  'apk':{'filename':apk.name, 'sha256':hashlib.sha256(apk.read_bytes()).hexdigest()},
  'execution':{'legacy_activity':True,'independent_temporary_root_shell':True,
               'kernelsu_requires_explicit_ui_button':True,
               'no_boot_automatic_kernel_injection':True,
               'kernel_injection_after_original_late_load':True},
  'warning':'A rebuilt .ko is NOT automatically device-tested even if ABI checks pass. First verify Temporary Root Only.'
}
(out/'build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
PY
printf 'Opt-in integrated legacy APK: %s\n' "$DIST/$APK_NAME"

if [[ "$EMBED_REBUILT" == 1 ]]; then
  echo "WARNING: APK contains a CI-REBUILT KernelSU module; runtime behavior is NOT validated."
fi
