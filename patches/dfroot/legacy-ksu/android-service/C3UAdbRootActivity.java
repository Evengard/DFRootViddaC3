package df.root;

import android.app.Activity;
import android.os.Bundle;

/** Exported only to ADB/shell holders of android.permission.DUMP. No exploit here. */
public final class C3UAdbRootActivity extends Activity {
    private boolean dispatched = false;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        // Start from onResume, once the transient Activity is foregrounded;
        // Android 12+ restricts foreground-service starts from the background.
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (dispatched) return;
        dispatched = true;
        String mode = getIntent() == null ? null
                : getIntent().getStringExtra(C3URootForegroundService.EXTRA_MODE);
        // A mode is required: never root a device using a stale/implicit intent.
        if (!C3URootForegroundService.isValidMode(mode)) {
            C3URootLog.append(this, "ADB request rejected: specify --es mode root-only or --es mode ksun\n");
            finish();
            return;
        }
        try {
            C3URootForegroundService.start(this, mode, C3URootForegroundService.SOURCE_ADB);
        } catch (RuntimeException e) {
            C3URootLog.append(this, "ADB could not start root service: " + e + "\n");
        }
        finish();
    }
}
