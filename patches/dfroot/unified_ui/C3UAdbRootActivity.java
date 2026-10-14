package df.root;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.Bundle;
import android.os.SystemClock;
import android.util.Log;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.security.SecureRandom;

/**
 * ADB-only, briefly visible entrypoint for a one-shot service-owned operation.
 * The manifest gates this exported Activity with android.permission.DUMP.
 * It does NOT open MainActivity or perform UI clicks.
 */
public final class C3UAdbRootActivity extends Activity {
    static final String TAG = "C3UAdbRoot";
    static final String PREF = "c3u_adb_root_gate";
    static final String KEY_NONCE = "nonce";
    static final String KEY_AT = "issued_at";
    static final String EXTRA_NONCE = "df.root.c3u.ADB_ROOT_NONCE";
    static final String TARGET_FP =
            "Hisense/VIDAA_TV/MT9655:14/UQ1A.240105.004.A1/07.02.70.202512281739:user/release-keys";
    static final String TARGET_KERNEL =
            "5.15.148-android14-11-g7b7674251b5d-dirty";

    private String pendingNonce;
    private boolean requested;

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        try {
            if (!TARGET_FP.equals(Build.FINGERPRINT)
                    || !TARGET_KERNEL.equals(readKernelRelease())) {
                Log.e(TAG, "REFUSED_FIRMWARE: unsupported fingerprint or kernel");
                finish();
                return;
            }
            if (new File("/dev/df").exists()) {
                Log.w(TAG, "SKIPPED_ALREADY_ARMED: exploit is one-shot per boot");
                finish();
                return;
            }
            byte[] bytes = new byte[24];
            new SecureRandom().nextBytes(bytes);
            StringBuilder nonce = new StringBuilder(48);
            for (byte b : bytes) {
                nonce.append(Character.forDigit((b >>> 4) & 15, 16));
                nonce.append(Character.forDigit(b & 15, 16));
            }
            pendingNonce = nonce.toString();
            SharedPreferences prefs = getSharedPreferences(PREF, MODE_PRIVATE);
            if (!prefs.edit().putString(KEY_NONCE, pendingNonce)
                    .putLong(KEY_AT, SystemClock.elapsedRealtime()).commit()) {
                Log.e(TAG, "REFUSED_STORAGE: token not saved");
                pendingNonce = null;
                finish();
            }
        } catch (Exception e) {
            Log.e(TAG, "REQUEST_FAILED", e);
            finish();
        }
    }

    @Override protected void onResume() {
        super.onResume();
        if (requested || pendingNonce == null) return;
        requested = true;
        try {
            // Start from the visible Activity to satisfy Android 12+ FGS rules.
            Intent service = new Intent(this, C3URootForegroundService.class);
            service.setAction(C3URootForegroundService.ACTION_START_ADB);
            service.putExtra(EXTRA_NONCE, pendingNonce);
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(service);
            else startService(service);
            Log.i(TAG, "FGS_REQUESTED: service owns root worker; no UI interaction");
        } catch (RuntimeException e) {
            getSharedPreferences(PREF, MODE_PRIVATE).edit()
                    .remove(KEY_NONCE).remove(KEY_AT).commit();
            Log.e(TAG, "FGS_START_REFUSED", e);
        } finally {
            // The service stays alive (stopWithTask=false), even after this UI closes.
            finish();
        }
    }

    static String readKernelRelease() throws Exception {
        try (BufferedReader reader = new BufferedReader(
                new FileReader("/proc/sys/kernel/osrelease"))) {
            return reader.readLine().trim();
        }
    }
}
