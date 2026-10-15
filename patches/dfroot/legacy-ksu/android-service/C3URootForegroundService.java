package df.root;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.os.IBinder;
import android.os.PowerManager;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/** The *only* owner of the original DFRoot IPsec/native exploit operation. */
public final class C3URootForegroundService extends Service {
    public static final String EXTRA_MODE = "mode";
    public static final String EXTRA_SOURCE = "df.root.extra.SOURCE";
    public static final String MODE_ROOT_ONLY = "root-only";
    public static final String MODE_KSUN = "ksun";
    public static final String SOURCE_UI = "ui";
    public static final String SOURCE_ADB = "adb";
    public static final String SOURCE_BOOT = "boot";

    private static final String CHANNEL_ID = "c3u-root-progress";
    private static final int NOTIFICATION_ID = 5396;
    private static final AtomicBoolean RUNNING = new AtomicBoolean(false);

    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    public static boolean isRunning() { return RUNNING.get(); }

    public static boolean isValidMode(String mode) {
        return MODE_ROOT_ONLY.equals(mode) || MODE_KSUN.equals(mode);
    }

    public static void start(Context context, String mode, String source) {
        if (!isValidMode(mode)) throw new IllegalArgumentException("Unknown root mode: " + mode);
        if (!SOURCE_UI.equals(source) && !SOURCE_ADB.equals(source) && !SOURCE_BOOT.equals(source))
            throw new IllegalArgumentException("Unknown root source: " + source);
        Intent intent = new Intent(context, C3URootForegroundService.class);
        intent.putExtra(EXTRA_MODE, mode);
        intent.putExtra(EXTRA_SOURCE, source);
        context.startForegroundService(intent);
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String mode = intent == null ? null : intent.getStringExtra(EXTRA_MODE);
        String source = intent == null ? null : intent.getStringExtra(EXTRA_SOURCE);
        if (!isValidMode(mode) || (!SOURCE_UI.equals(source)
                && !SOURCE_ADB.equals(source) && !SOURCE_BOOT.equals(source))) {
            C3URootLog.append(this, "Rejected malformed foreground-service request\n");
            stopSelfResult(startId);
            return START_NOT_STICKY;
        }
        if (!RUNNING.compareAndSet(false, true)) {
            C3URootLog.append(this, "Another root operation is already in progress; ignored\n");
            return START_NOT_STICKY;
        }
        try {
            NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            manager.createNotificationChannel(new NotificationChannel(
                    CHANNEL_ID, "Vidda C3 root operation", NotificationManager.IMPORTANCE_LOW));
            Intent viewIntent = new Intent(this, MainActivity.class);
            PendingIntent tap = PendingIntent.getActivity(this, 0, viewIntent,
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            Notification notice = new Notification.Builder(this, CHANNEL_ID)
                    .setContentTitle("Vidda C3 Root")
                    .setContentText(MODE_KSUN.equals(mode) ? "Root + KernelSU running" : "Temporary root running")
                    .setSmallIcon(R.mipmap.ic_launcher)
                    .setContentIntent(tap)
                    .setOngoing(true)
                    .build();
            startForeground(NOTIFICATION_ID, notice, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        } catch (Exception e) {
            RUNNING.set(false);
            C3URootLog.append(this, "Foreground service could not start: " + e + "\n");
            stopSelfResult(startId);
            return START_NOT_STICKY;
        }
        executor.execute(() -> performRoot(mode, source));
        return START_NOT_STICKY; // Never replay the exploit after process recreation.
    }

    private void performRoot(String mode, String source) {
        Context de = createDeviceProtectedStorageContext();
        PowerManager.WakeLock lock = null;
        File request = ExploitRunner.c3uRequestFile(de);
        // The kernel bootstrap may start AFTER runBinary() exits; never delete
        // a successfully requested flag before the native stage consumes it.
        boolean nativeAttemptStarted = false;
        try {
            C3URootLog.clear(de);
            IReporter report = msg -> C3URootLog.append(de, msg);
            report.report("START: " + mode + " via " + source + "\n");
            // A stale request must never turn a temporary-root attempt into a KSU load.
            Files.deleteIfExists(request.toPath());
            if (new File("/dev/df").exists()) {
                report.report("DFRoot already attempted this boot (/dev/df exists); not retrying\n");
                return;
            }
            C3URootManager.selectForRun(de, mode, source, report);
            if (MODE_KSUN.equals(mode)) {
                SharedPreferences prefs = de.getSharedPreferences(ExploitRunner.PREFS_NAME,
                        Context.MODE_PRIVATE);
                if (prefs.getBoolean(ExploitRunner.PREF_SOFT_REBOOT, false)) {
                    throw new IllegalStateException("Disable Soft Reboot before KernelSU loading");
                }
                Files.write(request.toPath(), (ExploitRunner.c3uBootId() + "\n")
                        .getBytes(StandardCharsets.US_ASCII));
                report.report("Opt-in KernelSU request recorded for this boot only\n");
            } else {
                report.report("Temporary root only: no KernelSU module injection\n");
            }

            PowerManager power = (PowerManager) getSystemService(POWER_SERVICE);
            lock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "dfroot:c3u-root-service");
            lock.acquire(10 * 60 * 1000L);
            nativeAttemptStarted = true;
            int rc = ExploitRunner.run(de, report);
            report.report("ExploitRunner returned " + rc + "\n");
            if (MODE_KSUN.equals(mode)) {
                // Bootstrap runs asynchronously after the first-stage native process
                // completes. These markers are the relevant authoritative observations.
                report.report("KernelSU completion is confirmed by /dev/dfki1 and /dev/dfkl1, not this return code\n");
            }
        } catch (Exception e) {
            C3URootLog.append(de, "Root operation failed: " + e + "\n");
        } finally {
            // For full mode, leave the boot-ID marker for the asynchronously
            // launched privileged bootstrap to atomically unlink. On the next
            // attempt we delete it before doing anything, and an old boot ID
            // can never be accepted on a different boot.
            if (!MODE_KSUN.equals(mode) || !nativeAttemptStarted) {
                try { Files.deleteIfExists(request.toPath()); }
                catch (Exception e) { C3URootLog.append(de, "Cannot remove request: " + e + "\n"); }
            }
            if (lock != null && lock.isHeld()) lock.release();
            RUNNING.set(false);
            stopForeground(STOP_FOREGROUND_REMOVE);
            stopSelf();
        }
    }

    @Override
    public void onDestroy() {
        executor.shutdown();
        super.onDestroy();
    }
}
