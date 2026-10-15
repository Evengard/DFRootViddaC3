#!/usr/bin/env python3
"""Add an opt-in KernelSU second stage to the verified 6de6222 C3U baseline.

Never patches DFRoot's exp.c or the proven first-stage helper. The default launch path retains
original legacy bootstrap behavior, including the independent root shell.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

UPSTREAM_BASELINE = {
    'app/src/main/jni/bootstrap.c': '604b3296297530219d6e8337e1b3bee68a9a0ae7686012add4dc8beb39af5f53',
    'app/src/main/jni/exp.c': '69e7a62fe98cdad5c21065d5605cbbe12ed8ad74d65553506e1e745e128220c6',
    'app/src/main/jni/CMakeLists.txt': '3f07197f393089dc4c16cfd73dc628788e54971e11042221df5a3883acccad90',
    'app/src/main/java/df/root/ExploitRunner.java': '088c4052876287067b74bec016f7aa34b5dc8dad2f44523692e5226fce686a8d',
    'app/src/main/java/df/root/MainActivity.java': 'f4ceecd7886c5b561f28a28b6ad451098b5d5966a5292ded1adf51c4fb9599a5',
    'app/src/main/res/layout/activity_main.xml': 'f3479a8c2e8a3e45be6c0aa1caccbc6ac5e827cff352863ad7f746354ff1e841',
}
KO_SHA256 = '7b5374327b316ccb4e0c4271b938b664f193b7aeb3dd25bd9428976a6c08a38b'
# Observed on the projector and explicitly tested with "ksud insmod". We do not
# bundle this ksud: the legacy app copies libksud.so from the selected Manager.
MANAGER_KSUD_SHA256 = '448155d297e0402ca577379131fc081387a4454392212c3b1567a9de0d58c974'


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text: str, original: str, replacement: str, name: str) -> str:
    count = text.count(original)
    if count != 1:
        raise ValueError(f'{name}: expected exactly one original pattern, saw {count}')
    return text.replace(original, replacement, 1)


NATIVE_STAGE_REQUEST = r'''
/* C3U opt-in request is a one-shot boot-ID marker written by the Activity.
 * Never consult a persistent preference: the automatic boot receiver must
 * not accidentally inject a kernel module on the next device boot. */
#define C3U_STAGE_REQUEST "/data/user_de/0/df.root/c3u-ksu-request"
#define C3U_STAGE_LOADER  "/data/user_de/0/df.root/c3u-ksu-loader"

static int c3u_read_line(const char *path, char *buf, size_t len)
{
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return -1;
    ssize_t n = read(fd, buf, len - 1);
    close(fd);
    if (n <= 0) return -1;
    buf[n] = '\0';
    buf[strcspn(buf, "\r\n ")] = '\0';
    return 0;
}

static int c3u_consume_stage_request(void)
{
    char requested[80], current[80];
    int ok = c3u_read_line(C3U_STAGE_REQUEST, requested, sizeof(requested));
    if (ok != 0) return 0;
    /* Consume the request before the risky stage, so it cannot be replayed. */
    unlink(C3U_STAGE_REQUEST);
    if (c3u_read_line("/proc/sys/kernel/random/boot_id", current, sizeof(current)) != 0)
        return 0;
    return strlen(requested) == 36 && strcmp(requested, current) == 0;
}
'''


def modify_bootstrap(src: str) -> str:
    src = replace_once(src, 'int dfroot_start_root_service(void);\n\nint main(void)',
                       'int dfroot_start_root_service(void);\n' + NATIVE_STAGE_REQUEST + '\nint main(void)', 'bootstrap request helper')
    src = replace_once(src,
                       '    else touch("/dev/dfsue0");\n    char su_manager[256];',
                       '    else touch("/dev/dfsue0");\n'
                       '    int c3u_stage_requested = c3u_consume_stage_request();\n'
                       '    char su_manager[256];', 'bootstrap requested flag')
    original = '''    touch("/dev/dfm5");
    if (run_ctx(NULL, (char *[]){ KSUD_STAGE, "late-load", "--package-name", su_manager, NULL }) == 0) {
        touch("/dev/dfm6");
        if (soft_reboot) {
            while (late_load_running()) sleep(1);
            run_ctx("u:r:ksu:s0", (char *[]){ KSUD, "soft-reboot", NULL });
        }
    } else {
        touch("/dev/dfme2");
    }

    run_ctx(NULL, (char *[]){ "/system/bin/rmmod", "dfroot", NULL });'''
    replacement = '''    touch("/dev/dfm5");
    int c3u_original_late_ok =
        (run_ctx(NULL, (char *[]){ KSUD_STAGE, "late-load", "--package-name", su_manager, NULL }) == 0);
    if (c3u_original_late_ok) {
        touch("/dev/dfm6");
        if (soft_reboot) {
            while (late_load_running()) sleep(1);
            run_ctx("u:r:ksu:s0", (char *[]){ KSUD, "soft-reboot", NULL });
        }
    } else {
        touch("/dev/dfme2");
    }

    /* Entirely optional second stage: the tested temporary-root path above
     * runs as before when the Activity did not request KernelSU loading. */
    if (c3u_stage_requested) {
        touch("/dev/dfki0");      /* consent consumed in this boot */
        if (soft_reboot) {
            touch("/dev/dfkie7"); /* incompatible with controlled KSU stage */
        } else if (!c3u_original_late_ok) {
            touch("/dev/dfkie0"); /* original late-load failed */
        } else {
            for (int i = 0; i < 20 && late_load_running(); i++) usleep(250000);
            if (late_load_running()) {
                touch("/dev/dfkie8"); /* older late-load did not settle */
            } else if (run_ctx(NULL, (char *[]){ C3U_STAGE_LOADER, NULL }) != 0) {
                touch("/dev/dfkie1"); /* KSU insmod helper failed */
            } else {
                touch("/dev/dfki1"); /* KSU module observed as loaded */
                if (run_ctx(NULL, (char *[]){ KSUD_STAGE, "late-load", "--package-name", su_manager, NULL }) == 0)
                    touch("/dev/dfkl1"); /* post-insmod late-load returned 0 */
                else
                    touch("/dev/dfkle1"); /* post-insmod late-load failed */
            }
        }
    }

    run_ctx(NULL, (char *[]){ "/system/bin/rmmod", "dfroot", NULL });'''
    src = replace_once(src, original, replacement, 'bootstrap late-load second stage')
    return src


JAVA_EXTRA = r'''
    // The selected, INSTALLED Manager supplies ksud; do not ship or replace it.
    // Only the exact Manager ksud tested on the projector is authorized for the
    // opt-in kernel stage, and a changed Manager fails before the exploit runs.
    private static final String C3U_MANAGER_KSUD_SHA256 = "448155d297e0402ca577379131fc081387a4454392212c3b1567a9de0d58c974";

    static File c3uRequestFile(Context ctx) {
        return new File(ctx.getFilesDir().getParentFile(), "c3u-ksu-request");
    }

    static String c3uBootId() throws IOException {
        String id = new String(Files.readAllBytes(new File("/proc/sys/kernel/random/boot_id").toPath()),
                java.nio.charset.StandardCharsets.US_ASCII).trim();
        if (id.length() != 36) throw new IOException("Invalid kernel boot ID");
        return id;
    }

    private static String c3uSha256(File file) throws Exception {
        java.security.MessageDigest digest = java.security.MessageDigest.getInstance("SHA-256");
        try (java.io.FileInputStream in = new java.io.FileInputStream(file)) {
            byte[] data = new byte[65536];
            int n;
            while ((n = in.read(data)) != -1) digest.update(data, 0, n);
        }
        StringBuilder hex = new StringBuilder(64);
        for (byte b : digest.digest()) hex.append(String.format(java.util.Locale.ROOT, "%02x", b & 0xff));
        return hex.toString();
    }
'''


def modify_runner(src: str) -> str:
    src = replace_once(src, '    private static void reportDeviceInfo(IReporter reporter) {',
                       JAVA_EXTRA + '\n    private static void reportDeviceInfo(IReporter reporter) {', 'Runner helper insertion')
    src = replace_once(src,
                       '''        stageBin(ctx, new File(app.nativeLibraryDir, "libksud.so"), "ksud"); // stage for a predictable path
        stageBin(ctx, new File(ctx.getApplicationInfo().nativeLibraryDir, "libbootstrap.so"), "bootstrap");''',
                       '''        stageBin(ctx, new File(app.nativeLibraryDir, "libksud.so"), "ksud"); // staged FROM the selected Manager
        stageBin(ctx, new File(ctx.getApplicationInfo().nativeLibraryDir, "libbootstrap.so"), "bootstrap");
        // Only stage the 6.8 MB KernelSU loader when the UI made a one-shot
        // request for THIS boot. Stale requests are dropped without touching KSU.
        File request = c3uRequestFile(ctx);
        if (request.isFile()) {
            String requestedBoot = new String(Files.readAllBytes(request.toPath()),
                    java.nio.charset.StandardCharsets.US_ASCII).trim();
            if (!requestedBoot.equals(c3uBootId())) {
                Files.deleteIfExists(request.toPath());
            } else {
                File ksud = new File(ctx.getFilesDir().getParentFile(), "ksud");
                if (!C3U_MANAGER_KSUD_SHA256.equals(c3uSha256(ksud)))
                    throw new IOException("Manager ksud differs from manually tested C3U binary; no exploit run");
                stageBin(ctx, new File(ctx.getApplicationInfo().nativeLibraryDir,
                        "libc3uksu.so"), "c3u-ksu-loader");
            }
        }''', 'Runner stage assets')
    return src


def modify_activity(src: str) -> str:
    src = replace_once(src, '    private Button btnRun;', '    private Button btnRun;\n    private Button btnRunKsu;', 'Activity button declaration')
    src = replace_once(src, '        btnRun = findViewById(R.id.btnRun);',
                       '        btnRun = findViewById(R.id.btnRun);\n        btnRunKsu = findViewById(R.id.btnRunKsu);', 'Activity button find')
    src = replace_once(src,
                       '''        btnRun.setOnClickListener(v -> {
            btnRun.setEnabled(false);
            outputView.setText("");
            mExec.execute(this::runExploit);
        });''',
                       '''        btnRun.setOnClickListener(v -> launch(false));
        btnRunKsu.setOnClickListener(v -> launch(true));''', 'Activity button actions')
    src = replace_once(src,
                       '''    private void updateRunButton() {
        btnRun.setEnabled(mValidSuManagerPos >= 1 && !new File("/dev/df").exists());
    }

    private void runExploit() {
        try {
            int rc = ExploitRunner.run(mDeCtx, this);''',
                       '''    private void updateRunButton() {
        boolean available = mValidSuManagerPos >= 1 && !new File("/dev/df").exists();
        btnRun.setEnabled(available);
        btnRunKsu.setEnabled(available);
    }

    private void launch(boolean withKernelSu) {
        btnRun.setEnabled(false);
        btnRunKsu.setEnabled(false);
        outputView.setText("");
        mExec.execute(() -> runExploit(withKernelSu));
    }

    private void runExploit(boolean withKernelSu) {
        try {
            File request = ExploitRunner.c3uRequestFile(mDeCtx);
            if (withKernelSu) {
                SharedPreferences prefs = mDeCtx.getSharedPreferences(ExploitRunner.PREFS_NAME,
                        Context.MODE_PRIVATE);
                if (prefs.getBoolean(ExploitRunner.PREF_SOFT_REBOOT, false))
                    throw new IllegalStateException("Disable Soft Reboot before loading KernelSU");
                String id = ExploitRunner.c3uBootId();
                java.nio.file.Files.write(request.toPath(),
                        (id + "\\n").getBytes(java.nio.charset.StandardCharsets.US_ASCII));
                report("KernelSU requested ONCE for the current boot; using Manager ksud\\n");
            } else {
                java.nio.file.Files.deleteIfExists(request.toPath());
                report("Temporary root only; KernelSU injection disabled\\n");
            }
            int rc = ExploitRunner.run(mDeCtx, this);''', 'Activity run stage')
    src = replace_once(src,
                       '''            String msg = rc == 0 ? "DFRoot: SUCCESS"''',
                       '''            String msg = rc == 0 && withKernelSu ? "DFRoot launched: verify /dev/dfki1 and /dev/dfkl1"
                       : rc == 0 ? "DFRoot: SUCCESS"''', 'Activity outcome semantics')
    return src


def modify_layout(src: str) -> str:
    result = replace_once(src,
                        '''        <Button
            android:id="@+id/btnRun"
            android:layout_width="0dp"
            android:layout_height="wrap_content"
            android:layout_weight="4"
            android:text="Launch Root" />''',
                        '''        <Button
            android:id="@+id/btnRun"
            android:layout_width="0dp"
            android:layout_height="wrap_content"
            android:layout_weight="1"
            android:text="Launch Root (temporary only)" />

        <Button
            android:id="@+id/btnRunKsu"
            android:layout_width="0dp"
            android:layout_height="wrap_content"
            android:layout_weight="1"
            android:text="Root + KernelSU (opt-in)" />''', 'Activity layout buttons')
    return replace_once(result, 'android:weightSum="5"', 'android:weightSum="2"', 'Activity button weight balance')


def modify_cmake(src: str) -> str:
    addition = '''
# Separate second-stage executable: embeds only the byte-verified working
# KernelSU .ko. The DFRoot exploit's exp.c and helper .ko are unchanged.
add_executable(c3uksu c3u_ksu_stage.c)
set_target_properties(c3uksu PROPERTIES
    PREFIX "lib"
    SUFFIX ".so"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_LIBRARY_OUTPUT_DIRECTORY}")
target_link_options(c3uksu PRIVATE -Wl,-z,max-page-size=16384)
set_source_files_properties(c3u_ksu_stage.c PROPERTIES
    OBJECT_DEPENDS "${JNI_DIR}/ko/c3u-autobuilt.ko")
'''
    if 'c3uksu' in src:
        raise ValueError('CMake already has a c3uksu target')
    return src + addition


# Every Vidda C3 APK embeds only the freshly compiled and ABI-checked module.
# The historical device-tested binary is represented by ABI metadata, not shipped.
COMPILED_MODULE = 'ViddaC3-KernelSU-Next.ko'


def select_module(package_root: Path) -> Path:
    dist = package_root / 'dist/vidda-c3-kernelsu'
    candidate = dist / COMPILED_MODULE
    checksum = dist / 'rebuilt-module.sha256'
    revision = dist / 'source-commit.txt'
    layout = dist / 'layout-report.txt'
    report = dist / 'module-comparison.json'
    files = (candidate, checksum, revision, layout, report)
    if not all(f.is_file() and f.stat().st_size > 0 for f in files):
        raise ValueError('Freshly compiled KernelSU module or attestations missing; no fallback')
    expected_hash = checksum.read_text().split()[0].lower()
    actual_hash = sha256(candidate)
    if len(expected_hash) != 64 or any(c not in '0123456789abcdef' for c in expected_hash):
        raise ValueError('Invalid compiled-module checksum')
    if actual_hash != expected_hash:
        raise ValueError('Compiled-module digest does not match build output')
    blob = candidate.read_bytes()
    if not (1024 * 1024 <= len(blob) <= 32 * 1024 * 1024
            and blob[:6] == b'\x7fELF\x02\x01'
            and int.from_bytes(blob[16:18], 'little') == 1
            and int.from_bytes(blob[18:20], 'little') == 183
            and blob.count(b'Permissive SELinux, keeping') >= 1
            and b'vermagic=' in blob):
        raise ValueError('Compiled module fails ELF and SELinux checks')
    version_file = dist / 'source-version.json'
    if not version_file.is_file():
        raise ValueError('Missing KernelSU source/version attestation')
    metadata = json.loads(version_file.read_text())
    source_sha = revision.read_text().strip()
    if metadata.get('source_revision') != source_sha or not __import__('re').fullmatch(r'[0-9a-f]{40}', source_sha):
        raise ValueError('Rebuilt source revision not attested')
    code, count, tag = (metadata.get('version_code'),
                        metadata.get('git_commit_count'), metadata.get('version_tag'))
    if (not isinstance(code, int) or not isinstance(count, int)
            or code != 30000 + count or code < 31000
            or not isinstance(tag, str) or not __import__('re').fullmatch(
                r'v[0-9]+\.[0-9]+\.[0-9]+(?:[-.][A-Za-z0-9._-]+)?-viddaC3', tag)):
        raise ValueError('Invalid KernelSU source version metadata')
    if tag.encode('ascii') not in blob:
        raise ValueError('Compiled ELF does not advertise selected upstream tag')
    comparison = json.loads(report.read_text())
    baseline = json.loads((package_root / 'config/kernel-abi-baseline.json').read_text())
    if comparison.get('source_revision') != source_sha:
        raise ValueError('Comparison corresponds to the wrong source revision')
    if comparison.get('rebuilt_candidate', {}).get('sha256') != actual_hash:
        raise ValueError('ABI comparison does not match built module')
    if comparison.get('device_tested_known_good', {}).get('sha256') != baseline['sha256']:
        raise ValueError('ABI baseline does not match device-tested source')
    if comparison.get('candidate_only_undefined_symbols'):
        raise ValueError('New undefined kernel symbols require ABI review; no APK')
    if comparison['rebuilt_candidate'].get('vermagic') != baseline['vermagic']:
        raise ValueError('KernelSU vermagic differs from tested baseline; no APK')
    return candidate


def compiled_stage_files(source: str, module_size: int) -> tuple[str, str]:
    if not (1024 * 1024 <= module_size <= 32 * 1024 * 1024):
        raise ValueError('Unexpected compiled module size')
    source = replace_once(source, '__VIDDA_C3_KO_SIZE__',
                          str(module_size), 'compiled module size guard')
    if source.count('c3u-autobuilt.ko') != 2:
        raise ValueError('Native stage .ko paths changed unexpectedly')
    return source, 'ko/c3u-autobuilt.ko'


def apply(checkout: Path, package_root: Path) -> None:
    checkout = checkout.resolve()
    for rel, expected in UPSTREAM_BASELINE.items():
        current = checkout / rel
        if not current.is_file() or sha256(current) != expected:
            raise ValueError(f'Unexpected legacy baseline at {rel}; refuse to patch')
    source_ko = select_module(package_root)
    modifications = {
        'app/src/main/jni/bootstrap.c': modify_bootstrap,
        'app/src/main/jni/CMakeLists.txt': modify_cmake,
        'app/src/main/java/df/root/ExploitRunner.java': modify_runner,
        'app/src/main/java/df/root/MainActivity.java': modify_activity,
        'app/src/main/res/layout/activity_main.xml': modify_layout,
    }
    results = {rel: fn((checkout / rel).read_text()) for rel, fn in modifications.items()}
    stage_src = (package_root / 'patches/dfroot/legacy-ksu/c3u_ksu_stage.c').read_text()
    stage_src, stage_ko = compiled_stage_files(stage_src, source_ko.stat().st_size)
    # Text patches are verified above, before writing any checkout files.
    for rel, body in results.items():
        (checkout / rel).write_text(body)
    jni = checkout / 'app/src/main/jni'
    (jni / 'c3u_ksu_stage.c').write_text(stage_src)
    staged_ko = jni / stage_ko
    staged_ko.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_ko, staged_ko)
    if sha256(staged_ko) != sha256(source_ko):
        raise ValueError('KernelSU module changed while staging')
    if sha256(jni / 'exp.c') != UPSTREAM_BASELINE['app/src/main/jni/exp.c']:
        raise ValueError('Original DFRoot exploit unexpectedly changed')
    print('PASS: original legacy DFRoot exploit/helper and independent root shell unchanged')
    print('PASS: Manager-staged ksud used; no separate ksud bundled')
    print('PASS: freshly compiled KernelSU module embedded in Vidda C3 stage')
    print(f'MODULE_SHA256={sha256(source_ko)}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkout', type=Path)
    args = parser.parse_args()
    package_root = Path(__file__).resolve().parents[3]
    try:
        apply(args.checkout, package_root)
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f'Legacy+KSU integration refused: {exc}')


if __name__ == '__main__':
    main()
