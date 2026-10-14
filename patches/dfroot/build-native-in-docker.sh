#!/usr/bin/env bash
# Runs INSIDE the Android build container, after the single DFRoot KO and the
# C3U bootstrap patches have been staged. The pinned DFRoot v3.1 native target
# names are libdfroot.so (exploit), libbootstrap.so (privileged stage), and
# libdfrootsu.so (temporary-root CLI). There is NO libexp.so target.
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
: "${ANDROID_HOME:=${ANDROID_SDK_ROOT:-/opt/android-sdk}}"
ndk="${ANDROID_NDK_HOME:-$ANDROID_HOME/ndk/28.2.13676358}"
cmake="${C3U_CMAKE:-$ANDROID_HOME/cmake/3.22.1/bin/cmake}"
[[ -x "$cmake" && -f "$ndk/build/cmake/android.toolchain.cmake" ]] || {
  echo "Missing Android CMake ($cmake) or NDK ($ndk)" >&2
  exit 1
}
mkdir -p "$stage" "$build" "$artifacts"
# Fail rather than accidentally packaging binaries left over from a different
# checkout/configuration. This checkout is fresh on each CI run.
rm -f "$stage/libexp.so" "$stage/libdfroot.so" "$stage/libbootstrap.so" "$stage/libdfrootsu.so"

# -Wa,-I points Clang's integrated assembler at the JNI source directory for
# the .incbin KO/payload assets used by DFRoot. CMake may also declare its own
# additional dependencies and output directories.
"$cmake" -S "$jni" -B "$build" -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$ndk/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=arm64-v8a \
  -DANDROID_PLATFORM=android-34 \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_FLAGS="-Wa,-I,$jni" \
  -DCMAKE_ASM_FLAGS="-I$jni" \
  -DCMAKE_LIBRARY_OUTPUT_DIRECTORY="$artifacts" \
  -DCMAKE_RUNTIME_OUTPUT_DIRECTORY="$artifacts"
"$cmake" --build "$build" --parallel "${C3U_CMAKE_JOBS:-4}"

# The v3 DFRoot CMake targets include shared libraries and executable ELF
# payloads intentionally named lib*.so for installation by Android. Accept
# either LIBRARY or RUNTIME output directories, but never use a prebuilt file
# from the NDK as our exploit library.
count=0
while IFS= read -r -d '' candidate; do
  [[ -s "$candidate" ]] || continue
  name="$(basename "$candidate")"
  case "$candidate" in
    "$stage"/*) continue;;
  esac
  # Only stage ELF files. The linker may also place other files in the tree.
  if ! readelf -h "$candidate" 2>/dev/null | grep -q 'Machine:.*AArch64'; then
    echo "Skipping non-ARM64 native output: $candidate"
    continue
  fi
  install -m 0644 "$candidate" "$stage/$name"
  printf 'Staged native binary: %s (%s bytes)\n' "$name" "$(stat -c %s "$stage/$name")"
  count=$((count+1))
done < <(find "$artifacts" "$build" "$jni" -type f -name 'lib*.so' -print0 | sort -zu)

# Require actual upstream v3.1 targets, not the obsolete libexp.so name.
# c3u_ksu_preload.c is compiled into bootstrap; that is where the embedded
# KernelSU module bytes reside, NOT in libdfroot.so.
for required in libdfroot.so libbootstrap.so libdfrootsu.so; do
  if [[ ! -s "$stage/$required" ]]; then
    echo "ERROR: native CMake did not produce $required for arm64-v8a." >&2
    echo 'Native outputs found:' >&2
    find "$build" "$jni" -type f \( -name '*.so' -o -name 'CMakeCache.txt' \) -print >&2
    exit 1
  fi
done
if [[ -e "$stage/libexp.so" ]]; then
  echo 'ERROR: obsolete libexp.so unexpectedly staged; check upstream version.' >&2
  exit 1
fi
printf 'Native build succeeded: %d ELF files staged; APK packaging can proceed.\n' "$count"
