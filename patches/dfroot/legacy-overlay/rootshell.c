/*
 * DFRoot C3U standalone root service, with one-shot and interactive modes.
 *
 * This is compiled into DFRoot's privileged bootstrap (server), and as an
 * executable named libdfrootsu.so when DFROOT_SU_CLIENT is defined (client).
 *
 * One-shot protocol (backwards compatible): plain command bytes, then EOF.
 * Interactive protocol (new): NUL byte + 16-bit rows and cols (network byte
 * order), then a full-duplex stream; the server connects a root shell to a PTY.
 *
 * Only Linux UID 2000 (ADB shell) or 0 (root) may connect, checked using
 * SO_PEERCRED. Temporary until reboot. NOT an Android-wide permission manager.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <poll.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/un.h>
#include <unistd.h>

#define CMD_MAX 4096
#define SHELL_UID 2000
#ifndef DFROOT_SHELL_PATH
#define DFROOT_SHELL_PATH "/system/bin/sh"
#endif

static void socket_address(struct sockaddr_un *sa, socklen_t *len) {
    static const char abstract_name[] = "\0dfroot_c3u_su_v1";
    memset(sa, 0, sizeof(*sa));
    sa->sun_family = AF_UNIX;
    memcpy(sa->sun_path, abstract_name, sizeof(abstract_name) - 1);
    *len = (socklen_t)(offsetof(struct sockaddr_un, sun_path)
                       + sizeof(abstract_name) - 1);
}

static int write_all(int fd, const void *p, size_t len) {
    const char *bytes = p;
    while (len) {
        ssize_t n = write(fd, bytes, len);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        bytes += (size_t)n;
        len -= (size_t)n;
    }
    return 0;
}

#ifndef DFROOT_SU_CLIENT
#include <pty.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/wait.h>

static int read_exact(int fd, unsigned char *p, size_t len) {
    while (len) {
        ssize_t n = read(fd, p, len);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        p += (size_t)n;
        len -= (size_t)n;
    }
    return 0;
}

static int read_command(int fd, char cmd[CMD_MAX + 1], unsigned char first) {
    size_t count = 1;
    cmd[0] = (char)first;
    for (;;) {
        ssize_t n = read(fd, cmd + count, CMD_MAX - count);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) return -1;
        if (n == 0) break;
        count += (size_t)n;
        if (count == CMD_MAX) return -1;
    }
    if (memchr(cmd, '\0', count)) return -1;
    cmd[count] = '\0';
    return 0;
}

static void serve_command(int peer_fd, unsigned char first) {
    char cmd[CMD_MAX + 1];
    if (read_command(peer_fd, cmd, first) != 0) {
        static const char msg[] = "Invalid or oversized command\n";
        (void)write_all(peer_fd, msg, sizeof(msg) - 1);
        _exit(2);
    }
    if (dup2(peer_fd, STDIN_FILENO) < 0 ||
        dup2(peer_fd, STDOUT_FILENO) < 0 ||
        dup2(peer_fd, STDERR_FILENO) < 0) _exit(127);
    if (peer_fd > STDERR_FILENO) close(peer_fd);
    (void)setenv("PATH", "/system/bin:/system/xbin:/vendor/bin", 1);
    char *const argv[] = { (char *)"sh", (char *)"-c", cmd, NULL };
    execv(DFROOT_SHELL_PATH, argv);
    _exit(127);
}

static void relay_pty(int peer, int master) {
    unsigned char buf[8192];
    int peer_readable = 1;
    for (;;) {
        struct pollfd fds[2] = {
            { .fd = peer_readable ? peer : -1, .events = POLLIN },
            { .fd = master, .events = POLLIN },
        };
        int p = poll(fds, 2, -1);
        if (p < 0 && errno == EINTR) continue;
        if (p < 0) break;

        /* Drain shell output first. A PTY typically returns EIO at EOF. */
        if (fds[1].revents & (POLLIN | POLLERR | POLLHUP | POLLNVAL)) {
            ssize_t n = read(master, buf, sizeof(buf));
            if (n <= 0 || write_all(peer, buf, (size_t)n) != 0) break;
        }
        if (peer_readable && (fds[0].revents & (POLLIN | POLLERR | POLLHUP | POLLNVAL))) {
            ssize_t n = read(peer, buf, sizeof(buf));
            if (n > 0) {
                if (write_all(master, buf, (size_t)n) != 0) break;
            } else {
                /* A noninteractive caller closed stdin. Let sh see EOF. */
                peer_readable = 0;
                static const char eof[] = "\004\004";
                (void)write_all(master, eof, sizeof(eof) - 1);
            }
        }
    }
}

