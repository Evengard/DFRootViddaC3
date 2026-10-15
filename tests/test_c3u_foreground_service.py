"""Offline checks: non-invasive service migration on working C3U legacy build."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'patches/dfroot/legacy-ksu/apply_foreground_service.py'
JAVA = ROOT / 'patches/dfroot/legacy-ksu/android-service'


def imported(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class C3UBackgroundServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patch = imported(PATCH, 'c3u_service_migrator')

    def template(self, name: str) -> str:
        return (JAVA / name).read_text()

    def test_legacy_native_path_and_runner_are_immutable(self):
        immutable = self.patch.NATIVE_IMMUTABLE
        self.assertIn('app/src/main/jni/exp.c', immutable)
        self.assertIn('app/src/main/jni/bootstrap.c', immutable)
        self.assertIn('app/src/main/java/df/root/ExploitRunner.java', immutable)
        self.assertTrue(set(immutable).isdisjoint(self.patch.TRANSFORMS))
        self.assertIn('6de6222', (ROOT/'tools/build-dfroot.sh').read_text())

    def test_activity_refactor_happens_after_compiled_module_staging(self):
        build = (ROOT/'tools/build-dfroot.sh').read_text()
        self.assertLess(build.index('apply_stage.py'), build.index('apply_foreground_service.py'))
        self.assertLess(build.index('apply_foreground_service.py'), build.index('assembleRelease'))
        self.assertIn('verify-service-apk.py', build)
        self.assertIn('build-vidda-c3.sh', (ROOT/'.github/workflows/build-vidda-c3.yml').read_text())

    def test_root_modes_and_adb_intent_requires_explicit_choice(self):
        service = self.template('C3URootForegroundService.java')
        adb = self.template('C3UAdbRootActivity.java')
        self.assertIn('EXTRA_MODE = "mode"', service)
        self.assertIn('MODE_ROOT_ONLY = "root-only"', service)
        self.assertIn('MODE_KSUN = "ksun"', service)
        self.assertIn('getStringExtra(C3URootForegroundService.EXTRA_MODE)', adb)
        self.assertIn('if (!C3URootForegroundService.isValidMode(mode))', adb)
        self.assertIn('C3URootForegroundService.SOURCE_ADB', adb)
        self.assertIn('protected void onResume()', adb)
        self.assertNotIn('ExploitRunner.run(', adb)

    def test_sole_service_exploit_owner_and_one_shot_request(self):
        service = self.template('C3URootForegroundService.java')
        self.assertEqual(service.count('ExploitRunner.run('), 1)
        self.assertIn('new AtomicBoolean(false)', service)
        self.assertIn('RUNNING.compareAndSet(false, true)', service)
        self.assertIn('START_NOT_STICKY', service)
        self.assertIn('startForeground(', service)
        self.assertIn('getBoolean(ExploitRunner.PREF_SOFT_REBOOT, false)', service)
        self.assertIn('Files.deleteIfExists(request.toPath());', service)
        self.assertIn('if (!MODE_KSUN.equals(mode) || !nativeAttemptStarted)', service)
        self.assertIn('ExploitRunner.c3uBootId()', service)
        self.assertIn('C3URootManager.selectForRun', service)

    def test_autoselects_exact_ksun_manager_but_retains_manual_mode(self):
        manager = self.template('C3URootManager.java')
        self.assertIn('com.rifsxd.ksunext', manager)
        self.assertIn('getApplicationInfo(KSU_NEXT_PACKAGE, 0)', manager)
        self.assertIn('boolean mustUseKsuNext = unattended', manager)
        self.assertIn('commit()', manager)
        self.assertIn('refusing unattended rooting', manager)
        self.assertNotIn('getInstalledApplications(', manager)
        self.assertIn('isKsuNextAvailable', PATCH.read_text())

    def test_boot_is_opt_in_and_root_only_default_and_no_double_boot(self):
        boot = self.template('BootReceiver.java')
        prefs = (ROOT/'patches/dfroot/legacy-ksu/apply_foreground_service.py').read_text()
        self.assertIn('if (!Intent.ACTION_BOOT_COMPLETED.equals(action)) return;', boot)
        self.assertIn('c3u_last_boot_attempt', boot)
        self.assertIn('"c3u_boot_full_ksu", false', boot)
        self.assertIn('C3URootForegroundService.MODE_ROOT_ONLY', boot)
        self.assertIn('SOURCE_BOOT', boot)
        self.assertIn('android:key="c3u_boot_full_ksu"', prefs)

    def test_android_14_fgs_protection_and_manifest(self):
        src = """<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.QUERY_ALL_PACKAGES" />
    <application>
        <activity
            android:name=".SettingsActivity" />
    </application>
</manifest>"""
        result = self.patch.manifest(src)
        self.assertIn('android:permission="android.permission.DUMP"', result)
        self.assertIn('android:foregroundServiceType="specialUse"', result)
        self.assertIn('android.permission.FOREGROUND_SERVICE_SPECIAL_USE', result)
        self.assertIn('android:exported="false"', result)
        import xml.etree.ElementTree as ET
        document = ET.fromstring(result)
        ns = '{http://schemas.android.com/apk/res/android}'
        service = document.find('./application/service')
        self.assertEqual(service.attrib[ns + 'exported'], 'false')
        activity = next(x for x in document.findall('./application/activity')
                        if x.attrib[ns + 'name'] == '.C3UAdbRootActivity')
        self.assertEqual(activity.attrib[ns + 'permission'], 'android.permission.DUMP')

    def test_log_can_be_read_after_activity_closes(self):
        service = self.template('C3URootForegroundService.java')
        log = self.template('C3URootLog.java')
        self.assertIn('c3u-root-operation.log', log)
        self.assertIn('createDeviceProtectedStorageContext()', log)
        self.assertIn('C3URootLog.append(', service)
        self.assertIn('C3URootLog.read(', PATCH.read_text())

    def test_fail_closed_on_changed_source_or_existing_class(self):
        with self.assertRaises(ValueError):
            self.patch.once('wrong', 'desired', 'replacement', 'test')
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            (path/'app/src/main/java/df/root').mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, 'Unexpected legacy'):
                self.patch.apply(path, JAVA)

    def test_final_apk_verifier_rejects_missing_classes(self):
        tool = imported(ROOT/'tools/verify-service-apk.py', 'c3u_service_dex_verifier')
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'app.apk'
            with zipfile.ZipFile(p, 'w') as z:
                z.writestr('classes.dex', b'none')
                z.writestr('AndroidManifest.xml', b'placeholder')
            with self.assertRaisesRegex(ValueError, 'missing in final DEX'):
                tool.verify(p)
            with zipfile.ZipFile(p, 'w') as z:
                z.writestr('classes.dex', b'\0'.join(tool.DEX_CLASSES + tool.DEX_STRINGS))
                z.writestr('AndroidManifest.xml', b'placeholder')
            tool.verify(p)


if __name__ == '__main__':
    unittest.main()
