package df.root;

import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;

/** Exact-package selection for unattended starts. Never pick an arbitrary root manager. */
final class C3URootManager {
    static final String KSU_NEXT_PACKAGE = "com.rifsxd.ksunext";

    private C3URootManager() {}

    static boolean isKsuNextAvailable(Context context) {
        try {
            ApplicationInfo app = context.getPackageManager()
                    .getApplicationInfo(KSU_NEXT_PACKAGE, 0);
            return ExploitRunner.hasKsud(app);
        } catch (PackageManager.NameNotFoundException e) {
            return false;
        }
    }

    static void selectForRun(Context deviceContext, String mode, String source,
                             IReporter reporter) {
        SharedPreferences prefs = deviceContext.getSharedPreferences(
                ExploitRunner.PREFS_NAME, Context.MODE_PRIVATE);
        boolean unattended = !C3URootForegroundService.SOURCE_UI.equals(source);
        String chosen = prefs.getString(ExploitRunner.PREF_SU_MANAGER, null);
        boolean mustUseKsuNext = unattended
                || C3URootForegroundService.MODE_KSUN.equals(mode);

        if (mustUseKsuNext || chosen == null || !isInstalledWithKsud(deviceContext, chosen)) {
            if (!isKsuNextAvailable(deviceContext)) {
                throw new IllegalStateException(
                        "KernelSU Next Manager (" + KSU_NEXT_PACKAGE + ") with libksud.so is not installed; "
                        + "refusing unattended rooting");
            }
            chosen = KSU_NEXT_PACKAGE;
        }

        // The native bootstrap reads this exact device-protected preference.
        // commit() is essential: apply() could race with the privileged bootstrap.
        if (!prefs.edit().putString(ExploitRunner.PREF_SU_MANAGER, chosen).commit()) {
            throw new IllegalStateException("Could not save selected SU Manager");
        }
        reporter.report("SU Manager: " + chosen + (unattended ? " (auto-selected)" : "") + "\n");
    }

    private static boolean isInstalledWithKsud(Context context, String name) {
        try {
            return ExploitRunner.hasKsud(
                    context.getPackageManager().getApplicationInfo(name, 0));
        } catch (PackageManager.NameNotFoundException e) {
            return false;
        }
    }
}
