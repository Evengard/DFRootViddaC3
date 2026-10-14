package df.root;

import android.content.Context;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

/** Small, device-protected log that works even when Android logd is stopped. */
final class C3URootLog {
    private static final int MAX_BYTES = 256 * 1024;
    private static final String NAME = "c3u-root-operation.log";

    private C3URootLog() {}

    private static File file(Context ctx) {
        return new File(ctx.createDeviceProtectedStorageContext().getFilesDir(), NAME);
    }

    static synchronized void clear(Context ctx) {
        try {
            Files.write(file(ctx).toPath(), new byte[0]);
        } catch (IOException e) {
            android.util.Log.e("C3URootLog", "Cannot clear root log", e);
        }
    }

    static synchronized void append(Context ctx, String message) {
        try {
            File target = file(ctx);
            if (target.length() >= MAX_BYTES) {
                Files.write(target.toPath(), "[previous log truncated]\n".getBytes(StandardCharsets.UTF_8));
            }
            try (FileOutputStream out = new FileOutputStream(target, true)) {
                out.write(message.getBytes(StandardCharsets.UTF_8));
            }
        } catch (IOException e) {
            android.util.Log.e("C3URootLog", "Cannot append root log", e);
        }
    }

    static synchronized String read(Context ctx) {
        try {
            File f = file(ctx);
            return f.exists() ? new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8) : "";
        } catch (IOException e) {
            return "Cannot read root log: " + e;
        }
    }
}
