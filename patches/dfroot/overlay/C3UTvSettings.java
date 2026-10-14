package df.root;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.res.Resources;
import android.util.Log;
import android.view.Gravity;
import android.view.Menu;
import android.view.MenuItem;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.PopupMenu;
import android.widget.TextView;
import android.widget.Toast;

/**
 * Focusable, on-screen TV fallback for DFRoot's phone-oriented settings entry.
 * Does not change preferences or root behavior; delegates to the existing
 * activity's options-menu handler, existing settings View, or settings Activity.
 *
 * Exact upstream UI source was not available in this build environment.
 * The patcher checks for a Java MainActivity and inserts a single install call.
 */
public final class C3UTvSettings {
    private static final String TAG = "C3UTvSettings";
    private static final String BUTTON_TAG = "c3u_settings_tv_button";

    private C3UTvSettings() { }

    public static void install(final Activity activity) {
        final FrameLayout content = activity.findViewById(android.R.id.content);
        if (content == null || content.findViewWithTag(BUTTON_TAG) != null) return;
        final Button button = new Button(activity);
        button.setTag(BUTTON_TAG);
        button.setText("Settings");
        button.setContentDescription("DFRoot Settings");
        button.setFocusable(true);
        button.setFocusableInTouchMode(true);
        button.setMinHeight(dp(activity, 48));
        button.setMinWidth(dp(activity, 112));
        button.setElevation(dp(activity, 6));
        final FrameLayout.LayoutParams params = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.END | Gravity.BOTTOM);
        params.setMargins(dp(activity, 12), dp(activity, 12), dp(activity, 24), dp(activity, 24));
        button.setOnClickListener(v -> openSettings(activity, button));
        content.addView(button, params);
    }

    private static int dp(Activity activity, int n) {
        return (int) (n * activity.getResources().getDisplayMetrics().density + 0.5f);
    }

    private static boolean looksSettings(CharSequence title) {
        if (title == null) return false;
        String lower = title.toString().toLowerCase(java.util.Locale.ROOT);
        return lower.contains("settings") || lower.contains("preferences") ||
                lower.contains("options");
    }

    private static MenuItem findSettingsItem(Menu menu) {
        for (int i = 0; i < menu.size(); ++i) {
            MenuItem item = menu.getItem(i);
            if (looksSettings(item.getTitle())) return item;
            if (item.hasSubMenu()) {
                MenuItem nested = findSettingsItem(item.getSubMenu());
                if (nested != null) return nested;
            }
        }
        return null;
    }

    private static View findSettingsView(View root, View self) {
        if (root == self) return null;
        String idName = "";
        if (root.getId() != View.NO_ID) {
            try { idName = root.getResources().getResourceEntryName(root.getId()); }
            catch (Resources.NotFoundException ignored) { }
        }
        if (looksSettings(idName) || looksSettings(root.getContentDescription()) ||
                (root instanceof TextView && looksSettings(((TextView) root).getText()))) {
            if (root.isClickable()) return root;
        }
        if (root instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) root;
            for (int i = 0; i < group.getChildCount(); i++) {
                View candidate = findSettingsView(group.getChildAt(i), self);
                if (candidate != null) return candidate;
            }
        }
        return null;
    }

    public static void openSettings(Activity activity, View anchor) {
        // Most reliable on phone-style UIs: use the original options-menu
        // callbacks, but provide our own visible, DPAD-focusable anchor.
        try {
            PopupMenu popup = new PopupMenu(activity, anchor);
            activity.onCreateOptionsMenu(popup.getMenu());
            MenuItem settings = findSettingsItem(popup.getMenu());
            if (settings != null) {
                // Route through the original activity's own handler.
                if (activity.onOptionsItemSelected(settings)) return;
                Intent intent = settings.getIntent();
                if (intent != null) { activity.startActivity(intent); return; }
                popup.setOnMenuItemClickListener(activity::onOptionsItemSelected);
                popup.show();
                return;
            }
        } catch (Exception e) { Log.w(TAG, "Options-menu fallback failed", e); }

        // Also works for a clipped/offscreen settings icon that still has
        // its normal click listener installed.
        try {
            View match = findSettingsView(activity.getWindow().getDecorView(), anchor);
            if (match != null && match.performClick()) return;
        } catch (Exception e) { Log.w(TAG, "View fallback failed", e); }

        // Last resort: a declared Settings/Preferences Activity in this APK.
        try {
            PackageInfo info = activity.getPackageManager().getPackageInfo(
                    activity.getPackageName(), PackageManager.GET_ACTIVITIES);
            ActivityInfo[] activities = info.activities;
            if (activities != null) {
                for (ActivityInfo target : activities) {
                    String name = target.name;
                    if (name.endsWith("SettingsActivity") || name.endsWith("PreferencesActivity")) {
                        activity.startActivity(new Intent().setClassName(activity, name));
                        return;
                    }
                }
            }
        } catch (Exception e) { Log.w(TAG, "Settings Activity fallback failed", e); }

        Toast.makeText(activity, "Settings screen not found in this DFRoot build", Toast.LENGTH_LONG).show();
    }
}
