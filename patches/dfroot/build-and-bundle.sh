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

python3 - "$DFROOT" <<'PY'
from pathlib import Path
import json, sys, zipfile
repo = Path(sys.argv[1]); manifest = json.loads((repo/'app/src/main/jni/c3u-v7-manifest.json').read_text())
apk = repo/'out/DFRoot.apk'
if not apk.is_file(): raise SystemExit('APK missing')
# The custom blob is in bootstrap, which DFRoot embeds into libexp. The
# resulting APK need not have a standalone .ko asset entry.
with zipfile.ZipFile(apk) as z:
    libs = [x for x in z.namelist() if x.endswith('/libexp.so')]
    if not libs: raise SystemExit('APK lacks libexp.so; inspect Gradle output')
    original_ko = (repo/'app/src/main/jni/ko/c3u-ksunext-v6.ko').read_bytes()
    present = any(original_ko in z.read(lib) for lib in libs)
    if not present:
        raise SystemExit('FATAL: exact v6 KO bytes NOT found in APK libexp.so! Check bootstrap packaging.')
print(f'APK: {apk}')
print(f'Embedded v6 KO SHA-256: {manifest["sha256"]}')
print('PASS: exact supplied v6 module bytes are embedded inside APK libexp.so.')
print('NOTE: first boot/install test remains necessary; never enable auto-start before testing.')
PY
