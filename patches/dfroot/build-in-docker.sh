#!/usr/bin/env bash
# Build ONLY android14-5.15 DFRoot kernel module + modified APK inside Docker.
# Usage: ./build-in-docker.sh /path/to/DFRoot
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /path/to/DFRoot" >&2
  exit 2
fi
for cmd in docker awk grep; do
  command -v "$cmd" >/dev/null || { echo "Missing host command: $cmd" >&2; exit 1; }
done
repo="$(cd "$1" && pwd -P)"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

jni="$repo/app/src/main/jni"
[[ -f "$jni/exp.c" ]] || { echo "Not a DFRoot repository: $repo" >&2; exit 1; }
if ! grep -q C3U_ONLY_KMI_ANDROID14_5_15 "$jni/exp.c" || \
   ! grep -q 'dfroot_start_root_service' "$jni/bootstrap.c"; then
  echo "Apply overlay first: python3 overlay/apply_overlay.py '$repo'" >&2
  exit 1
fi
if grep -Eq 'dfroot-android(12-5\.10|13-5\.10|13-5\.15|14-6\.1|15-6\.6|16-6\.12|17-6\.18)\.ko' "$jni/CMakeLists.txt"; then
  echo "ERROR: CMake still references other KMI builds; reapply overlay." >&2
  exit 1
fi

ddk_release="$(awk '/image: ghcr\.io\/ylarod\/ddk-min:/{sub(/.*-/ , ""); print; exit}' "$repo/.github/workflows/build.yml")"
[[ -n "$ddk_release" ]] || { echo "Could not determine upstream DDK image tag" >&2; exit 1; }

kmi=android14-5.15
ko="$jni/ko/dfroot-${kmi}.ko"
image="ghcr.io/ylarod/ddk-min:${kmi}-${ddk_release}"
# Reuse the previously built module when retrying a failed Docker SDK/APK stage.
# Set FORCE_KO_REBUILD=1 to compile the module again.
if [[ "${FORCE_KO_REBUILD:-0}" != 1 && -s "$ko" && \
      ! "$repo/lkm/dfroot.c" -nt "$ko" && \
      ! "$repo/lkm/Makefile" -nt "$ko" ]]; then
  echo "=== Reusing previously built module: ${kmi} ==="
else
  echo "=== Building the ONLY required module: ${kmi} ==="
  echo "DDK image: $image"
  docker run --rm --platform linux/amd64 --pid=host --network=none \
  --mount "type=bind,src=${repo},dst=/proj" \
  --env KMI="$kmi" \
  "$image" \
  bash -euc '
    cd /proj/lkm
    make -j"$(nproc)"
    llvm-objcopy --strip-unneeded \
      -R .comment -R .note.gnu.build-id -R .note.gnu.property \
      -R .note.Linux -R .note.GNU-stack \
      -R .BTF -R .BTF.base -R .llvm_addrsig \
      -R .hyp.text -R .hyp.bss -R .hyp.rodata -R .hyp.event_ids \
      -R .hyp.patchable_function_entries -R .hyp.data dfroot.ko
    mkdir -p /proj/app/src/main/jni/ko
    cp dfroot.ko "/proj/app/src/main/jni/ko/dfroot-${KMI}.ko"
    make clean
  '
fi
[[ -s "$ko" ]] || { echo "Kernel module not produced: $ko" >&2; exit 1; }

echo "=== Preparing Android APK builder image ==="
builder=dfroot-c3u-android-builder:local
docker build --platform linux/amd64 -t "$builder" \
  -f "$script_dir/Dockerfile" "$script_dir"

echo "=== Building release APK (only one KO is embedded) ==="
docker run --rm --platform linux/amd64 \
  --mount "type=bind,src=${repo},dst=/work" \
  --workdir /work \
  --env GRADLE_USER_HOME=/work/.gradle-docker-cache \
  "$builder" bash -euc '
    make signing.properties
    ./gradlew :app:assembleRelease
    mkdir -p out
    cp app/build/outputs/apk/release/DFRoot_*.apk out/DFRoot.apk
    ls -lh out/DFRoot.apk
  '
[[ -s "$repo/out/DFRoot.apk" ]] || { echo "APK was not produced" >&2; exit 1; }
echo "APK ready: $repo/out/DFRoot.apk"
