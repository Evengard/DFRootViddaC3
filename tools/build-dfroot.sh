#!/usr/bin/env bash
# Pinned, device-tested DFRoot first stage + freshly compiled KernelSU.
# This script never substitutes an older static KernelSU module.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
OLD_REF=6de62220809a678fddbd3819e4fcb3bb68aa1eae
OLD_HELPER_SHA=5135155128a90947e6ec341c36ce4b7169bdfe68f363341c9d0ed9568c60e473
WORK="$ROOT/work/DFRoot"
DIST="$ROOT/dist/vidda-c3"
HELPER="$WORK/app/src/main/jni/ko/dfroot-android14-5.15.ko"
SELECTED_KSU="$ROOT/dist/vidda-c3-kernelsu/ViddaC3-KernelSU-Next.ko"
MODULE_SELECTION=ci-compiled-unverified
APK_NAME=ViddaC3-Root.apk
trap 'rm -f -- "$WORK/keystore.jks" "$WORK/signing.properties"' EXIT
[[ -s "$SELECTED_KSU" && -s "$ROOT/dist/vidda-c3-kernelsu/module-comparison.json" ]] || {
  echo 'ERROR: freshly compiled KernelSU binary and ABI check are required' >&2; exit 1;
}
for cmd in git python3 docker sha256sum; do
  command -v "$cmd" >/dev/null || { echo "Missing: $cmd" >&2; exit 2; }
done
python3 -m unittest discover -s "$ROOT/tests" -p 'test_c3u_foreground_service.py' -v
mkdir -p "$(dirname "$WORK")" "$ROOT/.ci-cache/gradle-vidda-c3"
rm -rf -- "$WORK" "$DIST"
mkdir -p "$DIST"
git init -q "$WORK"
git -C "$WORK" remote add origin https://github.com/diabl0w/DFRoot.git
git -C "$WORK" -c protocol.version=2 fetch -q --depth=1 origin "$OLD_REF"
git -C "$WORK" checkout -q --detach FETCH_HEAD
python3 "$ROOT/tools/prepare-dfroot.py" "$WORK"
# The DFRoot helper is compiled from the original archived source, not staged
# from a binary in the repository. Fail closed on any output mismatch.
bash "$ROOT/tools/build-dfroot-helper.sh" "$WORK"
[[ -s "$HELPER" ]] || { echo 'DFRoot source build did not produce helper' >&2; exit 1; }
printf '%s  %s\n' "$OLD_HELPER_SHA" "$HELPER" | sha256sum -c -
python3 "$ROOT/patches/dfroot/legacy-ksu/apply_stage.py" "$WORK"
python3 "$ROOT/patches/dfroot/legacy-ksu/apply_foreground_service.py" "$WORK"
python3 "$ROOT/patches/dfroot/legacy-ksu/apply_tv_settings.py" "$WORK"
python3 "$ROOT/patches/dfroot/set-app-name.py" "$WORK"
# Signing is prepared only after the disposable checkout is fully patched.
python3 "$ROOT/tools/prepare-apk-signing.py" "$WORK"

# Both helper and KernelSU module were compiled and validated above.
# Do not rebuild modules during the Android Gradle packaging phase.
BUILDER=vidda-c3-dfroot:local
docker build --platform linux/amd64 -t "$BUILDER" \
  -f "$ROOT/patches/dfroot/Dockerfile" "$ROOT/patches/dfroot"
