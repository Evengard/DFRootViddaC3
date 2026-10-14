#!/usr/bin/env bash
# Build C3U-only DFRoot kernel module and the REQUIRED native CMake targets,
# then let Gradle package its own CMake targets; stage only an omitted client. Supports GitHub Actions cache.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /path/to/DFRoot" >&2
  exit 2
fi
for cmd in docker awk grep git sha256sum python3; do
  command -v "$cmd" >/dev/null || { echo "Missing host command: $cmd" >&2; exit 1; }
done
repo="$(cd "$1" && pwd -P)"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cache_root="${C3U_CI_CACHE_DIR:-$(cd "$script_dir/../.." && pwd -P)/.ci-cache}"
mkdir -p "$cache_root/dfroot-ko" "$cache_root/gradle"
cache_root="$(cd "$cache_root" && pwd -P)"

jni="$repo/app/src/main/jni"
[[ -f "$jni/exp.c" ]] || { echo "Not a DFRoot checkout: $repo" >&2; exit 1; }
if ! grep -q C3U_ONLY_KMI_ANDROID14_5_15 "$jni/exp.c" || \
   ! grep -q dfroot_start_root_service "$jni/bootstrap.c"; then
  echo "Apply overlay first: python3 overlay/apply_overlay.py '$repo'" >&2
  exit 1
fi
if grep -Eq 'dfroot-android(12-5\.10|13-5\.10|13-5\.15|14-6\.1|15-6\.6|16-6\.12|17-6\.18)\.ko' "$jni/CMakeLists.txt"; then
  echo 'ERROR: CMake still references other KMI builds.' >&2
  exit 1
fi

ddk_release="$(awk '/image: ghcr\.io\/ylarod\/ddk-min:/{sub(/.*-/ , ""); print; exit}' "$repo/.github/workflows/build.yml")"
[[ -n "$ddk_release" ]] || { echo 'Could not determine upstream DDK image tag' >&2; exit 1; }
kmi=android14-5.15
ko="$jni/ko/dfroot-${kmi}.ko"
image="ghcr.io/ylarod/ddk-min:${kmi}-${ddk_release}"

# Cache is content-addressed by DDK image, upstream commit and tracked lkm
# source CONTENTS. Never restore a KO across different source/image versions.
ko_key="$(
  {
    printf '%s\n' "$image" "$(git -C "$repo" rev-parse HEAD)" "$kmi"
    while IFS= read -r path; do
      [[ -f "$repo/$path" ]] && sha256sum "$repo/$path"
    done < <(git -C "$repo" ls-files -- lkm)
  } | sha256sum | awk '{print $1}'
)"
ko_cache="$cache_root/dfroot-ko/$ko_key.ko"
if [[ "${FORCE_KO_REBUILD:-0}" != 1 && -s "$ko_cache" ]]; then
  echo "=== Cache hit: DFRoot ${kmi} module ($ko_key) ==="
  mkdir -p "$(dirname "$ko")"
  cp -f "$ko_cache" "$ko"
else
  echo "=== Building DFRoot ${kmi} kernel module ==="
  echo "DDK image: $image"
  docker run --rm --platform linux/amd64 --network=none \
    --mount "type=bind,src=${repo},dst=/proj" \
    --env KMI="$kmi" "$image" \
    bash -euc '
      cd /proj/lkm
      make -j"$(nproc)"
      llvm-objcopy --strip-unneeded \
        -R .comment -R .note.gnu.build-id -R .note.gnu.property \
        -R .note.Linux -R .note.GNU-stack \
        -R .BTF -R .BTF.base -R .llvm_addrsig \
        -R .hyp.text -R .hyp.bss -R .hyp.rodata \
        -R .hyp.patchable_function_entries -R .hyp.data dfroot.ko
      mkdir -p /proj/app/src/main/jni/ko
      cp dfroot.ko "/proj/app/src/main/jni/ko/dfroot-${KMI}.ko"
      make clean
    '
  [[ -s "$ko" ]] || { echo "Kernel module not produced: $ko" >&2; exit 1; }
  cp -f "$ko" "$ko_cache"
