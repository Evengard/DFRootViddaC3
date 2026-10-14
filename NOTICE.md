# Source and license notices

This repository contains C3U-specific patch/build scripts derived from prior adaptations. It does not include third-party DFRoot or KernelSU-Next source archives by default. The GitHub Actions workflow fetches the following upstream projects at specified revisions:

- DFRoot, https://github.com/diabl0w/DFRoot — see its upstream license and copyright headers.
- KernelSU Next, https://github.com/KernelSU-Next/KernelSU-Next — the `/kernel` directory is GPL-2.0-only and the remainder is GPL-3.0-or-later per its upstream README.

The C3U v6 patch alters KernelSU Next's kernel module source, and generated binaries are based on that GPL-licensed source. The exact upstream Git commit hashes and target module/APK checksums are recorded in `dist/build-manifest.json`. If distributing binaries, provide recipients with the applicable complete corresponding source and notices for those binaries.

The project is experimental and is not affiliated with the manufacturers or upstream authors. No guarantees of stability, compatibility, support or warranty.

## Explicit ADB root intent security

The generated APK includes a permission-protected explicit Activity that initiates
the existing DFRoot Root button action when invoked with `am start` by an
authorized ADB shell. It has no implicit intent filter. Do not remove the
`android.permission.DUMP` restriction or publish an unprotected root-trigger
component. The current implementation intentionally starts the existing GUI
Activity and is not a native/headless executable. A root exploit can still
hang or crash the target device even if triggered correctly.

## Foreground service addition

The optional ADB-triggered launcher uses a non-exported Android 14 specialUse foreground service and a notification for up to four minutes. It retains DFRoot while its pre-existing Activity-based Root handler runs; it does NOT make DirtyFrag executable from a background service alone or guarantee survival against OEM process killers. Sideload/Android TV testing is required. No boot-time automation is included.