docker run --rm --platform linux/amd64 \
  --mount "type=bind,src=${WORK},dst=/work" \
  --mount "type=bind,src=${ROOT}/.ci-cache/gradle-vidda-c3,dst=/gradle-cache" \
  --workdir /work \
  --env GRADLE_USER_HOME=/gradle-cache \
  "$BUILDER" bash -euc '
    test -s keystore.jks && test -s signing.properties || {
      echo "Persistent signing key unavailable; refusing ephemeral signing" >&2; exit 1;
    }
    ./gradlew :app:assembleRelease --build-cache
    mkdir -p out
    shopt -s nullglob
    apks=(app/build/outputs/apk/release/DFRoot_*.apk)
    (( ${#apks[@]} == 1 )) || { echo "Expected exactly one APK" >&2; exit 1; }
    cp "${apks[0]}" out/DFRoot.apk
    "${ANDROID_HOME}/build-tools/37.0.0/apksigner" verify \
      --verbose --print-certs out/DFRoot.apk > out/apk-signature.txt
  '
# apksigner returns nonzero if the APK signature is invalid. Build Tools 37
# changed the certificate line prefix (Signer #1 -> V2/V3.0 Signer), so parse
# the signed APK report without assuming one specific tool-version format.
SIGNING_CERT_SHA256="$(python3 "$ROOT/tools/parse-apk-signature.py" "$WORK/out/apk-signature.txt")"
echo "PASS: APK cryptographic signature verified; certificate SHA-256=$SIGNING_CERT_SHA256"
# Remove the private signing materials immediately after Gradle finishes.
# The EXIT trap also covers a failed/interrupted Docker build.
rm -f -- "$WORK/keystore.jks" "$WORK/signing.properties"
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
python3 "$ROOT/tools/verify-service-apk.py" "$APK"
cp "$APK" "$DIST/$APK_NAME"
cp "$HELPER" "$DIST/ViddaC3-DFRoot-Helper.ko"
cp "$WORK/out/apk-signature.txt" "$DIST/apk-signature.txt"
python3 - "$DIST" "$OLD_REF" "$OLD_HELPER_SHA" "$SELECTED_KSU" "$MODULE_SELECTION" "$APK_NAME" "$SIGNING_CERT_SHA256" <<'PY'
import hashlib,json,sys
from pathlib import Path
out=Path(sys.argv[1]); apk=out/sys.argv[6]; ko=Path(sys.argv[4]);
import re
# Certificate hash comes from the version-tolerant parser. The preceding
# apksigner verify command must have succeeded before we reach this point.
cert_sha256=sys.argv[7]
gradle=(out.parent.parent/'work/DFRoot/app/build.gradle.kts').read_text()
version_match=re.search(r'(?m)^\s*versionCode\s*=\s*(\d+)\s*$', gradle)
if not version_match: raise SystemExit('Cannot determine built APK versionCode')
manifest={
  'status': 'CI_REBUILT_DEVICE_VERIFICATION_REQUIRED',
  'dfroot':{'ref':sys.argv[2], 'helper_sha256':sys.argv[3],
            'helper_selection':'compiled-from-pinned-source-byte-identical-to-device-tested',
            'helper_kmi':'android14-5.15',
            'helper_ddk_image':'ghcr.io/ylarod/ddk-min:android14-5.15-20260828'},
  'kernelsu':{'selection':sys.argv[5], 'sha256':hashlib.sha256(ko.read_bytes()).hexdigest(),
              'bytes':ko.stat().st_size,
              **json.loads((out.parent/'vidda-c3-kernelsu/source-version.json').read_text())},
  'ksud':{'source':'installed Manager libksud.so, staged by DFRoot (NOT bundled)',
          'required_sha256':'448155d297e0402ca577379131fc081387a4454392212c3b1567a9de0d58c974'},
  'apk':{'filename':apk.name, 'sha256':hashlib.sha256(apk.read_bytes()).hexdigest(),
         'version_code':int(version_match.group(1)), 'signing_certificate_sha256':cert_sha256,
         'signing':'persistent-GitHub-Actions-secret-backed'},
  'execution':{'service_owned_exploit':True,'independent_temporary_root_shell':True,
               'root_modes':['root-only','ksun'],
               'adb_protected_with_android_permission_DUMP':True,
               'boot_autostart_is_opt_in':True,
               'default_boot_mode':'root-only',
               'auto_manager':'com.rifsxd.ksunext',
               'kernelsu_requires_explicit_ui_adb_or_boot_mode':True,
               'kernel_injection_after_original_late_load':True},
  'warning':'A rebuilt .ko is NOT automatically device-tested even if ABI checks pass. First verify Temporary Root Only.'
}
(out/'build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
PY
printf 'Vidda C3 Root APK: %s\n' "$DIST/$APK_NAME"

echo 'NOTICE: this APK contains the latest selected KernelSU module; validate on device after upstream updates.'
