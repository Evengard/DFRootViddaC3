package df.root;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;

/** Boot root is opt-in in Settings. Never issue two exploit attempts per boot. */
public final class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null) return;
        String action = intent.getAction();
        // Wait for ordinary BOOT_COMPLETED so the installed Manager's extracted
        // libksud.so is visible. LOCKED_BOOT_COMPLETED may arrive too early.
        if (!Intent.ACTION_BOOT_COMPLETED.equals(action)) return;
        Context de = context.createDeviceProtectedStorageContext();
        try {
            if (new java.io.File("/dev/df").exists()) return;
            SharedPreferences prefs = de.getSharedPreferences(ExploitRunner.PREFS_NAME,
                    Context.MODE_PRIVATE);
            String bootId = ExploitRunner.c3uBootId();
            if (bootId.equals(prefs.getString("c3u_last_boot_attempt", ""))) return;
            // Commit before launch: even if it fails, never automatically retry
            // a kernel exploit on receipt of the second boot broadcast.
            if (!prefs.edit().putString("c3u_last_boot_attempt", bootId).commit())
                throw new IllegalStateException("Could not persist this boot's one-shot gate");
            String mode = prefs.getBoolean("c3u_boot_full_ksu", false)
                    ? C3URootForegroundService.MODE_KSUN
                    : C3URootForegroundService.MODE_ROOT_ONLY;
            C3URootForegroundService.start(context, mode, C3URootForegroundService.SOURCE_BOOT);
        } catch (Exception e) {
            C3URootLog.append(de, "Boot service was not started: " + e + "\n");
        }
    }
}
