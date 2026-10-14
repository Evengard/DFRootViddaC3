package df.root;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;
import android.widget.CompoundButton;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

/**
 * Consumes the single-use authorization issued by C3UAdbRootActivity and
 * activates DFRoot's existing clickable Root control on the main/UI thread.
 *
 * Deliberately does not invoke the native exploit directly or claim that a
 * successful click implies successful root. Unknown UI versions fail closed.
 */
public final class C3UAdbRootAction {
    private static final String TAG = C3UAdbRootActivity.TAG;
    private static final long TOKEN_TTL_MS = 30_000L;
    private static final long RETRIGGER_GUARD_MS = 180_000L;
    private static final int MAX_TRIES = 6;
    private static final long[] DELAYS_MS = {300, 600, 1000, 1500, 2000, 2500};

    private C3UAdbRootAction() { }

    public static void consumeAndRun(final Activity activity) {
        Intent intent = activity.getIntent();
        if (intent == null) return;
        String supplied = intent.getStringExtra(C3UAdbRootActivity.EXTRA_NONCE);
        if (supplied == null || supplied.length() != 48) return;

        SharedPreferences p = activity.getSharedPreferences(C3UAdbRootActivity.PREF,
                Activity.MODE_PRIVATE);
        String expected = p.getString(C3UAdbRootActivity.KEY_NONCE, "");
        long issued = p.getLong(C3UAdbRootActivity.KEY_AT, -1L);
        // Consume immediately; duplicate activity starts cannot reuse this token.
        p.edit().remove(C3UAdbRootActivity.KEY_NONCE)
                .remove(C3UAdbRootActivity.KEY_AT).commit();
        long now = SystemClock.elapsedRealtime();
        if (!expected.equals(supplied) || issued < 0 || now < issued ||
                now - issued > TOKEN_TTL_MS) {
            Log.e(TAG, "REFUSED_TOKEN: no valid unused ADB authorization");
            return;
        }
        if (new File("/dev/df").exists()) {
            Log.w(TAG, "SKIPPED_ALREADY_ARMED: /dev/df exists; do not re-run this boot");
            return;
        }
        long previous = p.getLong("last_attempt_at", -1L);
        if (previous >= 0 && now >= previous && now - previous < RETRIGGER_GUARD_MS) {
            Log.w(TAG, "SKIPPED_TOO_SOON: recent root action attempted");
            return;
        }
        p.edit().putLong("last_attempt_at", now).apply();
        Log.i(TAG, "AUTHORIZED: seeking DFRoot root control; this is NOT root success");
        Handler h = new Handler(Looper.getMainLooper());
        schedule(activity, h, 0);
    }

    private static void schedule(final Activity activity, final Handler h, final int attempt) {
        h.postDelayed(() -> {
            if (activity.isFinishing() || activity.isDestroyed()) {
                Log.e(TAG, "UI_GONE: MainActivity closed before Root control appeared");
                return;
            }
            if (new File("/dev/df").exists()) {
                Log.i(TAG, "ALREADY_ARMED: /dev/df appeared; no duplicate action");
                return;
            }
            View root = activity.findViewById(android.R.id.content);
            if (root != null) {
                List<Candidate> matches = new ArrayList<>();
                collect(root, matches, 0);
                Candidate best = null;
                boolean tied = false;
                for (Candidate c : matches) {
                    if (best == null || c.score > best.score) {
                        best = c;
                        tied = false;
                    } else if (c.score == best.score) {
                        tied = true;
                    }
                }
                if (best != null && !tied) {
                    Log.i(TAG, "MATCHED_CONTROL: " + best.name);
                    if (best.view.performClick()) {
                        Log.i(TAG, "ROOT_ACTION_CLICKED: clicked existing DFRoot control; verify with su -c id");
                        return;
                    }
                    Log.w(TAG, "CONTROL_NOT_CLICKABLE: will retry");
                } else if (tied) {
                    Log.w(TAG, "AMBIGUOUS_ROOT_CONTROLS: will not click automatically");
                    return;
                }
            }
            if (attempt + 1 < MAX_TRIES) schedule(activity, h, attempt + 1);
            else Log.e(TAG, "NO_ROOT_CONTROL: UI is unsupported; manual run still available");
        }, DELAYS_MS[Math.min(attempt, DELAYS_MS.length - 1)]);
    }

    private static void collect(View v, List<Candidate> out, int depth) {
        if (depth > 30 || v.getVisibility() != View.VISIBLE || !v.isEnabled()) return;
        if (v.isClickable() && !(v instanceof CompoundButton)) {
            String id = "";
            if (v.getId() != View.NO_ID) {
                try { id = v.getResources().getResourceEntryName(v.getId()); }
                catch (Exception ignored) { }
            }
            String label = labelOf(v, 0).trim();
            String description = v.getContentDescription() == null ? "" :
                    v.getContentDescription().toString();
            int score = score(id, label, description);
            if (score > 0) out.add(new Candidate(v, score, id + ":" + label));
        }
        if (v instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) v;
            for (int i = 0; i < group.getChildCount(); ++i)
                collect(group.getChildAt(i), out, depth + 1);
        }
    }

    private static String labelOf(View v, int depth) {
        if (v instanceof TextView) return ((TextView) v).getText() == null ? "" :
                ((TextView) v).getText().toString();
        if (depth >= 2 || !(v instanceof ViewGroup)) return "";
        StringBuilder b = new StringBuilder();
        ViewGroup group = (ViewGroup) v;
        for (int i = 0; i < Math.min(group.getChildCount(), 8); ++i) {
            String s = labelOf(group.getChildAt(i), depth + 1);
            if (!s.isEmpty()) b.append(s).append(' ');
        }
        return b.toString();
    }

    private static int score(String id, String label, String description) {
        String i = id.toLowerCase(java.util.Locale.ROOT);
        String l = label.toLowerCase(java.util.Locale.ROOT).trim();
        String d = description.toLowerCase(java.util.Locale.ROOT).trim();
        String all = i + " " + l + " " + d;
        for (String reject : new String[]{"unroot", "remove", "reboot", "settings",
                "autorun", "boot", "disable", "stop", "uninstall", "update",
                "status", "rooted", "details", "logs", "advanced", "manager"}) {
            if (all.contains(reject)) return 0;
        }
        int idScore = (i.contains("exploit") ? 16 : (i.contains("root") ? 12 :
                (i.contains("run") || i.contains("start") ? 4 : 0)));
        int labelScore = 0;
        if (l.equals("run exploit") || l.equals("start exploit") ||
                l.equals("run root") || l.equals("start rooting") ||
                l.equals("root device")) labelScore = 30;
        else if (l.equals("root") || l.equals("run") || l.equals("start")) labelScore = 15;
        else if (l.contains("exploit") || l.contains("root now") || l.contains("gain root")) labelScore = 12;
        int descScore = (d.contains("exploit") || d.contains("root device")) ? 16 : 0;
        return Math.max(idScore, Math.max(labelScore, descScore));
    }

    private static final class Candidate {
        final View view;
        final int score;
        final String name;
        Candidate(View v, int s, String n) { view = v; score = s; name = n; }
    }
}
