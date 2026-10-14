#!/usr/bin/env bash
# Fallback ONLY for libdfrootsu.so when Gradle's CMake APK packaging omitted
# this executable. The Gradle-managed libbootstrap.so and libdfroot.so MUST NOT
# be staged into jniLibs: doing so causes MergeReleaseNativeLibs duplicates.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /path/to/DFRoot" >&2
  exit 2
fi
repo="$(cd "$1" && pwd -P)"
jni="$repo/app/src/main/jni"
stage="$repo/app/src/main/jniLibs/arm64-v8a"
build="$repo/.c3u-native-build"
artifacts="$build/artifacts"
[[ -f "$jni/CMakeLists.txt" && -s "$jni/ko/dfroot-android14-5.15.ko" && -s "$jni/ko/c3u-ksunext-v6.ko" ]] || {
  echo 'Missing patched JNI sources, DFRoot KO or embedded v6 KernelSU KO' >&2
  exit 1
}
# This fallback must never replace a Gradle/CMake native target.
for lib in libbootstrap.so libdfroot.so libexp.so; do
  if [[ -e "$stage/$lib" ]]; then
    echo "ERROR: native fallback must not run with $stage/$lib present" >&2
    exit 1
  fi
done
: "${ANDROID_HOME:=${ANDROID_SDK_ROOT:-/opt/android-sdk}}"
ndk="${ANDROID_NDK_HOME:-$ANDROID_HOME/ndk/28.2.13676358}"
cmake="${C3U_CMAKE:-$ANDROID_HOME/cmake/3.22.1/bin/cmake}"
[[ -x "$cmake" && -f "$ndk/build/cmake/android.toolchain.cmake" ]] || {
  echo "Missing Android CMake ($cmake) or NDK ($ndk)" >&2
  exit 1
}
mkdir -p "$stage" "$artifacts"
# Keep the previous integration's assembler search paths for payload assets.
"$cmake" -S "$jni" -B "$build" -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$ndk/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=arm64-v8a \
  -DANDROID_PLATFORM=android-34 \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_FLAGS="-Wa,-I,$jni" \
  -DCMAKE_ASM_FLAGS="-I$jni" \
  -DCMAKE_LIBRARY_OUTPUT_DIRECTORY="$artifacts" \
  -DCMAKE_RUNTIME_OUTPUT_DIRECTORY="$artifacts"
"$cmake" --build "$build" --target dfrootsu --parallel "${C3U_CMAKE_JOBS:-4}"
client="$artifacts/libdfrootsu.so"
[[ -s "$client" ]] || {
  echo 'ERROR: fallback CMake dfrootsu target produced no libdfrootsu.so' >&2
  exit 1
}
readelf -h "$client" | grep -q 'Machine:.*AArch64' || {
  echo 'ERROR: fallback libdfrootsu.so is not AArch64' >&2
  exit 1
}
install -m 0644 "$client" "$stage/libdfrootsu.so"
echo "Staged standalone client ONLY: libdfrootsu.so ($(stat -c %s "$client") bytes)"