fi
[[ -s "$ko" ]] || { echo "Kernel module missing: $ko" >&2; exit 1; }

echo '=== Preparing Android APK builder image ==='
builder=dfroot-c3u-android-builder:local
if [[ "${GITHUB_ACTIONS:-}" == 'true' && "${C3U_DOCKER_GHA_CACHE:-1}" == 1 ]]; then
  # setup-buildx-action installs the BuildKit driver that supports the GHA v2
  # cache backend. Build failure here must NOT silently use an uncached image.
  docker buildx build --platform linux/amd64 --load -t "$builder" \
    --cache-from type=gha,scope=c3u-android-sdk \
    --cache-to type=gha,scope=c3u-android-sdk,mode=max \
    -f "$script_dir/Dockerfile" "$script_dir"
else
  docker build --platform linux/amd64 -t "$builder" \
    -f "$script_dir/Dockerfile" "$script_dir"
fi

echo '=== Packaging Gradle/CMake native targets exactly once ==='
docker run --rm --platform linux/amd64 \
  --mount "type=bind,src=${repo},dst=/work" \
  --mount "type=bind,src=${script_dir},dst=/tooling,readonly" \
  --mount "type=bind,src=${cache_root}/gradle,dst=/gradle-cache" \
  --workdir /work \
  --env GRADLE_USER_HOME=/gradle-cache \
  "$builder" bash -euc '
    # Gradle externalNativeBuild already supplies libbootstrap.so and
    # libdfroot.so to MergeReleaseNativeLibs. In v5.1 we additionally copied
    # them to jniLibs, causing a duplicate-input Gradle failure.
    stage=app/src/main/jniLibs/arm64-v8a
    mkdir -p "$stage"
    rm -f "$stage/libbootstrap.so" "$stage/libdfroot.so" \
          "$stage/libdfrootsu.so" "$stage/libexp.so"
    make signing.properties

    # First pass uses Gradle-owned native artifacts exclusively.
    ./gradlew :app:assembleRelease --build-cache
    shopt -s nullglob
    apks=(app/build/outputs/apk/release/DFRoot_*.apk)
    if (( ${#apks[@]} != 1 )); then
      echo "ERROR: expected exactly one DFRoot release APK, got ${#apks[@]}" >&2
      exit 1
    fi
    apk="${apks[0]}"
    if ! unzip -Z1 "$apk" | grep -Fxq "lib/arm64-v8a/libbootstrap.so"; then
      echo "ERROR: Gradle failed to package its CMake libbootstrap.so" >&2
      exit 1
    fi
    if ! unzip -Z1 "$apk" | grep -Fxq "lib/arm64-v8a/libdfroot.so"; then
      echo "ERROR: Gradle failed to package its CMake libdfroot.so" >&2
      exit 1
    fi

    if unzip -Z1 "$apk" | grep -Fxq "lib/arm64-v8a/libdfrootsu.so"; then
      echo "Standalone root client already packaged by Gradle; no jniLibs staging needed"
    else
      # Executable ELF targets may not be packaged by Android Gradle Plugin.
      # Build and stage ONLY that one executable, then let Gradle re-merge.
      echo "Standalone root client absent; staging only libdfrootsu.so"
      /tooling/build-native-in-docker.sh /work
      ./gradlew :app:assembleRelease --build-cache
    fi
    mkdir -p out
    cp "$apk" out/DFRoot.apk
    echo "APK ready for strict verification: /work/out/DFRoot.apk"
  '
[[ -s "$repo/out/DFRoot.apk" ]] || { echo 'APK was not produced' >&2; exit 1; }
python3 "$script_dir/../../tools/verify-apk-native.py" "$repo/out/DFRoot.apk"
echo "APK ready: $repo/out/DFRoot.apk"
