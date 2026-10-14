package df.root;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Binder;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;

import java.io.File;

/**
 * Android 14-compatible foreground process holder for a *single* authorized
 * DFRoot root attempt. The actual exploit remains in MainActivity's existing
 * Root action; moving it into a service would require refactoring IpSecManager
 * and DFRoot's activity-dependent code rather than invoking the UI control.
 *
 * This class never executes a shell or kernel module; it observes only stage
 * markers and keeps the process foreground while native bootstrap runs.
 */
public final class C3URootForegroundService extends Service {
    private static final String TAG = "C3URootService";
    private static final String CHANNEL = "c3u_root_operation";
    private static final int NOTICE_ID = 27014;
    private static final long POLL_MS = 2_000L;
    private static final long MAX_MS = 240_000L;
    private static final long STABILIZE_MS = 30_000L;

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final LocalBinder localBinder = new LocalBinder();

    /** Internal-only readiness acknowledgment for the launcher Activity. */
    public final class LocalBinder extends Binder {
        public boolean isForegroundReady() { return foregroundReady; }
    }
    private boolean running;
    private boolean foregroundReady;
    private long beganAt;
    private long firstModuleSeenAt = -1L;
    private int lastStage = -1;
    private final Runnable watcher = new Runnable() {
        @Override public void run() {
            if (!running) return;
            long now = SystemClock.elapsedRealtime();
            long elapsed = now - beganAt;
            int stage = 0;
            if (new File("/dev/df").exists()) stage = 1;
            if (new File("/dev/dfm1").exists()) stage = 2;
            if (new File("/dev/dfm6").exists()) stage = 3;
            if (new File("/sys/module/kernelsu").isDirectory()) stage = 4;
            if (stage != lastStage) {
                lastStage = stage;
                Log.i(TAG, "STAGE_" + stage + ": observed stage markers; not proof of SU access");
            }
            if (stage == 4) {
                if (firstModuleSeenAt < 0) firstModuleSeenAt = now;
                if (now - firstModuleSeenAt >= STABILIZE_MS) {
                    Log.i(TAG, "MODULE_VISIBLE_SETTLED: stopping FGS; check su -c id separately");
                    stopWatching();
                    return;
                }
            }
            if (elapsed >= MAX_MS) {
                Log.w(TAG, "FGS_TIMEOUT: stopping after 4 minutes; check logs and su manually");
                stopWatching();
                return;
            }
            mainHandler.postDelayed(this, POLL_MS);
        }
    };

    @Override public void onCreate() {
        super.onCreate();
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel c = new NotificationChannel(
                    CHANNEL, "DFRoot C3U operation", NotificationManager.IMPORTANCE_LOW);
            c.setDescription("Keeps DFRoot active during a manually requested root attempt");
            nm.createNotificationChannel(c);
        }
        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= 26) b = new Notification.Builder(this, CHANNEL);
        else b = new Notification.Builder(this);
        Notification n = b.setSmallIcon(android.R.drawable.stat_sys_download)
                .setContentTitle("DFRoot C3U")
                .setContentText("ADB-requested root operation in progress")
                .setOnlyAlertOnce(true)
                .setOngoing(true)
                .build();
        try {
            if (Build.VERSION.SDK_INT >= 34) {
                startForeground(NOTICE_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
            } else {
                startForeground(NOTICE_ID, n);
            }
            foregroundReady = true;
            Log.i(TAG, "FOREGROUND_ACTIVE: notification posted; rooting is not yet verified");
        } catch (RuntimeException e) {
            Log.e(TAG, "FOREGROUND_FAILED: unable to hold DFRoot foreground", e);
            stopSelf();
        }
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (!foregroundReady) {
            Log.e(TAG, "NO_FOREGROUND: refusing to watch exploit without valid FGS");
            stopSelf();
            return START_NOT_STICKY;
        }
        if (!running) {
            running = true;
            beganAt = SystemClock.elapsedRealtime();
            Log.i(TAG, "WATCH_STARTED: maximum 4 minutes, non-sticky");
            mainHandler.post(watcher);
        } else {
            Log.w(TAG, "ALREADY_RUNNING: rejecting duplicate observation request");
        }
        return START_NOT_STICKY;
    }

    private void stopWatching() {
        if (!running) return;
        running = false;
        mainHandler.removeCallbacks(watcher);
        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
    }

    @Override public void onDestroy() {
        running = false;
        mainHandler.removeCallbacks(watcher);
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return localBinder; }
}
