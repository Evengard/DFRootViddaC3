package df.root;

import android.content.Context;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

/** App-private, bounded log shared by the UI and the foreground root worker. */
public final class C3URootLog {
    private static final Object LOCK = new Object();
    private static final String FILENAME = "c3u-root-operation.log";
    private static final int MAX_BYTES = 384 * 1024;
    private static final String TAG = "C3URootLog";

    private C3URootLog() {}

    private static File logFile(Context context) {
        return new File(context.getFilesDir(), FILENAME);
    }

    public static void begin(Context context, String origin) {
        synchronized (LOCK) {
            write(context, "C3U root request from " + origin + "\n", false);
        }
    }

    public static void append(Context context, String msg) {
        if (msg == null || msg.isEmpty()) return;
        synchronized (LOCK) {
            write(context, msg, true);
        }
    }

    private static void write(Context context, String msg, boolean append) {
        File file = logFile(context);
        byte[] data = msg.getBytes(StandardCharsets.UTF_8);
        final byte[] marker = "[Log truncated to bound on-device storage]\n"
                .getBytes(StandardCharsets.UTF_8);
        // Keep an entire record where possible, otherwise retain its tail.
        boolean truncate = data.length > MAX_BYTES
                || (append && file.length() + data.length > MAX_BYTES);
        if (truncate) {
            append = false;
            int allowance = MAX_BYTES - marker.length;
            if (data.length > allowance) {
                byte[] tail = new byte[allowance];
                System.arraycopy(data, data.length - allowance, tail, 0, allowance);
                data = tail;
            }
        }
        try (FileOutputStream out = new FileOutputStream(file, append)) {
            if (truncate) out.write(marker);
            out.write(data);
        } catch (Exception e) {
            Log.w(TAG, "Cannot write operation log", e);
        }
    }

    public static String read(Context context) {
        synchronized (LOCK) {
            try {
                File file = logFile(context);
                if (!file.isFile()) return "";
                if (file.length() > MAX_BYTES) return "[Log exceeds size limit]\n";
                return new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8);
            } catch (Exception e) {
                Log.w(TAG, "Cannot read operation log", e);
                return "[Cannot read operation log]\n";
            }
        }
    }
}
