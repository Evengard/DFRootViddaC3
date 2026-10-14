#!/usr/bin/env python3
"""Add a service-owned UI/ADB/boot launcher to the *working* legacy+C3U stage.

Runs ONLY after apply_stage.py. Fails closed against unexpected upstream/app changes.
Does not touch exp.c, bootstrap.c, the native .ko payload, or ExploitRunner.java.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys

# Hashes of the successful legacy 6de6222 source AFTER the known-good
# apply_stage.py integration, before this new Android-only migration.
EXPECTED = {
    'app/src/main/java/df/root/MainActivity.java': '2306f926e468a40f5e808f3f0f497df0dcda2ef2a838b265eab9bf2f234e8cda',
    'app/src/main/java/df/root/ExploitRunner.java': '3468813689c4e9d6c8d37c32fc19cce212fb9470674efa4459c57bfed41c09f1',
    'app/src/main/java/df/root/BootReceiver.java': 'bb3985e1a71335f3ba4f18179e8d3b99770edc819503ed1cf5dc6714ddb2803b',
    'app/src/main/java/df/root/SettingsFragment.java': '6e13456c19be7258f90e510c9d38922018b770a10f37de1b806dacc47bd9fae5',
    'app/src/main/AndroidManifest.xml': 'b1bcf07ff6eaf81e21606c3d084d7f89fee49922d59beeb930dba33c5ba16af8',
    'app/src/main/res/xml/preferences.xml': 'a5f0bb631443ca202937422d1832f6ab6a54aebe58ad41cc20acf79924c90bb4',
    'app/proguard-rules.pro': 'bd8d80d1986ae11424a2122415ce28aa2348546f59f69ba29f96a23db7c074fd',
    'app/src/main/jni/bootstrap.c': 'fb5433a2c4c2085f60e2fffef3b9a7b673b9c9ed7e0570e7bf37b5174d9350ae',
    'app/src/main/jni/exp.c': '69e7a62fe98cdad5c21065d5605cbbe12ed8ad74d65553506e1e745e128220c6',
}

NATIVE_IMMUTABLE = ('app/src/main/jni/bootstrap.c', 'app/src/main/jni/exp.c',
                    'app/src/main/java/df/root/ExploitRunner.java')
TEMPLATE_CLASSES = ('C3UAdbRootActivity.java', 'C3URootForegroundService.java',
                    'C3URootLog.java', 'C3URootManager.java', 'BootReceiver.java')


def digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def once(src: str, old: str, new: str, name: str) -> str:
    n = src.count(old)
    if n != 1:
        raise ValueError(f'{name}: expected original source exactly once, got {n}')
    return src.replace(old, new, 1)


def activity(src: str) -> str:
    # Service owns runExploit() now: this Activity may close and reopen at will.
    start = src.index('    private void launch(boolean withKernelSu) {')
    end = src.index('    private static class SuManagerEntry {', start)
    src = src[:start] + '''    private void launch(boolean withKernelSu) {
        btnRun.setEnabled(false);
        btnRunKsu.setEnabled(false);
        outputView.setText("");
        String mode = withKernelSu ? C3URootForegroundService.MODE_KSUN
                                   : C3URootForegroundService.MODE_ROOT_ONLY;
        try {
            C3URootForegroundService.start(this, mode, C3URootForegroundService.SOURCE_UI);
        } catch (RuntimeException e) {
            C3URootLog.append(mDeCtx, "Cannot start foreground service: " + e + "\\n");
            updateRunButton();
        }
    }

    // Reopening the Activity displays the ongoing or completed operation log.
    private final Runnable mLogPoll = new Runnable() {
        @Override public void run() {
            String content = C3URootLog.read(mDeCtx);
            if (!content.contentEquals(outputView.getText())) {
                outputView.setText(content);
                outputScroll.post(() -> outputScroll.fullScroll(View.FOCUS_DOWN));
            }
            updateRunButton();
            mMain.postDelayed(this, 700);
        }
    };

    @Override
    protected void onStart() {
        super.onStart();
        mMain.removeCallbacks(mLogPoll);
        mMain.post(mLogPoll);
    }

    @Override
    protected void onStop() {
        mMain.removeCallbacks(mLogPoll);
        super.onStop();
    }

''' + src[end:]
    src = once(src, '    private final Executor mExec = Executors.newSingleThreadExecutor();\n',
               '', 'remove Activity exploit executor')
    src = once(src, '        boolean available = mValidSuManagerPos >= 1 && !new File("/dev/df").exists();',
               '        boolean available = mValidSuManagerPos >= 1 && !new File("/dev/df").exists()\n'
               '                && !C3URootForegroundService.isRunning();',
               'button state')
    # On first use of the app with no prior manager selection, pick actual KSUN.
    src = once(src,
               '''        String saved = prefs.getString(ExploitRunner.PREF_SU_MANAGER, null);
        boolean savedFound = false;''',
               '''        String saved = prefs.getString(ExploitRunner.PREF_SU_MANAGER, null);
        if (saved == null && C3URootManager.isKsuNextAvailable(mDeCtx)) {
            saved = C3URootManager.KSU_NEXT_PACKAGE;
            prefs.edit().putString(ExploitRunner.PREF_SU_MANAGER, saved).commit();
        }
        boolean savedFound = false;''', 'first UI manager auto selection')
    # Fallback for stale saved manager: select KSUN if present rather than picker.
    src = once(src,
               '''        if (!savedFound && saved != null) { // Saved manager was uninstalled
            prefs.edit().remove(ExploitRunner.PREF_SU_MANAGER).apply();
        }
''',
               '''        if (!savedFound) {
            int preferredPos = -1;
            for (int i = 1; i < entries.size(); i++) {
                if (C3URootManager.KSU_NEXT_PACKAGE.equals(entries.get(i).packageName)) {
                    preferredPos = i;
                    break;
                }
            }
            if (preferredPos >= 1) {
                spinnerSuManager.setSelection(preferredPos);
                mValidSuManagerPos = preferredPos;
                prefs.edit().putString(ExploitRunner.PREF_SU_MANAGER,
                        C3URootManager.KSU_NEXT_PACKAGE).commit();
            } else if (saved != null) {
                prefs.edit().remove(ExploitRunner.PREF_SU_MANAGER).commit();
            }
        }
''', 'stale manager fallback')
    return src


def settings(src: str) -> str:
    old = '''        SwitchPreference softRebootPref = (SwitchPreference) findPreference("soft_reboot");'''
    new = '''        // Only used if Start at Boot is explicitly enabled; default is temp root.
        SwitchPreference fullBootPref = (SwitchPreference) findPreference("c3u_boot_full_ksu");
        fullBootPref.setPersistent(false);
        fullBootPref.setChecked(dePrefs.getBoolean("c3u_boot_full_ksu", false));
        fullBootPref.setOnPreferenceChangeListener((pref, value) ->
                dePrefs.edit().putBoolean("c3u_boot_full_ksu", (Boolean) value).commit());

''' + old
    return once(src, old, new, 'boot mode preference')


def preferences(src: str) -> str:
    old = '''    <SwitchPreference
        android:key="soft_reboot"'''
    new = '''    <SwitchPreference
        android:key="c3u_boot_full_ksu"
        android:title="Use full KernelSU on boot"
        android:summary="Only when Start at Boot is on. Off = temporary root only. Full mode loads the kernel module."
        android:defaultValue="false" />

''' + old
    return once(src, old, new, 'boot mode setting')


def manifest(src: str) -> str:
    src = once(src,
               '    <uses-permission android:name="android.permission.QUERY_ALL_PACKAGES" />',
               '''    <uses-permission android:name="android.permission.QUERY_ALL_PACKAGES" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_SPECIAL_USE" />''',
               'Android 14 FGS permissions')
    src = once(src,
               '''        <activity
            android:name=".SettingsActivity"''',
               '''        <!-- Brief ADB-only entrypoint, restricted to shell's DUMP permission. -->
        <activity
            android:name=".C3UAdbRootActivity"
            android:exported="true"
            android:permission="android.permission.DUMP"
            android:excludeFromRecents="true"
            android:noHistory="true"
            android:theme="@android:style/Theme.Translucent.NoTitleBar" />

        <service
            android:name=".C3URootForegroundService"
            android:exported="false"
            android:directBootAware="true"
            android:foregroundServiceType="specialUse">
            <property
                android:name="android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE"
                android:value="User or opt-in boot invoked device-specific root operation" />
        </service>

        <activity
            android:name=".SettingsActivity"''',
               'protected ADB activity and non-exported service')
    return src


def proguard(src: str) -> str:
    return src + '''
# Manifest entry points and CI-verifiable class identities.
-keep class df.root.C3UAdbRootActivity { *; }
-keep class df.root.C3URootForegroundService { *; }
-keep class df.root.C3URootManager { *; }
-keep class df.root.C3URootLog { *; }
-keep class df.root.BootReceiver { *; }
'''


TRANSFORMS = {
    'app/src/main/java/df/root/MainActivity.java': activity,
    'app/src/main/java/df/root/SettingsFragment.java': settings,
    'app/src/main/AndroidManifest.xml': manifest,
    'app/src/main/res/xml/preferences.xml': preferences,
    'app/proguard-rules.pro': proguard,
}


def apply(checkout: Path, template_dir: Path) -> None:
    checkout = checkout.resolve()
    for rel, expected_hash in EXPECTED.items():
        source = checkout / rel
        if not source.is_file() or digest(source.read_bytes()) != expected_hash:
            raise ValueError(f'Unexpected legacy+KSU source at {rel}; refusing change')
    for name in TEMPLATE_CLASSES:
        if not (template_dir / name).is_file():
            raise ValueError(f'Android service template missing: {name}')
        if name != 'BootReceiver.java' and (checkout / 'app/src/main/java/df/root' / name).exists():
            raise ValueError(f'Java class already exists: {name}')

    # Calculate every replacement before writing anything.
    updates = {rel: transformer((checkout / rel).read_text())
               for rel, transformer in TRANSFORMS.items()}
    javadir = checkout / 'app/src/main/java/df/root'
    for name in TEMPLATE_CLASSES:
        updates[f'app/src/main/java/df/root/{name}'] = (template_dir / name).read_text()

    for rel, text in updates.items():
        dest = checkout / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)

    for rel in NATIVE_IMMUTABLE:
        if digest((checkout / rel).read_bytes()) != EXPECTED[rel]:
            raise ValueError(f'CRITICAL: existing tested implementation changed: {rel}')
    print('PASS: unchanged native exploit, bootstrap, KernelSU payload and ExploitRunner')
    print('PASS: protected ADB launcher, explicit root-only/ksun modes, shared FGS worker')
    print('PASS: unattended KernelSU Next selection and opt-in boot mode')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkout', type=Path)
    args = parser.parse_args()
    templates = Path(__file__).resolve().parent / 'android-service'
    try:
        apply(args.checkout, templates)
    except (OSError, ValueError) as e:
        parser.exit(1, f'Foreground-service migration REFUSED: {e}\n')


if __name__ == '__main__':
    main()