static void serve_interactive(int peer_fd) {
    unsigned char dims[4];
    if (read_exact(peer_fd, dims, sizeof(dims)) != 0) _exit(2);
    unsigned int rows = ((unsigned int)dims[0] << 8) | dims[1];
    unsigned int cols = ((unsigned int)dims[2] << 8) | dims[3];
    struct winsize ws = {
        .ws_row = (unsigned short)(rows ? rows : 24),
        .ws_col = (unsigned short)(cols ? cols : 80),
    };
    int master = -1;
    pid_t child = forkpty(&master, NULL, NULL, &ws);
    if (child < 0) {
        static const char msg[] = "Could not create a PTY for root shell\n";
        (void)write_all(peer_fd, msg, sizeof(msg) - 1);
        _exit(1);
    }
    if (child == 0) {
        close(peer_fd);
        (void)setenv("PATH", "/system/bin:/system/xbin:/vendor/bin", 1);
        (void)setenv("TERM", "xterm-256color", 1);
        (void)setenv("HOME", "/data/local/tmp", 1);
        char *const argv[] = { (char *)"sh", (char *)"-i", NULL };
        execv(DFROOT_SHELL_PATH, argv);
        _exit(127);
    }
    relay_pty(peer_fd, master);
    close(master);
    /* forkpty makes the shell a process group leader. Reap it on disconnect. */
    (void)kill(-child, SIGHUP);
    (void)waitpid(child, NULL, 0);
    _exit(0);
}

static void serve_one(int peer_fd) {
    unsigned char first;
    if (read_exact(peer_fd, &first, 1) != 0) _exit(2);
    if (first == 0) serve_interactive(peer_fd);
    else serve_command(peer_fd, first);
}

static void server_loop(int listener) {
    (void)signal(SIGCHLD, SIG_IGN);
    (void)signal(SIGPIPE, SIG_IGN);
    for (;;) {
        int fd = accept(listener, NULL, NULL);
        if (fd < 0 && errno == EINTR) continue;
        if (fd < 0) continue;
        struct ucred who;
        socklen_t size = sizeof(who);
        if (getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &who, &size) != 0 ||
            size != sizeof(who) ||
            (who.uid != SHELL_UID && who.uid != 0)) {
            close(fd);
            continue;
        }
        pid_t pid = fork();
        if (pid == 0) {
            (void)signal(SIGCHLD, SIG_DFL);
            close(listener);
            serve_one(fd);
        }
        close(fd);
    }
}

/* Called after DFRoot's privileged bootstrap; 0 means the service is ready. */
int dfroot_start_root_service(void) {
    if (geteuid() != 0) return -1;
    int ready[2];
    if (pipe(ready) < 0) return -1;
    pid_t pid = fork();
    if (pid < 0) {
        close(ready[0]);
        close(ready[1]);
        return -1;
    }
    if (pid == 0) {
        close(ready[0]);
        (void)setsid();
        struct sockaddr_un addr;
        socklen_t len;
        socket_address(&addr, &len);
        int s = socket(AF_UNIX, SOCK_STREAM, 0);
        unsigned char ok = 0;
        if (s >= 0 && bind(s, (struct sockaddr *)&addr, len) == 0 &&
            listen(s, 4) == 0) ok = 1;
        (void)write(ready[1], &ok, 1);
        close(ready[1]);
        if (!ok) _exit(1);
        int nullfd = open("/dev/null", O_RDWR);
        if (nullfd >= 0) {
            (void)dup2(nullfd, STDIN_FILENO);
            (void)dup2(nullfd, STDOUT_FILENO);
            (void)dup2(nullfd, STDERR_FILENO);
            if (nullfd > STDERR_FILENO) close(nullfd);
        }
        server_loop(s);
        _exit(0);
    }
    close(ready[1]);
    unsigned char ok = 0;
    ssize_t n;
    do { n = read(ready[0], &ok, 1); } while (n < 0 && errno == EINTR);
    close(ready[0]);
    return (n == 1 && ok == 1) ? 0 : -1;
}

#else /* DFROOT_SU_CLIENT */
#include <sys/ioctl.h>
#include <termios.h>

