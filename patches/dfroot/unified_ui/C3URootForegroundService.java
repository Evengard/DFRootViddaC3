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
 * Single owner of DFRoot's native exploit for BOTH the visible UI Root button
 * and the permission-gated ADB launcher. Never dispatches UI clicks.
 *
 * Upstream ExploitRunner.run(Context, IReporter) owns all IPsec resources,
 * native process lifetime, and cleanup; its Context is device-protected.
 */
public final class C3URootForegroundService extends Service implements IReporter {
    public static final String ACTION_START_UI = "df.root.c3u.START_FROM_UI";
    public static final String ACTION_START_ADB = "df.root.c3u.START_FROM_ADB";

    private static final String TAG = "C3URootService";
    private static final String CHANNEL = "c3u_root_operation";
    private static final int NOTICE_ID = 27014;
    private static final long TOKEN_TTL_MS = 30_000L;
    private static final long RETRIGGER_GUARD_MS = 180_000L;
    private static final long WAKELOCK_MAX_MS = 10 * 60_000L;
    private static final AtomicBoolean ACTIVE = new AtomicBoolean(false);

    private final ExecutorService executor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "c3u-dirtyfrag-worker");
        t.setDaemon(false);
        return t;
    });
    private PowerManager.WakeLock wakeLock;
    private boolean foregroundReady;

    public static boolean isRunning() { return ACTIVE.get(); }

    @Override public void onCreate() {
        super.onCreate();
        try {
            NotificationManager nm =
                    (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (Build.VERSION.SDK_INT >= 26) {
                NotificationChannel channel = new NotificationChannel(
                        CHANNEL, "DFRoot C3U operation", NotificationManager.IMPORTANCE_LOW);
                channel.setDescription("Root operation (UI or trusted ADB request)");
                nm.createNotificationChannel(channel);
            }
            Notification.Builder builder = Build.VERSION.SDK_INT >= 26
                    ? new Notification.Builder(this, CHANNEL)
                    : new Notification.Builder(this);
            Notification note = builder.setSmallIcon(android.R.drawable.stat_sys_download)
                    .setContentTitle("DFRoot C3U")
                    .setContentText("Root operation in progress")
                    .setOngoing(true).setOnlyAlertOnce(true).build();
            if (Build.VERSION.SDK_INT >= 34) {
                startForeground(NOTICE_ID, note,
                        ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
            } else {
                startForeground(NOTICE_ID, note);
            }
            foregroundReady = true;
            Log.i(TAG, "FOREGROUND_ACTIVE");
        } catch (RuntimeException e) {
            Log.e(TAG, "FOREGROUND_FAILED: refusing to run exploit", e);
            stopSelf();
        }
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (!foregroundReady) {
            if (!ACTIVE.get()) stopSelf();
            return START_NOT_STICKY;
        }
        if (ACTIVE.get()) {
            Log.w(TAG, "ALREADY_RUNNING: refusing duplicate UI/ADB request");
            C3URootLog.append(this, "ALREADY_RUNNING: duplicate request ignored\n");
            return START_NOT_STICKY;
        }
        String origin = authorizeAndReserve(intent);
        if (origin == null) {
            Log.e(TAG, "REQUEST_REJECTED: bad token, firmware, or repeat attempt");
            stopForeground(STOP_FOREGROUND_REMOVE);
            stopSelf();
            return START_NOT_STICKY;
        }
        if (!ACTIVE.compareAndSet(false, true)) {
            Log.w(TAG, "ALREADY_RUNNING: another worker claimed root attempt");
            return START_NOT_STICKY;
        }
        C3URootLog.begin(this, origin);
        record("FOREGROUND_ACTIVE: " + origin + " request accepted");
        try {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            if (pm == null) throw new IllegalStateException("PowerManager unavailable");
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "dfroot:c3u-service");
            wakeLock.acquire(WAKELOCK_MAX_MS);
            record("ROOT_WORKER_STARTED: ExploitRunner owns IPsec and native process");
            executor.execute(this::runRootAttempt);
        } catch (RuntimeException e) {
            Log.e(TAG, "WORKER_START_FAILED", e);
            C3URootLog.append(this, "WORKER_START_FAILED: " + e + "\n");
            ACTIVE.set(false);
            releaseWakeLock();
            stopForeground(STOP_FOREGROUND_REMOVE);
            stopSelf();
        }
        return START_NOT_STICKY;
    }

    /** Returns UI or ADB on approval, null on refusal. Service is non-exported. */
    private String authorizeAndReserve(Intent intent) {
        if (intent == null) return null;
        String action = intent.getAction();
        boolean fromUi = ACTION_START_UI.equals(action);
        boolean fromAdb = ACTION_START_ADB.equals(action);
        if (!fromUi && !fromAdb) return null;

        SharedPreferences prefs = getSharedPreferences(C3UAdbRootActivity.PREF, MODE_PRIVATE);
        if (fromAdb) {
            String supplied = intent.getStringExtra(C3UAdbRootActivity.EXTRA_NONCE);
            String expected = prefs.getString(C3UAdbRootActivity.KEY_NONCE, null);
            long issued = prefs.getLong(C3UAdbRootActivity.KEY_AT, -1L);
            // ADB token is issued only by the permission-gated launcher Activity.
            if (!prefs.edit().remove(C3UAdbRootActivity.KEY_NONCE)
                    .remove(C3UAdbRootActivity.KEY_AT).commit()) return null;
            long now = SystemClock.elapsedRealtime();
            if (supplied == null || supplied.length() != 48 || !supplied.equals(expected)
                    || issued < 0 || now < issued || now - issued > TOKEN_TTL_MS) return null;
        }
        try {
            if (!C3UAdbRootActivity.TARGET_FP.equals(Build.FINGERPRINT)
                    || !C3UAdbRootActivity.TARGET_KERNEL.equals(
                            C3UAdbRootActivity.readKernelRelease())) return null;
        } catch (Exception e) {
            Log.e(TAG, "FIRMWARE_CHECK_FAILED", e);
            return null;
        }
        if (new File("/dev/df").exists()) {
            Log.w(TAG, "SKIPPED_ALREADY_ARMED: exploit already attempted this boot");
            return null;
        }
        long now = SystemClock.elapsedRealtime();
        long previous = prefs.getLong("last_attempt_at", -1L);
        if (previous >= 0 && now >= previous && now - previous < RETRIGGER_GUARD_MS) {
            Log.w(TAG, "SKIPPED_TOO_SOON: waiting for previous attempt to settle");
            return null;
        }
        if (!prefs.edit().putLong("last_attempt_at", now).commit()) return null;
        return fromUi ? "UI" : "ADB";
    }

    private void runRootAttempt() {
        try {
            int rc = ExploitRunner.run(createDeviceProtectedStorageContext(), this);
            record("NATIVE_DONE: exit_code=" + rc);
            boolean moduleVisible = new File("/sys/module/kernelsu").isDirectory();
            if (!moduleVisible) moduleVisible = containsKernelSuInProcModules();
            record("ROOT_RESULT: native_rc=" + rc + " kernelsu_visible=" + moduleVisible
                    + " (su authorization must be verified separately)");
        } catch (Exception e) {
            Log.e(TAG, "ROOT_FAILED", e);
            C3URootLog.append(this, "ROOT_FAILED: " + e + "\n");
        } finally {
            releaseWakeLock();
            ACTIVE.set(false);
            record("ROOT_WORKER_FINISHED");
            stopForeground(STOP_FOREGROUND_REMOVE);
            // A duplicate onStartCommand may have arrived with a later startId.
            // stopSelfResult(originalId) would leave this service running.
            stopSelf();
        }
    }

    private boolean containsKernelSuInProcModules() {
        try (BufferedReader reader = new BufferedReader(new FileReader("/proc/modules"))) {
            for (String line; (line = reader.readLine()) != null; ) {
                if (line.startsWith("kernelsu ")) return true;
            }
        } catch (Exception e) {
            Log.w(TAG, "MODULE_STATUS_UNAVAILABLE", e);
        }
        return false;
    }

    private void record(String msg) {
        Log.i(TAG, msg);
        C3URootLog.append(this, msg + "\n");
    }

    @Override public void report(String msg) {
        if (msg != null) {
            Log.i(TAG, "EXPLOIT: " + msg.trim());
            C3URootLog.append(this, msg);
        }
    }

    private void releaseWakeLock() {
        if (wakeLock != null) {
            try { if (wakeLock.isHeld()) wakeLock.release(); }
            catch (RuntimeException e) { Log.w(TAG, "WAKELOCK_RELEASE_FAILED", e); }
            wakeLock = null;
        }
    }

    @Override public void onDestroy() {
        releaseWakeLock();
        executor.shutdown();
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
