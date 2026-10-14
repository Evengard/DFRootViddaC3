/*
 * Vidda C3U-only KernelSU Next loader for DFRoot's already-privileged bootstrap.
 *
 * Embeds the exact user-provided, v6-permissive .ko with no ELF modification,
 * runs the already-staged KernelSU Next ksud's symbol-aware `insmod`, verifies
 * that a live module exists and SELinux remains permissive, then lets DFRoot
 * continue its normal `ksud late-load` path. The latter skips kernel loading
 * when KernelSU is already present (KernelSU Next late-load behavior).
 *
 * Does not install persistent services, change boot partitions or enable
 * start-on-boot. Fails closed: caller must not invoke ordinary late-load if
 * any check below fails, because it could load an incompatible stock module.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stddef.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/utsname.h>
#include <sys/wait.h>
#include <unistd.h>
#ifdef __ANDROID__
#include <sys/system_properties.h>
#endif

#define C3U_MODULE_FILE "/data/user_de/0/df.root/c3u-ksunext-v6.ko"
#define C3U_LOG_FILE "/data/user_de/0/df.root/c3u-v7-preload.log"
#define C3U_EXACT_KERNEL "5.15.148-android14-11-g7b7674251b5d-dirty"
#define C3U_EXACT_FINGERPRINT "Hisense/VIDAA_TV/MT9655:14/UQ1A.240105.004.A1/07.02.70.202512281739:user/release-keys"

/* The .incbin input is copied in by the build script, never reconstructed. */
__asm__(
    ".section .rodata\n"
    ".balign 16\n"
    ".global c3u_v7_ksu_ko_begin\n"
    "c3u_v7_ksu_ko_begin:\n"
    ".incbin \"ko/c3u-ksunext-v6.ko\"\n"
    ".global c3u_v7_ksu_ko_end\n"
    "c3u_v7_ksu_ko_end:\n"
    ".balign 16\n");
extern const unsigned char c3u_v7_ksu_ko_begin[];
extern const unsigned char c3u_v7_ksu_ko_end[];

static void c3u_log(const char *fmt, ...) {
    char msg[420];
    va_list ap;
    va_start(ap, fmt);
    int count = vsnprintf(msg, sizeof(msg), fmt, ap);
    va_end(ap);
    if (count < 0) return;
    size_t n = strnlen(msg, sizeof(msg) - 1);
    int fd = open(C3U_LOG_FILE, O_WRONLY | O_CREAT | O_APPEND | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd >= 0) {
        (void)write(fd, msg, n);
        (void)write(fd, "\n", 1);
        close(fd);
    }
    /* Surface messages in the kernel ring buffer where permitted. */
    fd = open("/dev/kmsg", O_WRONLY | O_CLOEXEC);
    if (fd >= 0) {
        char line[490];
        int len = snprintf(line, sizeof(line), "<6>dfroot-c3u-v7: %.*s\n", (int)n, msg);
        if (len > 0 && len < (int)sizeof(line)) (void)write(fd, line, (size_t)len);
        close(fd);
    }
}

static bool c3u_is_permissive(void) {
    char buf[12];
    int fd = open("/sys/fs/selinux/enforce", O_RDONLY | O_CLOEXEC);
    if (fd < 0) return false;
    ssize_t n = read(fd, buf, sizeof(buf));
    close(fd);
    return n > 0 && buf[0] == '0';
}

static bool c3u_is_live(void) {
    FILE *f = fopen("/proc/modules", "r");
    if (!f) return false;
    char line[1024];
    bool live = false;
    while (fgets(line, sizeof(line), f)) {
        if (strncmp(line, "kernelsu ", 9) == 0) {
            live = strstr(line, " Live ") != NULL;
            break;
        }
    }
    fclose(f);
    return live;
}

