# DFRoot C3U patchset (v4 repository arrangement)

The **patches** are source-overlay scripts, not a fork of DFRoot. The GitHub
builder checks out `diabl0w/DFRoot` at a pinned ref, then runs the patches on
that disposable checkout. No user-created DFRoot fork is required.

The ordered sequence and their roles are declared in `series.json`.

* Stage 01: read-only source inspection (generates `dist/dfroot-source-report/`).
* Stage 02: single-KMI DFRoot native payload, ADB temp-root fallback.
* Stage 03: embed custom C3U KernelSU Next module, preserve firmware guards.
* Stage 04: permission-protected ADB Activity plus Android 14 foreground holder.

**Important: Stage 04 is not the requested service-owned exploit worker.**
The existing Root action still runs through `MainActivity`. There is no
verified upstream Java source in the container that produced this ZIP; the
`inspect-upstream-dfroot` GitHub workflow downloads the exact Java/JNI files
and creates a source report on GitHub runners. `docs/SERVICE-WORKER-MIGRATION.md`
records what must be migrated and the fail-closed acceptance criteria. We
should not manufacture a patch moving IpSec resources without verifying their
lifetime and the JNI binding.

This arrangement intentionally preserves the existing v3 manual behavior while
preparing for a real v4 worker patch. It does not automatically load modules at
boot or auto-install kernel changes.
