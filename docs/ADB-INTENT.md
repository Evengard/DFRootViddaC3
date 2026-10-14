# C3U: ADB-triggered root using a service-owned worker (v5.3)

The modified DFRoot APK exposes a **permission-protected explicit Activity**. From your ADB-connected host:

```sh
adb shell am start -n df.root/.C3UAdbRootActivity
adb logcat -s C3UAdbRoot:I C3URootService:I
```

The entrypoint requires `android.permission.DUMP` and refuses mismatched C3U firmware or a boot already carrying `/dev/df`. It is visible briefly solely to satisfy Android's foreground-service launch restrictions. It issues a short-lived one-time token and calls `startForegroundService()` with that token, then finishes. Ordinary third-party apps cannot access the activity with normal app privileges. The service is not exported.

The service calls `startForeground()` with a `specialUse` notification **before** executing the rooting worker. Its single-flight worker invokes the reviewed upstream DFRoot v3.1 `ExploitRunner.run(createDeviceProtectedStorageContext(), reporter)` directly. That class already owns the IPsec SPI, UDP encapsulation socket, transport transform, native `libdfroot.so` process and resource cleanup. A bounded partial wake lock protects against idle suspension. There are no Root-button UI clicks, `MainActivity` dependencies, or automatic retries.

Logs show `FGS_REQUESTED`, `FOREGROUND_ACTIVE`, `ROOT_WORKER_STARTED`, `NATIVE_DONE`, `ROOT_RESULT` or `ROOT_FAILED`, and `ROOT_WORKER_FINISHED`. `NATIVE_DONE` and module visibility do **not** independently establish successful `su` authorization. Verify with:

```sh
adb shell 'su -c id'
adb shell getenforce
```

An Activity launch alone merely confirms Android accepted the request. The APK requires the compatible installed KernelSU Next manager/`ksud`, the exact C3U firmware, and the embedded custom v6 module. Once `/dev/df` exists, the DirtyFrag exploit is considered one-shot for this boot; don't blindly retry. The foreground service cannot prevent OEM force-stops, kernel panics, or watchdog resets. Do not enable automatic root-on-boot without an established recovery path.

**Testing status:** This v5.3 source refactor applies to the verified DFRoot v3.1 Java source and passed local patch/integration tests and Java API-shaped stub compilation. It has **not** yet been compiled as a full APK by GitHub Actions or tested on the projector.
