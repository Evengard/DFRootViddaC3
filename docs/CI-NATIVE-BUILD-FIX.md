# CI native build + caching fix (v5.1)

## Diagnosis

The original CI did not explicitly build DFRoot's JNI CMake targets before
running Gradle. The v5 patch added the native build, and your latest Actions
log confirms it now produces all three ARM64 outputs:

```text
Staged native binary: libbootstrap.so
Staged native binary: libdfroot.so
Staged native binary: libdfrootsu.so
```

**The remaining failure was a bad assertion in our v5 patch, not a compiler
error.** The patch demanded a nonexistent `libexp.so` output. In pinned DFRoot
v3.1, `exp.c` is built into the `libdfroot.so` executable and the C3U v6
KernelSU module is embedded into `libbootstrap.so` by `c3u_ksu_preload.c`.
The temporary root client is `libdfrootsu.so`.

## Changes

1. `build-native-in-docker.sh`: uses Android NDK 28.2 and CMake 3.22.1 to build
   the ARM64 native code, then copies the resulting `lib*.so` binaries to
   `app/src/main/jniLibs/arm64-v8a/` prior to the Gradle stage. It checks for
   all three real targets—`libdfroot.so`, `libbootstrap.so`, and
   `libdfrootsu.so`—before proceeding.
2. `verify-apk-native.py`: reads the *actual APK* as a ZIP, requires the three ARM64 executables, and compares the full v6 KernelSU .ko bytes
   inside `libbootstrap.so` when run by `build-and-bundle.sh`.
3. `build-in-docker.sh`: builds only `android14-5.15` and runs native CMake,
   then Gradle, then validates the APK. It uses a content-addressed cache for
   the DFRoot `.ko` and a mounted Gradle cache.
4. GitHub Actions workflow: restores/saves `.ci-cache` and enables Buildx with
   `type=gha` cache for the large Android SDK builder image.

## Installation in your existing repository

```bash
unzip -o DFRootViddaC3-CI-Fix-v5.1-patch.zip -d /path/to/DFRootViddaC3
cd /path/to/DFRootViddaC3
python3 -m unittest discover -s tests -v
git add patches/dfroot tools/verify-apk-native.py tests/test_ci_native.py docs/CI-NATIVE-BUILD-FIX.md README.md
git commit -m "Build DFRoot native libs and cache CI dependencies"
git push
```

GitHub Actions builds on fresh runners. Re-run the `Build C3U candidates`
workflow after pushing. It must show `Staged native binary: libdfroot.so`,
`Staged native binary: libbootstrap.so`, and
`Staged native binary: libdfrootsu.so`, then an APK verifier PASS.
The exact embedded KSU module is checked in the final APK's
`lib/arm64-v8a/libbootstrap.so` entry.

## Boundaries

This patch is source-only and has not run a full Android build here. The source
pinned to upstream DFRoot v3.1 may change. It does not replace the v6 C3U
KernelSU patch, the DFRoot exploit chain, or the existing protected ADB
foreground-process holder. The DirtyFrag worker has **not** been migrated into
the service; that is a separate future change. Do not automatically install or
load a freshly built kernel module based on a green CI run.
