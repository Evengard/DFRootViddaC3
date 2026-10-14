#!/usr/bin/env bash
# CI/local entrypoint. Builds a C3U-only KernelSU Next candidate and DFRoot APK.
# No flashing, no insmod, no device access, no boot-time deployment.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
for c in python3 git docker; do
  command -v "$c" >/dev/null || { echo "Missing required command: $c" >&2; exit 2; }
done
python3 "$ROOT/tools/validate-repo.py"

upstream=()
while IFS= read -r entry; do upstream+=("$entry"); done < <(python3 - "$ROOT/config/upstreams.json" <<'PY'
import json,sys
c=json.load(open(sys.argv[1]))
print(c['kernelsu_next']['repository'])
print(c['kernelsu_next']['ref'])
print(c['dfroot']['repository'])
print(c['dfroot']['ref'])
PY
)
KSU_REPO="${upstream[0]}"
KSU_REF="${C3U_KSU_REF_OVERRIDE:-${upstream[1]}}"
DFROOT_REPO="${upstream[2]}"
DFROOT_REF="${upstream[3]}"
USE_KNOWN_GOOD="${C3U_USE_KNOWN_GOOD:-0}"
[[ "$USE_KNOWN_GOOD" == 0 || "$USE_KNOWN_GOOD" == 1 ]] || { echo 'C3U_USE_KNOWN_GOOD must be 0 or 1' >&2; exit 2; }
# Reject ambiguous refs and flag injection. A complete Git SHA is also accepted.
[[ "$KSU_REF" =~ ^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}$ && "$KSU_REF" != *..* ]] || { echo 'Invalid KSU ref' >&2; exit 2; }
[[ "$DFROOT_REF" =~ ^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}$ && "$DFROOT_REF" != *..* ]] || { echo 'Invalid DFRoot ref' >&2; exit 2; }

WORK="$ROOT/work"
DIST="$ROOT/dist"
mkdir -p "$WORK" "$DIST"
# Always fresh upstream checkouts, even when this is rerun on the same host.
checkout_ref() {
  local slug="$1" ref="$2" dir="$3"
  rm -rf -- "$dir"
  mkdir -p "$dir"
  git -C "$dir" init -q
  git -C "$dir" remote add origin "https://github.com/${slug}.git"
  git -C "$dir" -c protocol.version=2 fetch -q --depth=1 origin "$ref"
  git -C "$dir" checkout -q --detach FETCH_HEAD
  printf '%s %s -> %s\n' "$slug" "$ref" "$(git -C "$dir" rev-parse HEAD)"
}
checkout_ref "$DFROOT_REPO" "$DFROOT_REF" "$WORK/DFRoot"

# Source inspection is read-only and acts as the pinned upstream integration
# report. It does not claim that DirtyFrag is now a service-owned worker.
echo '=== Inspect pinned upstream DFRoot Java/JNI root flow ==='
python3 "$ROOT/tools/inspect_dfroot_root_flow.py" \
  "$WORK/DFRoot" "$DIST/dfroot-source-report"
python3 "$ROOT/tools/check-patchset.py"
KSU_COMMIT=""
if [[ "$USE_KNOWN_GOOD" == 1 ]]; then
  echo '=== Using explicitly provided device-tested .ko (NO upstream KSU rebuild) ==='
  KO="$ROOT/known-good/working-v6.ko"
  expected_file="$ROOT/known-good/working-v6.sha256"
  [[ -s "$KO" && -s "$expected_file" ]] || { echo 'Missing known-good/working-v6.ko and/or known-good/working-v6.sha256' >&2; exit 1; }
  expected="$(head -1 "$expected_file" | awk '{print $1}')"
  [[ "$expected" =~ ^[0-9a-f]{64}$ ]] || { echo 'Invalid known-good SHA-256' >&2; exit 1; }
  if command -v sha256sum >/dev/null; then
    actual="$(sha256sum "$KO" | awk '{print $1}')"
  else
    actual="$(shasum -a 256 "$KO" | awk '{print $1}')"
  fi
  [[ "$expected" == "$actual" ]] || { echo 'Known-good .ko SHA-256 mismatch' >&2; exit 1; }
  selection=known-good
