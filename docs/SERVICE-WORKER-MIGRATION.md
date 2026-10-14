# C3U source-reviewed foreground-service migration

## Implemented design (v5.3 CI patchset)

Using the upstream DFRoot v3.1 `ExploitRunner.java` recovered in the GitHub Actions build artifact, we confirmed the exploit already has a UI-independent API:

```java
public static int run(Context ctx, IReporter reporter) throws Exception
```

This API stages the selected manager's `ksud` and the native bootstrap, obtains `IpSecManager` resources, creates a transport transform, runs `libdfroot.so` via `ProcessBuilder`, and releases IPsec resources in a `finally` block. No DFRoot GUI is required to perform the operation.

The v5.3 service patch is applied after the older v3 launcher patch. It replaces its Activity and service sources, removes the Root-button auto-click from `MainActivity`, and calls `ExploitRunner.run()` directly on a service-owned single-thread worker. It requires the pinned upstream `ExploitRunner.java` SHA-256 and checks source and manifest shape before changing the app. On incompatible upstream sources, it fails the build instead of silently producing a UI-dependent APK.

`C3UAdbRootActivity` only creates a short-lived token and starts the non-exported service while briefly visible. The service promotes itself to a foreground notification before starting the worker, validates and consumes the token, rejects duplicate attempts, and holds a bounded partial wake lock. After the native worker exits and upstream IPsec cleanup is complete, it logs the actual return code and module visibility, then stops. It never claims `su` is working solely because `/dev/dfm6` or `kernelsu` is visible.

## What remains unverified

- Real GitHub Actions/Gradle build with the v5.3 service patch.
- Android 14/VIDAA behavior, foreground-service eligibility, and permission handoff on a C3U.
- Actual successful root under screen-off/sleep behavior and post-load stability.
- Manual `su -c id` confirmation with an authorized ADB shell. A module being listed isn't proof of a usable `su`.

The original C3U-v6 kernel module and firmware guards remain unchanged. The patch is not an automatic boot-time root installer. Kernel panics and watchdog resets remain possible if the `.ko` is incompatible.
