/*
 * C3U second stage: embed the *device-tested* KernelSU Next module and use
 * the Manager-staged ksud to load it. No other ksud binary is bundled here.
 *
 * This executable is invoked by the legacy DFRoot bootstrap only after the
 * original first stage and late-load have run, and only for a one-shot,
 * same-boot request explicitly initiated in the UI.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#define C3U_KSUD "/data/user_de/0/df.root/ksud"
#define C3U_KO_PATH "/data/user_de/0/df.root/c3u-working-v6.ko"
#define C3U_STAGE_STATUS "/data/user_de/0/df.root/c3u-ksu-stage.status"

__asm__(
    ".section .rodata\n"
    ".balign 16\n"
    ".global c3u_known_ko_start\n"
    "c3u_known_ko_start:\n"
    ".incbin \"ko/c3u-working-v6.ko\"\n"
    ".global c3u_known_ko_end\n"
    "c3u_known_ko_end:\n"
    ".balign 16\n"
);
extern const unsigned char c3u_known_ko_start[];
extern const unsigned char c3u_known_ko_end[];

static void mark(const char *path)
{
    int fd = open(path, O_CREAT | O_WRONLY | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd >= 0) close(fd);
    /* Persist the last transition so a post-crash legacy root session can
     * inspect it even if /dev and logcat state disappear after a reset. */
    fd = open(C3U_STAGE_STATUS, O_CREAT | O_TRUNC | O_WRONLY | O_CLOEXEC | O_NOFOLLOW, 0644);
    if (fd >= 0) {
        (void)fchmod(fd, 0644);
        (void)write(fd, path, strlen(path));
        (void)write(fd, "\n", 1);
        (void)fsync(fd);
        close(fd);
    }
}

static int module_loaded(void)
{
    if (access("/sys/module/kernelsu", F_OK) == 0) return 1;
    FILE *f = fopen("/proc/modules", "r");
    if (!f) return 0;
    char line[512];
    int found = 0;
    while (fgets(line, sizeof(line), f)) {
        if (strncmp(line, "kernelsu ", sizeof("kernelsu ") - 1) == 0) {
            found = 1;
            break;
        }
    }
    fclose(f);
    return found;
}

static int write_all(int fd, const unsigned char *data, size_t len)
{
    while (len) {
        ssize_t n = write(fd, data, len);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        data += (size_t)n;
        len -= (size_t)n;
    }
    return 0;
}

static int verify_written(const unsigned char *data, size_t len)
{
    int fd = open(C3U_KO_PATH, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return -1;
    struct stat st;
    int ok = fstat(fd, &st) == 0 && S_ISREG(st.st_mode) && st.st_size == (off_t)len;
    unsigned char buf[65536];
    size_t off = 0;
    while (ok && off < len) {
        size_t want = len - off < sizeof(buf) ? len - off : sizeof(buf);
        ssize_t n = read(fd, buf, want);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0 || memcmp(buf, data + off, (size_t)n) != 0) {
            ok = 0;
            break;
        }
        off += (size_t)n;
    }
    close(fd);
    return ok && off == len ? 0 : -1;
}

static int stage_known_module(void)
{
    const unsigned char *data = c3u_known_ko_start;
    size_t len = (size_t)(c3u_known_ko_end - c3u_known_ko_start);
    if (len != 6797960) return -1; /* the *specific* tested module */
    int fd = open(C3U_KO_PATH, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd < 0) return -1;
    int ok = fchmod(fd, 0600) == 0 && write_all(fd, data, len) == 0 && fsync(fd) == 0;
    if (close(fd) != 0) ok = 0;
    return ok ? verify_written(data, len) : -1;
}

static int run_insmod(void)
{
    pid_t pid = fork();
    if (pid < 0) return -1;
    if (pid == 0) {
        char *const argv[] = { (char *)C3U_KSUD, (char *)"insmod", (char *)C3U_KO_PATH, NULL };
        execv(C3U_KSUD, argv);
        _exit(127);
    }
    int status = 0;
    pid_t waited;
    do { waited = waitpid(pid, &status, 0); } while (waited < 0 && errno == EINTR);
    return waited == pid && WIFEXITED(status) ? WEXITSTATUS(status) : -1;
}

int main(void)
{
    if (geteuid() != 0) {
        mark("/dev/dfkie2"); /* helper wasn't invoked with root */
        return 2;
    }
    if (module_loaded()) {
        mark("/dev/dfki1"); /* already present; don't double-load */
        return 0;
    }
    if (access(C3U_KSUD, X_OK) != 0) {
        mark("/dev/dfkie3"); /* Manager-staged ksud unavailable */
        return 3;
    }
    if (stage_known_module() != 0) {
        mark("/dev/dfkie4"); /* embedded .ko couldn't be staged/verified */
        return 4;
    }
    mark("/dev/dfki2"); /* exact .ko written and byte-verified */
    mark("/dev/dfki3"); /* immediately before Manager-staged ksud insmod */
    if (run_insmod() != 0) {
        mark("/dev/dfkie5");
        return 5;
    }
    if (!module_loaded()) {
        mark("/dev/dfkie6"); /* return 0 but module not observable */
        return 6;
    }
    mark("/dev/dfki1");
    return 0;
}