else
  echo '=== Building pinned KernelSU Next version with C3U v6 SELinux patch ==='
  checkout_ref "$KSU_REPO" "$KSU_REF" "$WORK/KernelSU-Next"
  KSU_COMMIT="$(git -C "$WORK/KernelSU-Next" rev-parse HEAD)"
  "$ROOT/patches/ksunext/build-module.sh" "$WORK/KernelSU-Next" "$DIST/ksu-build"
  KO="$DIST/ksu-build/aarch64_android14-5.15_kernelsu-c3u-permissive-v6-UNVERIFIED-DO-NOT-LOAD.ko"
  selection=source-built-candidate
fi
[[ -s "$KO" ]] || { echo "KernelSU module missing: $KO" >&2; exit 1; }

# The Android TV settings button is optional; it touches only Java UI code.
# Fail closed on unsupported MainActivity instead of silently mutating it.
if [[ "${C3U_ENABLE_TV_SETTINGS:-0}" == 1 ]]; then
  echo '=== Applying optional Android TV settings UI patch ==='
  python3 "$ROOT/patches/dfroot/overlay/apply_tv_settings.py" "$WORK/DFRoot"
fi

# Protected explicit Activity for script-initiated root. Enabled by default.
# Keeps DFRoot native exploit unmodified and simply dispatches its Root UI action.
if [[ "${C3U_ENABLE_ADB_INTENT:-1}" == 1 ]]; then
  echo '=== Installing protected C3U ADB Root intent launcher ==='
  python3 "$ROOT/patches/dfroot/overlay/apply_adb_intent.py" "$WORK/DFRoot"
  echo '=== Upgrading to true service-owned DirtyFrag exploit worker ==='
  python3 "$ROOT/patches/dfroot/overlay/apply_service_worker.py" "$WORK/DFRoot"
fi

echo '=== Applying DFRoot integration & building Android APK ==='
C3U_CI_CACHE_DIR="$ROOT/.ci-cache" \
  "$ROOT/patches/dfroot/build-and-bundle.sh" "$WORK/DFRoot" "$KO"

cp -f -- "$KO" "$DIST/KernelSU-Next-C3U-CANDIDATE.ko"
cp -f -- "$WORK/DFRoot/out/DFRoot.apk" "$DIST/DFRoot-C3U-CANDIDATE.apk"
python3 "$ROOT/tools/manifest.py" \
  --config "$ROOT/config/upstreams.json" \
  --out "$DIST/build-manifest.json" \
  --kernel "$DIST/KernelSU-Next-C3U-CANDIDATE.ko" \
  --apk "$DIST/DFRoot-C3U-CANDIDATE.apk" \
  --ksu-ref "$KSU_REF" \
  --ksu-commit "$KSU_COMMIT" \
  --dfroot-ref "$DFROOT_REF" \
  --dfroot-commit "$(git -C "$WORK/DFRoot" rev-parse HEAD)" \
  --selection "$selection"
cat > "$DIST/README-READ-ME-FIRST.txt" <<'TXT'
C3U CI ARTIFACTS — DO NOT INSTALL AUTOMATICALLY
These builds are generated automatically and are NOT device-tested.
The DFRoot integration remains experimental and needs an already installed,
compatible /data/adb/ksud. NEVER flash the .ko or APK into a boot partition.
Reboots, watchdog resets and permanent device failures are possible.
The APK signing key may be ephemeral in GitHub Actions; backup app settings.
Check build-manifest.json and validate on the exact C3U firmware manually.
Upstream updates open PRs, not automatic releases or device upgrades.
TXT
printf '\n=== Completed: generated artifacts, NOT device-tested ===\n'
ls -lh "$DIST/KernelSU-Next-C3U-CANDIDATE.ko" "$DIST/DFRoot-C3U-CANDIDATE.apk" "$DIST/build-manifest.json"
