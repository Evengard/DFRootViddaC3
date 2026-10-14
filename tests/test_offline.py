import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('c3u_updater', ROOT/'tools/check-upstream.py')
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)

class TestUpdater(unittest.TestCase):
    def test_new_stable(self):
        self.assertEqual(updater.candidate('v3.4.1', {'tag_name':'v3.5.0', 'draft':False, 'prerelease':False}), 'v3.5.0')
    def test_same(self):
        self.assertIsNone(updater.candidate('v3.4.1', {'tag_name':'v3.4.1'}))
    def test_no_downgrades(self):
        self.assertIsNone(updater.candidate('v3.4.1', {'tag_name':'v3.4.0'}))
    def test_no_prerelease(self):
        self.assertIsNone(updater.candidate('v3.4.1', {'tag_name':'v3.5.0', 'prerelease':True}))
    def test_invalid_ref_fails_closed(self):
        with self.assertRaises(ValueError):
            updater.candidate('dev', {'tag_name':'v3.5.0'})
    def test_config_verifier(self):
        spec2 = importlib.util.spec_from_file_location('c3u_verifier', ROOT/'tools/validate-repo.py')
        verifier = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(verifier)
        self.assertTrue(verifier.validate(json.loads((ROOT/'config/upstreams.json').read_text())))
    def test_adb_intent_patch_is_protected_and_idempotent(self):
        spec3 = importlib.util.spec_from_file_location('adb_patch',
                   ROOT/'patches/dfroot/overlay/apply_adb_intent.py')
        impl = importlib.util.module_from_spec(spec3)
        spec3.loader.exec_module(impl)
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            src = repo/'app/src/main/java/df/root'
            src.mkdir(parents=True)
            main = src/'MainActivity.java'
            main.write_text('''package df.root;
import android.os.Bundle;
public class MainActivity extends android.app.Activity {
    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(42);
    }
}
''')
            manifest = repo/'app/src/main/AndroidManifest.xml'
            manifest.write_text('''<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="df.root"><application><activity android:name=".MainActivity"
    android:exported="true" /></application></manifest>''')
            source_dir = ROOT/'patches/dfroot/overlay'
            impl.patch(repo, source_dir)
            impl.patch(repo, source_dir)
            self.assertEqual(main.read_text().count(impl.TAG), 1)
            self.assertEqual(manifest.read_text().count('android.permission.DUMP'), 1)
            self.assertTrue((src/'C3UAdbRootActivity.java').exists())
            self.assertTrue((src/'C3UAdbRootAction.java').exists())
            self.assertIn('FLAG_ACTIVITY_CLEAR_TASK', (src/'C3UAdbRootActivity.java').read_text())
            self.assertIn('SKIPPED_ALREADY_ARMED', (src/'C3UAdbRootAction.java').read_text())
            self.assertIn('startForegroundService(service)', (src/'C3UAdbRootActivity.java').read_text())
            self.assertIn('bindService(service, connected, Context.BIND_AUTO_CREATE)', (src/'C3UAdbRootActivity.java').read_text())
            self.assertIn('FGS_CONFIRMED', (src/'C3UAdbRootActivity.java').read_text())
            self.assertIn('FGS_HANDSHAKE_TIMEOUT', (src/'C3UAdbRootActivity.java').read_text())
            self.assertIn('LocalBinder extends Binder', (src/'C3URootForegroundService.java').read_text())
            self.assertIn('FOREGROUND_SERVICE_TYPE_SPECIAL_USE', (src/'C3URootForegroundService.java').read_text())
            self.assertIn('START_NOT_STICKY', (src/'C3URootForegroundService.java').read_text())
            self.assertIn('android:foregroundServiceType="specialUse"', manifest.read_text())
            self.assertIn('android:exported="false"', manifest.read_text())
            self.assertIn('android.permission.FOREGROUND_SERVICE_SPECIAL_USE', manifest.read_text())
            self.assertIn('Theme.Translucent.NoTitleBar', manifest.read_text())
            self.assertNotIn('Theme.NoDisplay', manifest.read_text())

    def test_adb_intent_patch_refuses_unsupported_activity(self):
        spec3 = importlib.util.spec_from_file_location('adb_patch',
                   ROOT/'patches/dfroot/overlay/apply_adb_intent.py')
        impl = importlib.util.module_from_spec(spec3)
        spec3.loader.exec_module(impl)
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            src = repo/'app/src/main/java/df/root'
            src.mkdir(parents=True)
            main = src/'MainActivity.java'
            original = ('package df.root;\n'
                        'public class MainActivity extends android.app.Activity { }\n')
            main.write_text(original)
            manifest = repo/'app/src/main/AndroidManifest.xml'
            original_manifest = '''<manifest xmlns:android="http://schemas.android.com/apk/res/android"
                package="df.root"><application/></manifest>'''
            manifest.write_text(original_manifest)
            with self.assertRaises(ValueError):
                impl.patch(repo, ROOT/'patches/dfroot/overlay')
            self.assertEqual(main.read_text(), original)
            self.assertEqual(manifest.read_text(), original_manifest)

    def test_fgs_patch_upgrades_existing_v2_manifest(self):
        spec = importlib.util.spec_from_file_location('adb_patch',
            ROOT/'patches/dfroot/overlay/apply_adb_intent.py')
        impl = importlib.util.module_from_spec(spec); spec.loader.exec_module(impl)
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            src = repo/'app/src/main/java/df/root'
            src.mkdir(parents=True)
            (src/'MainActivity.java').write_text('''package df.root;
class MainActivity extends android.app.Activity {
    void onCreate(android.os.Bundle state) { setContentView(1); }
}
''')
            manifest = repo/'app/src/main/AndroidManifest.xml'
            manifest.write_text('''<manifest xmlns:android="http://schemas.android.com/apk/res/android"
package="df.root"><application><activity android:name="df.root.C3UAdbRootActivity"
android:exported="true" android:permission="android.permission.DUMP"
android:theme="@android:style/Theme.NoDisplay"/></application></manifest>''')
            impl.patch(repo, ROOT/'patches/dfroot/overlay')
            text = manifest.read_text()
            self.assertIn('Theme.Translucent.NoTitleBar',text)
            self.assertEqual(text.count('android:name="df.root.C3UAdbRootActivity"'),1)
            self.assertEqual(text.count('android:name="df.root.C3URootForegroundService"'),1)
            self.assertEqual(text.count('android.permission.FOREGROUND_SERVICE_SPECIAL_USE'),1)
            self.assertEqual(text.count('android.permission.DUMP'),1)

    def test_fgs_patch_rejects_exported_service(self):
        spec = importlib.util.spec_from_file_location('adb_patch',
            ROOT/'patches/dfroot/overlay/apply_adb_intent.py')
        impl = importlib.util.module_from_spec(spec); spec.loader.exec_module(impl)
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            src = repo/'app/src/main/java/df/root'
            src.mkdir(parents=True)
            (src/'MainActivity.java').write_text('''package df.root;
class MainActivity extends android.app.Activity {
    void onCreate(android.os.Bundle state) { setContentView(1); }
}
''')
            manifest = repo/'app/src/main/AndroidManifest.xml'
            original = '''<manifest xmlns:android="http://schemas.android.com/apk/res/android"
package="df.root"><application>
<service android:name="df.root.C3URootForegroundService" android:exported="true"
android:foregroundServiceType="specialUse"/>
</application></manifest>'''
            manifest.write_text(original)
            with self.assertRaises(ValueError):
                impl.patch(repo, ROOT/'patches/dfroot/overlay')
            self.assertEqual(manifest.read_text(), original)
            self.assertFalse((src/'C3UAdbRootActivity.java').exists())

    def test_patch_source_text(self):
        spec3=importlib.util.spec_from_file_location('c3u_patch', ROOT/'patches/ksunext/patch-selinux.py')
        patch=importlib.util.module_from_spec(spec3);spec3.loader.exec_module(patch)
        src=('int k(void) {\n    if (!getenforce()) {\n'
             '        pr_info("Permissive SELinux, enforcing\\n");\n'
             '        setenforce(true);\n    }\n}\n')
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'init.c';p.write_text(src)
            self.assertEqual(patch.patch_file(p), 'PATCHED')
            self.assertEqual(patch.patch_file(p), 'ALREADY_PATCHED')
            self.assertNotIn('setenforce(true);',p.read_text())
            self.assertIn('C3U: preserving permissive SELinux',p.read_text())

if __name__ == '__main__':
    unittest.main()
