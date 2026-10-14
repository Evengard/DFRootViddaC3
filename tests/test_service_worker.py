"""Offline regression coverage for the service-owned DFRoot v3.1 overlay."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / 'patches/dfroot/overlay'
WORKER = ROOT / 'patches/dfroot/service_worker'


def load(name):
    p = OVERLAY / name
    spec = importlib.util.spec_from_file_location('c3u_' + name.replace('.', '_'), p)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

BASE_PATCH = load('apply_adb_intent.py')
WORKER_PATCH = load('apply_service_worker.py')
RUNNER = '''package df.root;
import android.content.Context;
class ExploitRunner {
  public static int run(Context ctx, IReporter reporter) throws Exception {
    IpSecManager ipsec = null;
    IpSecTransform transform = null;
    try { return runBinary(bin, reporter, 1, 2, new byte[]{1}, 3); }
    finally { transform.close(); spiObj.close(); encapSock.close(); }
  }
}
'''


class ServiceWorkerTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.repo = Path(self._td.name)
        java = self.repo/'app/src/main/java/df/root'
        java.mkdir(parents=True)
        (java/'MainActivity.java').write_text('''package df.root;
import android.os.Bundle;
class MainActivity extends android.app.Activity {
  protected void onCreate(Bundle state) { super.onCreate(state); setContentView(1); }
}
''')
        (java/'ExploitRunner.java').write_text(RUNNER)
        (self.repo/'app/src/main/AndroidManifest.xml').write_text('''<manifest xmlns:android="http://schemas.android.com/apk/res/android"
package="df.root"><application><activity android:name=".MainActivity"
android:exported="true" /></application></manifest>''')
        BASE_PATCH.patch(self.repo, OVERLAY)
        self.original_hash = WORKER_PATCH.UPSTREAM_RUNNER_SHA256
        WORKER_PATCH.UPSTREAM_RUNNER_SHA256 = hashlib.sha256(RUNNER.encode()).hexdigest()
        self.addCleanup(setattr, WORKER_PATCH, 'UPSTREAM_RUNNER_SHA256', self.original_hash)

    def test_worker_replaces_click_and_is_idempotent(self):
        WORKER_PATCH.patch(self.repo, WORKER)
        WORKER_PATCH.patch(self.repo, WORKER)
        java = self.repo/'app/src/main/java/df/root'
        self.assertNotIn(WORKER_PATCH.UI_HOOK,(java/'MainActivity.java').read_text())
        self.assertIn(WORKER_PATCH.OWNER_MARKER,(java/'MainActivity.java').read_text())
        self.assertFalse((java/'C3UAdbRootAction.java').exists())
        svc = (java/'C3URootForegroundService.java').read_text()
        act = (java/'C3UAdbRootActivity.java').read_text()
        self.assertIn('ExploitRunner.run(createDeviceProtectedStorageContext(), this)', svc)
        self.assertIn('startForeground(NOTICE_ID, note',svc)
        self.assertIn('wakeLock.acquire(WAKELOCK_MAX_MS)',svc)
        self.assertIn('executor.execute(() -> runRootAttempt(startId))',svc)
        self.assertIn('stopSelfResult(startId)',svc)
        self.assertIn('return START_NOT_STICKY;',svc)
        self.assertIn('FOREGROUND_ACTIVE',svc)
        self.assertNotIn('MainActivity.class',act)
        self.assertIn('service.putExtra(EXTRA_NONCE, pendingNonce)',act)
        self.assertIn('startForegroundService(service)',act)
        self.assertIn('android.permission.DUMP',(self.repo/'app/src/main/AndroidManifest.xml').read_text())

    def test_changed_upstream_refuses_without_modification(self):
        java = self.repo/'app/src/main/java/df/root'
        prev = (java/'MainActivity.java').read_bytes()
        WORKER_PATCH.UPSTREAM_RUNNER_SHA256='0'*64
        with self.assertRaises(ValueError):
            WORKER_PATCH.patch(self.repo, WORKER)
        self.assertEqual(prev, (java/'MainActivity.java').read_bytes())
        self.assertTrue((java/'C3UAdbRootAction.java').exists())

    def test_exported_service_fails_closed(self):
        manifest = self.repo/'app/src/main/AndroidManifest.xml'
        m = manifest.read_text().replace('android:exported="false"', 'android:exported="true"')
        manifest.write_text(m)
        with self.assertRaises(ValueError):
            WORKER_PATCH.patch(self.repo, WORKER)

if __name__ == '__main__':
    unittest.main()
