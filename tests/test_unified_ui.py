"""Regression tests: both UI and ADB use the same foreground exploit worker.

The full, exact upstream v3.1 sources are fetched by CI. The sample below
exercises the same Root-button and reporter method shapes without vendoring
upstream implementation files into this repository.
"""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT/'patches/dfroot/overlay'
WORKER = ROOT/'patches/dfroot/service_worker'
UNIFIED = ROOT/'patches/dfroot/unified_ui'


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem + '_test', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BASE = load(OVERLAY/'apply_adb_intent.py')
WORK = load(OVERLAY/'apply_service_worker.py')
UI = load(OVERLAY/'apply_unified_ui.py')
MAIN_SAMPLE = '''package df.root;
import android.content.Intent;
import android.os.Bundle;
import android.util.Log;
import android.view.View;
import java.io.File;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;
public class MainActivity extends android.app.Activity implements IReporter {
    private static final String TAG = "dfroot";
    private final Executor mExec = Executors.newSingleThreadExecutor();
    private android.os.Handler mMain;
    private ViewBinder binding;
    @Override
    public void report(String msg) {
        Log.i(TAG, msg.trim());
        mMain.post(() -> {
            binding.outputView.append(msg);
            binding.outputScroll.post(() -> binding.outputScroll.fullScroll(View.FOCUS_DOWN));
        });
    }
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(42);
        binding.btnRun.setOnClickListener(v -> {
            binding.btnRun.setEnabled(false);
            binding.outputView.setText("");
            mExec.execute(this::runExploit);
        });
    }
    private void runExploit() {
        try { int rc = ExploitRunner.run(this, this); }
        catch (Exception ex) { report(ex.toString()); }
    }
}
'''
RUNNER_SAMPLE = '''package df.root;
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


class UnifiedUIIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        dest = self.repo/'app/src/main/java/df/root'
        dest.mkdir(parents=True)
        (dest/'MainActivity.java').write_text(MAIN_SAMPLE)
        (dest/'ExploitRunner.java').write_text(RUNNER_SAMPLE)
        (dest/'IReporter.java').write_text('package df.root; interface IReporter {void report(String msg);}')
        (self.repo/'app/src/main/AndroidManifest.xml').write_text('''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="df.root">
        <application><activity android:name=".MainActivity" android:exported="true"/></application>
        </manifest>''')
        digest = hashlib.sha256(RUNNER_SAMPLE.encode()).hexdigest()
        old_work, old_ui = WORK.UPSTREAM_RUNNER_SHA256, UI.EXPECTED_RUNNER_SHA256
        WORK.UPSTREAM_RUNNER_SHA256 = UI.EXPECTED_RUNNER_SHA256 = digest
        self.addCleanup(setattr, WORK, 'UPSTREAM_RUNNER_SHA256', old_work)
        self.addCleanup(setattr, UI, 'EXPECTED_RUNNER_SHA256', old_ui)
        BASE.patch(self.repo, OVERLAY)
        WORK.patch(self.repo, WORKER)

    def test_ui_and_adb_unified_with_persistent_log(self):
        UI.patch(self.repo, UNIFIED)
        java = self.repo/'app/src/main/java/df/root'
        main=(java/'MainActivity.java').read_text()
        svc=(java/'C3URootForegroundService.java').read_text()
        launcher=(java/'C3UAdbRootActivity.java').read_text()
        self.assertIn('C3U_UNIFIED_ROOT_UI', main)
        self.assertIn('ACTION_START_UI', main)
        self.assertIn('startForegroundService(service)', main)
        self.assertNotIn('ExploitRunner.run(', main)
        self.assertNotIn('mExec.execute(', main)
        self.assertNotIn('private void runExploit()', main)
        self.assertIn('C3URootLog.read(MainActivity.this)', main)
        self.assertIn('onStart()', main)
        self.assertIn('onStop()', main)
        self.assertIn('C3URootLog.append(this, msg)', svc)
        self.assertIn('ExploitRunner.run(createDeviceProtectedStorageContext(), this)', svc)
        self.assertIn('ACTION_START_UI', svc)
        self.assertIn('ACTION_START_ADB', svc)
        self.assertIn('ALREADY_RUNNING', svc)
        self.assertIn('AtomicBoolean ACTIVE', svc)
        self.assertIn('stopSelf();', svc)
        self.assertIn('setAction(C3URootForegroundService.ACTION_START_ADB)', launcher)
        self.assertTrue((java/'C3URootLog.java').is_file())
        self.assertIn('new FileOutputStream(file, append)', (java/'C3URootLog.java').read_text())
        manifest=(self.repo/'app/src/main/AndroidManifest.xml').read_text()
        self.assertIn('android:exported="false"', manifest)
        self.assertIn('android.permission.DUMP', manifest)

    def test_idempotent_patch(self):
        UI.patch(self.repo, UNIFIED)
        java=self.repo/'app/src/main/java/df/root'
        before={p.name:p.read_bytes() for p in java.glob('*.java')}
        UI.patch(self.repo, UNIFIED)
        self.assertEqual(before,{p.name:p.read_bytes() for p in java.glob('*.java')})

    def test_fails_closed_if_root_handler_changed(self):
        p=self.repo/'app/src/main/java/df/root/MainActivity.java'
        p.write_text(p.read_text().replace('mExec.execute(this::runExploit)', 'mExec.execute(() -> runExploit())'))
        before=p.read_bytes()
        with self.assertRaises(ValueError): UI.patch(self.repo, UNIFIED)
        self.assertEqual(before, p.read_bytes())
        self.assertFalse(p.with_name('C3URootLog.java').exists())

    def test_fails_closed_if_service_exported(self):
        p=self.repo/'app/src/main/AndroidManifest.xml'
        m=p.read_text().replace('android:exported="false"', 'android:exported="true"')
        p.write_text(m)
        with self.assertRaises(ValueError): UI.patch(self.repo, UNIFIED)

if __name__=='__main__': unittest.main()
