# C3U service-owned DirtyFrag migration — integration spec

## Current status

`C3URootForegroundService` is a **foreground process holder**, not the owner
of the DirtyFrag worker. `C3UAdbRootAction` still performs an activity UI
control click. The attached v4 repository **does not claim true headless
rooting**. Upstream DFRoot v3.1 Java/JNI sources must be examined first.

## Target design

1. **Protected ADB entrypoint**: `adb shell am start -n df.root/.C3UAdbRootActivity`
   (permission `android.permission.DUMP`), verifies exact target firmware.
2. The visibly launched Activity starts a **non-exported `specialUse`
   foreground service**. It does not handle IpSec resources or native exploit.
3. `C3URootForegroundService` promotes itself with an ongoing notification
   and schedules one background worker. It is `START_NOT_STICKY`.
4. A single `C3URootOperation` owns all `IpSecManager` transforms, UDP sockets,
   SPI allocations and file descriptors for their required lifetimes. No
   objects may be accidentally finalized or GC-closed while JNI uses them.
5. Operation calls DFRoot's existing native methods using the original
   initialization order, with native libraries loaded as required, and uses
   `applicationContext` instead of an Activity where supported.
6. The operation records `STARTED`, `IPSEC_READY`, `NATIVE_DONE`,
   `KSU_VISIBLE`, `ROOT_VERIFIED`, `FAILED` with distinct timestamps. Markers
   like `/dev/dfm6` are *not* accepted as proof of root.
7. A single-flight lock prevents simultaneous exploit attempts. `/dev/df`
   is a one-shot marker; the service must not automatically retry on timeout.
8. Resources are closed in `finally`, in correct reverse order; the
   foreground notification is removed only after worker completion or an
   explicit failure. Android process death may interrupt work and cannot be
   prevented absolutely by a foreground service.
9. Firmware checks and the selected C3U v6 module/SELinux corrections are
   preserved unchanged. No automatic reboot or boot-time loading.

## What CI verifies now

The included upstream-inspection workflow pins `DFRoot v3.1`, copies the Java
and JNI files referencing IPsec and the native root path, and uploads a report
under the `dfroot-v3.1-root-flow-source` artifact. The main CI continues to
build **the v3 UI-assisted edition**. A true service-owned patch should be
introduced as a new, fail-closed stage only when the pinned source has been
reviewed and compiled; never silently fall back to button clicks while
claiming headless behavior.

## Minimum tests for a future service-owned implementation

- Upstream pin and source-shape check reject unsupported changes.
- Java/Android compile against actual DFRoot v3.1 with Android 14 service
  type and permissions; no non-exported service can be started externally.
- Test duplicate `am start` requests, service kill, timeout, and interrupted
  IPsec cleanup. Assert no duplicate exploit worker.
- Only a real `su -c id` (authorized shell) or equivalent UID 0 command
  constitutes a functional-success signal; loading a `.ko` is not enough.
- Manual on-projector verification on the **exact** firmware before
  enabling any scheduled invocation.
