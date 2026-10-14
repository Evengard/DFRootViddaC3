package df.root;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import android.os.SystemClock;
import android.util.Log;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Service-owned DirtyFrag execution for upstream DFRoot v3.1.
 * ExploitRunner.run(Context, IReporter) already owns the IPsec resources,
 * stage assets, native worker process and try/finally resource cleanup.
 * No Activity/UI callback is needed after startForegroundService().
 */
public final class C3URootForegroundService extends Service implements IReporter {
    private static final String TAG = "C3URootService";
    private static final String CHANNEL = "c3u_root_operation";
    private static final int NOTICE_ID = 27014;
    private static final long TOKEN_TTL_MS = 30_000L;
    private static final long RETRIGGER_GUARD_MS = 180_000L;
    private static final long WAKELOCK_MAX_MS = 10 * 60_000L;

    private final AtomicBoolean working = new AtomicBoolean(false);
    private final ExecutorService executor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "c3u-dirtyfrag-worker");
        t.setDaemon(false);
        return t;
    });
    private PowerManager.WakeLock wakeLock;
    private boolean foregroundReady;

    @Override public void onCreate() {
        super.onCreate();
        try {
            NotificationManager nm =
                    (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (Build.VERSION.SDK_INT >= 26) {
                NotificationChannel channel = new NotificationChannel(
                        CHANNEL, "DFRoot C3U operation", NotificationManager.IMPORTANCE_LOW);
                channel.setDescription("Service-owned, ADB-requested root operation");
                nm.createNotificationChannel(channel);
            }
            Notification.Builder builder = Build.VERSION.SDK_INT >= 26
                    ? new Notification.Builder(this, CHANNEL)
                    : new Notification.Builder(this);
            Notification note = builder.setSmallIcon(android.R.drawable.stat_sys_download)
                    .setContentTitle("DFRoot C3U")
                    .setContentText("Preparing one-shot root operation")
                    .setOngoing(true).setOnlyAlertOnce(true).build();
            if (Build.VERSION.SDK_INT >= 34) {
                startForeground(NOTICE_ID, note,
                        ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
            } else {
                startForeground(NOTICE_ID, note);
            }
            foregroundReady = true;
            Log.i(TAG, "FOREGROUND_ACTIVE: about to authenticate root request");
        } catch (RuntimeException e) {
            Log.e(TAG, "FOREGROUND_FAILED: refusing to run exploit", e);
            stopSelf();
        }
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (!foregroundReady) {
            if (!working.get()) stopSelfResult(startId);
            return START_NOT_STICKY;
        }
        if (working.get()) {
            Log.w(TAG, "ALREADY_RUNNING: duplicate request ignored");
            return START_NOT_STICKY;
        }
        if (!acceptAndConsumeToken(intent)) {
            Log.e(TAG, "REFUSED_TOKEN_OR_FIRMWARE: no root operation started");
            stopForeground(STOP_FOREGROUND_REMOVE);
            stopSelfResult(startId);
            return START_NOT_STICKY;
        }
        if (!working.compareAndSet(false, true)) {
            Log.w(TAG, "ALREADY_RUNNING: duplicate worker refused");
            return START_NOT_STICKY;
        }
        try {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            if (pm == null) throw new IllegalStateException("PowerManager unavailable");
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "dfroot:c3u-service");
            wakeLock.acquire(WAKELOCK_MAX_MS);
            Log.i(TAG, "ROOT_WORKER_STARTED: service owns IPsec + native DFRoot process");
            executor.execute(() -> runRootAttempt(startId));
        } catch (RuntimeException e) {
            Log.e(TAG, "WORKER_START_FAILED", e);
            working.set(false);
            releaseWakeLock();
            stopForeground(STOP_FOREGROUND_REMOVE);
            stopSelfResult(startId);
        }
        return START_NOT_STICKY;
    }

    private boolean acceptAndConsumeToken(Intent intent) {
        SharedPreferences prefs = getSharedPreferences(C3UAdbRootActivity.PREF, MODE_PRIVATE);
        String supplied = intent == null ? null
                : intent.getStringExtra(C3UAdbRootActivity.EXTRA_NONCE);
        String expected = prefs.getString(C3UAdbRootActivity.KEY_NONCE, null);
        long issued = prefs.getLong(C3UAdbRootActivity.KEY_AT, -1L);
        // Consume atomically as far as this one-process application allows.
        if (!prefs.edit().remove(C3UAdbRootActivity.KEY_NONCE)
                .remove(C3UAdbRootActivity.KEY_AT).commit()) return false;
        long now = SystemClock.elapsedRealtime();
        if (supplied == null || supplied.length() != 48 || !supplied.equals(expected)
                || issued < 0 || now < issued || now - issued > TOKEN_TTL_MS) return false;
        try {
            if (!C3UAdbRootActivity.TARGET_FP.equals(Build.FINGERPRINT)
                    || !C3UAdbRootActivity.TARGET_KERNEL.equals(
                            C3UAdbRootActivity.readKernelRelease())) return false;
        } catch (Exception e) {
            Log.e(TAG, "KERNEL_RELEASE_UNAVAILABLE", e);
            return false;
        }
        if (new File("/dev/df").exists()) {
            Log.w(TAG, "SKIPPED_ALREADY_ARMED: refusing second exploit in same boot");
            return false;
        }
        long prior = prefs.getLong("last_attempt_at", -1L);
        if (prior >= 0 && now >= prior && now - prior < RETRIGGER_GUARD_MS) {
            Log.w(TAG, "SKIPPED_TOO_SOON: another attempt ran recently");
            return false;
        }
        return prefs.edit().putLong("last_attempt_at", now).commit();
    }

    private void runRootAttempt(int startId) {
        try {
            // Upstream's ExploitRunner manages IpSecManager and native process
            // lifetimes; it does not depend on a visible Activity.
            int rc = ExploitRunner.run(createDeviceProtectedStorageContext(), this);
            Log.i(TAG, "NATIVE_DONE: exit_code=" + rc);
            boolean moduleVisible = new File("/sys/module/kernelsu").isDirectory();
            if (!moduleVisible) moduleVisible = containsKernelSuInProcModules();
            Log.i(TAG, "ROOT_RESULT: native_rc=" + rc
                    + " kernelsu_visible=" + moduleVisible
                    + " (NOT a substitute for authorized su -c id)");
        } catch (Exception e) {
            Log.e(TAG, "ROOT_FAILED: exploit worker threw", e);
        } finally {
            releaseWakeLock();
            working.set(false);
            stopForeground(STOP_FOREGROUND_REMOVE);
            stopSelfResult(startId);
            Log.i(TAG, "ROOT_WORKER_FINISHED: foreground service stopped");
        }
    }

    private boolean containsKernelSuInProcModules() {
        try (BufferedReader reader = new BufferedReader(new FileReader("/proc/modules"))) {
            for (String line; (line = reader.readLine()) != null; ) {
                if (line.startsWith("kernelsu ")) return true;
            }
        } catch (Exception e) {
            Log.w(TAG, "MODULE_STATUS_UNAVAILABLE: " + e);
        }
        return false;
    }

    @Override public void report(String msg) {
        // Native output is diagnostic, not proof of successful root.
        if (msg != null) Log.i(TAG, "EXPLOIT: " + msg.trim());
    }

    private void releaseWakeLock() {
        if (wakeLock != null) {
            try { if (wakeLock.isHeld()) wakeLock.release(); }
            catch (RuntimeException e) { Log.w(TAG, "WAKELOCK_RELEASE_FAILED", e); }
            wakeLock = null;
        }
    }

    @Override public void onDestroy() {
        // Do not cancel an already running native operation; a forced service
        // teardown can interrupt the work, and no automatic retry is scheduled.
        releaseWakeLock();
        executor.shutdown();
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
