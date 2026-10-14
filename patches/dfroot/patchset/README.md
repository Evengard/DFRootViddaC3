# DFRoot C3U ordered patchset (v5.3)

GitHub Actions checks out pinned `diabl0w/DFRoot v3.1` on each run. No DFRoot fork is necessary. The stages listed in `series.json` are:

1. Inspect pinned DFRoot Java/JNI source (read-only).
2. Add single-KMI/temp-root native support.
3. Embed the custom KernelSU Next C3U module with firmware guards.
4. Install the protected ADB Activity / foreground-service skeleton.
5. **Upgrade to a service-owned DirtyFrag worker**, replacing the UI click with upstream `ExploitRunner.run(Context, IReporter)`.

Stage 05 verifies the exact reviewed upstream `ExploitRunner.java` SHA-256 before applying. The source comes from the `dfroot-source-report` folder in the successful GitHub Actions build artifact. It is *not* a reimplementation of the exploit, and the service does not need a visible Root button.

This is a source-reviewed implementation, **not device-tested**. The ADB entrypoint is `adb shell am start -n df.root/.C3UAdbRootActivity`. It is not a boot-time autorun feature, and no `.ko` is flashed or deployed automatically.