static int c3u_write_embedded_ko(void) {
    uintptr_t start = (uintptr_t)c3u_v7_ksu_ko_begin;
    uintptr_t end = (uintptr_t)c3u_v7_ksu_ko_end;
    if (end <= start || end - start < 65536 || end - start > 64 * 1024 * 1024) return -1;
    size_t size = (size_t)(end - start);
    int fd = open(C3U_MODULE_FILE, O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) {
        c3u_log("Cannot stage embedded v6 KO: errno=%d", errno);
        return -1;
    }
    (void)fchmod(fd, 0600);
    for (size_t done = 0; done < size;) {
        ssize_t n = write(fd, c3u_v7_ksu_ko_begin + done, size - done);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) {
            c3u_log("Error writing v6 KO: errno=%d", errno);
            close(fd);
            unlink(C3U_MODULE_FILE);
            return -1;
        }
        done += (size_t)n;
    }
    int synced = fsync(fd);
    int closed = close(fd);
    if (synced != 0 || closed != 0) {
        c3u_log("Unable to finish v6 KO staging: errno=%d", errno);
        return -1;
    }
    c3u_log("Staged exact v6 KO (%zu bytes) at %s", size, C3U_MODULE_FILE);
    return 0;
}

static int c3u_run_insmod(const char *ksud_path) {
    pid_t child = fork();
    if (child == -1) return -1;
    if (child == 0) {
        char *const argv[] = {(char *)ksud_path, (char *)"insmod", (char *)C3U_MODULE_FILE, NULL};
        execv(ksud_path, argv);
        _exit(127);
    }
    int status = 0;
    /* A timed wait avoids blocking DFRoot forever if the loader hangs. */
    for (int i = 0; i < 450; ++i) {
        pid_t done = waitpid(child, &status, WNOHANG);
        if (done == child) {
            if (!WIFEXITED(status)) return -1;
            return WEXITSTATUS(status);
        }
        if (done < 0 && errno != EINTR) return -1;
        usleep(100000);
    }
    c3u_log("ksud insmod exceeded 45-second timeout; aborting normal late-load");
    (void)kill(child, SIGTERM);
    (void)waitpid(child, NULL, WNOHANG);
    return -1;
}

int c3u_ksu_preload(void) {
    if (geteuid() != 0 || getuid() != 0) {
        c3u_log("Refused: bootstrap is not UID 0");
        return 70;
    }

    struct utsname un;
    if (uname(&un) != 0 || strcmp(un.machine, "aarch64") != 0 ||
        strcmp(un.release, C3U_EXACT_KERNEL) != 0) {
        c3u_log("Refused: different device kernel/architecture");
        return 71;
    }
#ifdef __ANDROID__
    char fingerprint[PROP_VALUE_MAX] = {0};
    if (__system_property_get("ro.build.fingerprint", fingerprint) <= 0 ||
        strcmp(fingerprint, C3U_EXACT_FINGERPRINT) != 0) {
        c3u_log("Refused: firmware fingerprint differs from validated C3U build");
        return 72;
    }
#endif
    if (!c3u_is_permissive()) {
        c3u_log("Refused: SELinux is not permissive before v6 preload");
        return 73;
    }
    if (c3u_is_live()) {
        c3u_log("KernelSU is already live; allowing DFRoot late-load continuation");
        return 0;
    }

    const char *candidates[] = {
        "/data/adb/ksud" /* Installed during user’s previously successful v6 run */
    };
    const char *ksud = NULL;
    for (size_t i = 0; i < sizeof(candidates) / sizeof(candidates[0]); ++i) {
        if (access(candidates[i], X_OK) == 0) { ksud = candidates[i]; break; }
    }
    if (!ksud) {
        c3u_log("Refused: /data/adb/ksud missing; requires prior working KernelSU userspace");
        return 74;
    }
    if (c3u_write_embedded_ko() != 0) return 75;
    c3u_log("Launching %s insmod (C3U v6 KO)", ksud);
    int result = c3u_run_insmod(ksud);
    if (result != 0) {
        c3u_log("ksud insmod failed (exit=%d); refusing stock late-load", result);
        return 76;
    }
    if (!c3u_is_live()) {
        c3u_log("ksud insmod returned success but kernelsu is not Live; aborting");
        return 77;
    }
    if (!c3u_is_permissive()) {
        c3u_log("v6 preload unexpectedly enabled SELinux; refusing continuation");
        return 78;
    }
    c3u_log("C3U v6 KernelSU is Live; proceeding with original ksud late-load userspace setup");
    return 0;
}
