package df.root;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.security.SecureRandom;

/**
 * ADB-shell-only launcher. The manifest protects this exported Activity with
 * android.permission.DUMP; the foreground service itself is NOT exported.
 *
 * Start the service only after the translucent Activity becomes visible,
 * bind locally, then launch the existing DFRoot UI *only after* it confirms
 * that startForeground() completed. Neither this Activity nor the service
 * reimplements the native DirtyFrag exploit.
 */
public final class C3UAdbRootActivity extends Activity {
    static final String TAG = "C3UAdbRoot";
    static final String PREF = "c3u_adb_root_gate";
    static final String KEY_NONCE = "nonce";
    static final String KEY_AT = "issued_at";
    static final String EXTRA_NONCE = "df.root.c3u.ADB_ROOT_NONCE";
    private static final String TARGET_FP =
            "Hisense/VIDAA_TV/MT9655:14/UQ1A.240105.004.A1/07.02.70.202512281739:user/release-keys";
    private static final String TARGET_KERNEL =
            "5.15.148-android14-11-g7b7674251b5d-dirty";

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private boolean requestReady;
    private boolean startRequested;
    private boolean bound;
    private boolean uiLaunched;
    private String nonce;
    private final Runnable timeout = () -> {
        if (startRequested && !uiLaunched) {
            Log.e(TAG, "FGS_HANDSHAKE_TIMEOUT: foreground service did not confirm readiness");
            abortRequest();
        }
    };

    private final ServiceConnection connected = new ServiceConnection() {
        @Override public void onServiceConnected(ComponentName name, IBinder binder) {
            if (uiLaunched || isFinishing()) return;
            if (!(binder instanceof C3URootForegroundService.LocalBinder)
                    || !((C3URootForegroundService.LocalBinder) binder).isForegroundReady()) {
                Log.e(TAG, "FGS_NOT_READY: refusing to start DFRoot exploit");
                abortRequest();
                return;
            }
            Log.i(TAG, "FGS_CONFIRMED: service promoted to foreground");
            launchRootUi();
        }
        @Override public void onServiceDisconnected(ComponentName name) {
            if (!uiLaunched) {
                Log.e(TAG, "FGS_DISCONNECTED: could not start root UI safely");
                abortRequest();
            }
        }
    };

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        try {
            if (!TARGET_FP.equals(Build.FINGERPRINT)) {
                Log.e(TAG, "REFUSED_FIRMWARE: non-C3U build fingerprint");
                finish(); return;
            }
            if (!TARGET_KERNEL.equals(readKernelRelease())) {
                Log.e(TAG, "REFUSED_KERNEL: unexpected kernel release");
                finish(); return;
            }
            if (new File("/dev/df").exists()) {
                Log.w(TAG, "SKIPPED_ALREADY_ARMED: /dev/df already exists");
                finish(); return;
            }
            byte[] random = new byte[24];
            new SecureRandom().nextBytes(random);
            StringBuilder buf = new StringBuilder(48);
            for (byte b : random) {
                buf.append(Character.forDigit((b >> 4) & 15, 16));
                buf.append(Character.forDigit(b & 15, 16));
            }
            nonce = buf.toString();
            SharedPreferences prefs = getSharedPreferences(PREF, MODE_PRIVATE);
            if (!prefs.edit().putString(KEY_NONCE, nonce)
                    .putLong(KEY_AT, SystemClock.elapsedRealtime()).commit()) {
                Log.e(TAG, "REFUSED_STORAGE: could not store one-time authorization");
                finish(); return;
            }
            requestReady = true;
        } catch (Exception e) {
            Log.e(TAG, "REQUEST_FAILED: " + e, e);
            finish();
        }
    }

    @Override protected void onResume() {
        super.onResume();
        if (!requestReady || startRequested) return;
        startRequested = true;
        try {
            // We are now in a visible Activity, satisfying Android 12+ FGS
            // launch restrictions; the former Theme.NoDisplay is insufficient.
            Intent service = new Intent(this, C3URootForegroundService.class);
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(service);
            else startService(service);
            bound = bindService(service, connected, Context.BIND_AUTO_CREATE);
            if (!bound) {
                Log.e(TAG, "FGS_BIND_FAILED: service unavailable");
                abortRequest();
                return;
            }
            mainHandler.postDelayed(timeout, 10_000L);
            Log.i(TAG, "FGS_REQUESTED: waiting for foreground readiness before root UI");
        } catch (RuntimeException e) {
            Log.e(TAG, "FGS_START_REFUSED: refusing unattended root action", e);
            abortRequest();
        }
    }

    private void launchRootUi() {
        if (uiLaunched || !requestReady) return;
        mainHandler.removeCallbacks(timeout);
        uiLaunched = true;
        try {
            Intent next = new Intent(this, MainActivity.class);
            next.putExtra(EXTRA_NONCE, nonce);
            next.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
            startActivity(next);
            Log.i(TAG, "REQUEST_ACCEPTED: foreground service active; existing DFRoot UI action requested");
        } catch (RuntimeException e) {
            Log.e(TAG, "ROOT_UI_LAUNCH_FAILED", e);
            getSharedPreferences(PREF, MODE_PRIVATE).edit()
                    .remove(KEY_NONCE).remove(KEY_AT).commit();
            stopService(new Intent(this, C3URootForegroundService.class));
        } finally {
            finish();
        }
    }

    private void abortRequest() {
        mainHandler.removeCallbacks(timeout);
        requestReady = false;
        getSharedPreferences(PREF, MODE_PRIVATE).edit()
                .remove(KEY_NONCE).remove(KEY_AT).commit();
        try { stopService(new Intent(this, C3URootForegroundService.class)); }
        catch (RuntimeException e) { Log.w(TAG, "FGS_STOP_FAILED: " + e); }
        finish();
    }

    @Override protected void onDestroy() {
        mainHandler.removeCallbacks(timeout);
        if (bound) {
            bound = false;
            try { unbindService(connected); }
            catch (RuntimeException e) { Log.w(TAG, "FGS_UNBIND_FAILED: " + e); }
        }
        super.onDestroy();
    }

    private static String readKernelRelease() throws Exception {
        try (BufferedReader reader = new BufferedReader(
                new FileReader("/proc/sys/kernel/osrelease"))) {
            return reader.readLine().trim();
        }
    }
}
