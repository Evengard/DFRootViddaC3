# CI native build + caching fix (v5)

## Diagnosis

The earlier build used Gradle `:app:assembleRelease` after building the single
`android14-5.15` DFRoot kernel module, but **never compiled the Android JNI
CMake project**. Gradle could package an APK without `libexp.so`, which then
failed the embedded-C3U-module validation. That result does not imply the native
exploit itself failed to compile.

## Changes

1. `build-native-in-docker.sh`: uses Android NDK 28.2 and CMake 3.22.1 to build
   the ARM64 native code, then copies the resulting `lib*.so` binaries to
   `app/src/main/jniLibs/arm64-v8a/` prior to the Gradle stage. It checks for
   both `libexp.so` and `libdfrootsu.so` before proceeding.
2. `verify-apk-native.py`: reads the *actual APK* as a ZIP, requires the two
   ARM64 libraries, and compares the full v6 KernelSU .ko bytes inside
   `libexp.so` when run by `build-and-bundle.sh`.
3. `build-in-docker.sh`: builds only `android14-5.15` and runs native CMake,
   then Gradle, then validates the APK. It uses a content-addressed cache for
   the DFRoot `.ko` and a mounted Gradle cache.
4. GitHub Actions workflow: restores/saves `.ci-cache` and enables Buildx with
   `type=gha` cache for the large Android SDK builder image.

## Installation in your existing repository

```bash
unzip -o DFRootViddaC3-CI-Fix-v5-patch.zip -d /path/to/DFRootViddaC3
cd /path/to/DFRootViddaC3
python3 -m unittest discover -s tests -v
git add .github patches/dfroot tools tests docs
git commit -m "Build DFRoot native libs and cache CI dependencies"
git push
```

GitHub Actions builds on fresh runners. Re-run the `Build C3U candidates`
workflow after pushing. It must show `Staged native binary: libexp.so`,
`Staged native binary: libdfrootsu.so`, then an APK verifier PASS.

## Boundaries

This patch is source-only and has not run a full Android build here. The source
pinned to upstream DFRoot v3.1 may change. It does not replace the v6 C3U
KernelSU patch, the DFRoot exploit chain, or the existing protected ADB
foreground-process holder. The DirtyFrag worker has **not** been migrated into
the service; that is a separate future change. Do not automatically install or
load a freshly built kernel module based on a green CI run.