static struct termios saved_termios;
static int terminal_raw = 0;

static void restore_terminal(void) {
    if (terminal_raw) (void)tcsetattr(STDIN_FILENO, TCSAFLUSH, &saved_termios);
    terminal_raw = 0;
}

static void set_raw_terminal(void) {
    if (!isatty(STDIN_FILENO) || tcgetattr(STDIN_FILENO, &saved_termios) != 0) return;
    struct termios raw = saved_termios;
    cfmakeraw(&raw);
    if (tcsetattr(STDIN_FILENO, TCSAFLUSH, &raw) == 0) {
        terminal_raw = 1;
        (void)atexit(restore_terminal);
    }
}

static int interactive_client(int s) {
    struct winsize ws = { .ws_row = 24, .ws_col = 80 };
    if (ioctl(STDIN_FILENO, TIOCGWINSZ, &ws) != 0 &&
        ioctl(STDOUT_FILENO, TIOCGWINSZ, &ws) != 0) {
        ws.ws_row = 24;
        ws.ws_col = 80;
    }
    unsigned char hello[5] = {
        0,
        (unsigned char)(ws.ws_row >> 8), (unsigned char)ws.ws_row,
        (unsigned char)(ws.ws_col >> 8), (unsigned char)ws.ws_col,
    };
    if (write_all(s, hello, sizeof(hello)) != 0) {
        perror("init interactive root shell");
        return 1;
    }
    set_raw_terminal();
    unsigned char buf[8192];
    int stdin_open = 1;
    for (;;) {
        struct pollfd fds[2] = {
            { .fd = s, .events = POLLIN },
            { .fd = stdin_open ? STDIN_FILENO : -1, .events = POLLIN },
        };
        int p = poll(fds, 2, -1);
        if (p < 0 && errno == EINTR) continue;
        if (p < 0) { perror("poll"); return 1; }
        if (fds[0].revents & (POLLIN | POLLERR | POLLHUP | POLLNVAL)) {
            ssize_t n = read(s, buf, sizeof(buf));
            if (n <= 0) return (n < 0 && errno != ECONNRESET) ? 1 : 0;
            if (write_all(STDOUT_FILENO, buf, (size_t)n) != 0) return 1;
        }
        if (stdin_open && (fds[1].revents & (POLLIN | POLLERR | POLLHUP | POLLNVAL))) {
            ssize_t n = read(STDIN_FILENO, buf, sizeof(buf));
            if (n > 0) {
                if (write_all(s, buf, (size_t)n) != 0) return 1;
            } else {
                stdin_open = 0;
                (void)shutdown(s, SHUT_WR);
            }
        }
    }
}

static int command_client(int s, const char *cmd) {
    size_t len = strlen(cmd);
    if (!len || len >= CMD_MAX) {
        fputs("Command is empty or too long\n", stderr);
        return 2;
    }
    if (write_all(s, cmd, len) < 0 || shutdown(s, SHUT_WR) < 0) {
        perror("send command");
        return 1;
    }
    char buf[4096];
    for (;;) {
        ssize_t n = read(s, buf, sizeof(buf));
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) { perror("read root output"); return 1; }
        if (n == 0) break;
        if (write_all(STDOUT_FILENO, buf, (size_t)n) != 0) return 1;
    }
    /* Compatibility: one-shot protocol does not relay the command's exit code. */
    return 0;
}

int main(int argc, char **argv) {
    int interactive = (argc == 2 && strcmp(argv[1], "-i") == 0);
    int oneshot = (argc == 3 && strcmp(argv[1], "-c") == 0);
    if (!interactive && !oneshot) {
        fprintf(stderr, "Usage: %s -i | -c 'command'\n", argv[0]);
        return 2;
    }
    (void)signal(SIGPIPE, SIG_IGN);
    int s = socket(AF_UNIX, SOCK_STREAM, 0);
    if (s < 0) { perror("socket"); return 1; }
    struct sockaddr_un addr;
    socklen_t addrlen;
    socket_address(&addr, &addrlen);
    if (connect(s, (struct sockaddr *)&addr, addrlen) < 0) {
        perror("root service unavailable (run DFRoot first)");
        close(s);
        return 1;
    }
    int rc = interactive ? interactive_client(s) : command_client(s, argv[2]);
    close(s);
    return rc;
}
#endif
