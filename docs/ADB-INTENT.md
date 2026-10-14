> **v4 note:** This is the v3 **UI-assisted** launcher held foreground, not a service-owned exploit worker. See `docs/SERVICE-WORKER-MIGRATION.md`.

# ADB-triggered C3U root with foreground-service process retention

The patched DFRoot APK exposes a protected, **visible** launcher Activity:

```sh
adb shell am start -n df.root/.C3UAdbRootActivity
```

Unlike the earlier no-display launcher, this Activity starts a **non-exported Android 14 foreground service** before opening DFRoot's main screen. The service promotes the process with `startForeground()` and an ongoing low-priority notification so Android is less likely to reclaim it while the exploit operates. A local binder handshake confirms that the service is foreground **before** the Root UI is launched; a ten-second timeout fails closed.

## Exact execution path

1. The exported launcher requires `android.permission.DUMP` (normally available only to ADB shell/system), verifies the exact C3U firmware, and refuses an already-armed boot.
2. The launcher enters `onResume()` with a translucent Activity so it is visible when it calls `startForegroundService()` (Android 12+ background start restrictions).
3. `C3URootForegroundService` creates a notification channel and calls `startForeground()` with Android 14 `specialUse` type; the manifest declares `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_SPECIAL_USE` and a special-use subtype. The service is **not exported**, and only the app can bind to it. A local binder callback acknowledges foreground readiness before root triggering is permitted.
4. Once the service is confirmed foreground, `MainActivity` consumes the one-time token, looks for DFRoot's existing Root control, and invokes its `performClick()`. The normal DFRoot Java/IpSec/DirtyFrag flow does the root operation; **the service does not invoke native exploit code**.
5. The service monitors `/dev/df`, `/dev/dfm1`, `/dev/dfm6`, and `/sys/module/kernelsu`, but does **not** treat marker presence as proof of root. It remains foreground for 30 seconds after the module appears (or stops after a maximum of four minutes), then removes its notification and terminates.
6. KernelSU Next v6 remains the same embedded custom module; it must be tested on the exact target firmware and still requires `/data/adb/ksud`. The service does not alter SELinux state and cannot recover a kernel crash.

This is **UI-assisted unattended rooting**, not a fully headless executable or permanent root. If the DFRoot UI changes, the safe matcher can fail with `NO_ROOT_CONTROL` rather than clicking an unrelated control. The service may also be stopped by an aggressive OEM killer, force-stop, user action, or reboot; it reduces normal background-reclamation risk, not eliminates it.

## Testing

```sh
adb shell am start -n df.root/.C3UAdbRootActivity
adb logcat -d -s C3UAdbRoot:I C3URootService:I
adb shell dumpsys activity services df.root
adb shell 'su -c id'
adb shell getenforce
```

Look for `FGS_REQUESTED`, `FOREGROUND_ACTIVE`, `FGS_CONFIRMED`, `ROOT_ACTION_CLICKED`, and `MODULE_VISIBLE_SETTLED` or `FGS_TIMEOUT`. These are **stage indicators**, not proof of root. Only a UID 0 command and the manager's verified status show that user-facing root works.

You can also use the host helper `./tools/adb-root-c3u.sh`. It invokes the intent and checks UID 0, not the service log, for success. ADB authorization is required; a normal application UID without the protected permission cannot invoke the launcher.

**Important Android TV caveats:** `Theme.NoDisplay` was replaced with `Theme.Translucent.NoTitleBar` so the Activity qualifies as visible when requesting a foreground service. The UI may briefly flash and Android might return to the main launcher; the service survives the Activity task (`stopWithTask=false`). Android 13+ `POST_NOTIFICATIONS` is not required to *start* a foreground service, but notification visibility depends on platform/user settings. The `specialUse` type avoids `shortService`'s three-minute hard timeout; Play distribution would require review of the stated special-use case.

`am start` only proves Android accepted the launch. A rejected foreground-service start is logged as `FGS_START_REFUSED` and no Root UI is opened. A failed service readiness handshake logs `FGS_NOT_READY` or `FGS_HANDSHAKE_TIMEOUT` and likewise refuses root UI launch. If the service cannot promote itself (e.g. an OEM policy restriction), `FOREGROUND_FAILED` will appear; the build is not device-tested.

**Do not run it repeatedly in the same boot.** `/dev/df` is a one-shot marker. Do not install any auto-start trigger until you have a reliable recovery method. Firmware differences, module ABI mismatches, watchdog resets, and permanent device failure remain possible.
