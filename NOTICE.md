# Source and license notices

This repository contains C3U-specific patch/build scripts derived from prior adaptations. It does not include third-party DFRoot or KernelSU-Next source archives by default. The GitHub Actions workflow fetches the following upstream projects at specified revisions:

- DFRoot, https://github.com/diabl0w/DFRoot — see its upstream license and copyright headers.
- KernelSU Next, https://github.com/KernelSU-Next/KernelSU-Next — the `/kernel` directory is GPL-2.0-only and the remainder is GPL-3.0-or-later per its upstream README.

The C3U v6 patch alters KernelSU Next's kernel module source, and generated binaries are based on that GPL-licensed source. The exact upstream Git commit hashes and target module/APK checksums are recorded in `dist/build-manifest.json`. If distributing binaries, provide recipients with the applicable complete corresponding source and notices for those binaries.

The project is experimental and is not affiliated with the manufacturers or upstream authors. No guarantees of stability, compatibility, support or warranty.

## Explicit ADB root intent security

The generated APK includes a permission-protected explicit Activity that starts
a non-exported foreground service when invoked through `adb shell am start`.
The Activity requires `android.permission.DUMP` and its request is accepted
only with a one-use short-lived token. The UI Root button starts the same
non-exported service with a separate same-application action. No exploit runs
inside either Activity. Do not remove the permission or export the service.

## Foreground service, logging and safety

The specialUse Android 14 foreground service calls upstream DFRoot's existing
`ExploitRunner.run()` from a worker thread, preserving native and IPsec resource
lifetimes. A bounded partial wake lock and single-flight guard protect the
operation; there are no automatic retries or boot-time loads.

An app-private bounded text log allows the UI to display output live and after
reopening. This does not guarantee survival against force-stop, watchdog reset
or kernel crash. The source patch is offline-tested only; a full build and
actual device behavior remain unverified.
