/* A transient, unrouted TUN interface verifies UID-scoped in-tree hiding.
 * Run as root: builtin-probe <configured-target-uid> <unconfigured-control-uid>.
 * Closing the TUN fd removes the interface, including on process failure.
 */
#include <errno.h>
#include <fcntl.h>
#include <grp.h>
#include <ifaddrs.h>
#include <linux/if_tun.h>
#include <net/if.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <unistd.h>

static const char *iface = "tun998";

static int check(uid_t uid, int hidden)
{
    pid_t child = fork();
    if (child < 0) return 1;
    if (child == 0) {
        gid_t inet = 3003;
        if (setgroups(1, &inet) || setgid(uid) || setuid(uid)) _exit(2);
        struct ifaddrs *addresses = NULL;
        if (getifaddrs(&addresses)) _exit(3);
        int visible = 0;
        for (struct ifaddrs *a = addresses; a; a = a->ifa_next)
            if (!strcmp(a->ifa_name, iface)) visible = 1;
        freeifaddrs(addresses);
        int sock = socket(AF_INET, SOCK_DGRAM, 0);
        if (sock < 0) _exit(4);
        struct ifreq req = {0};
        strcpy(req.ifr_name, iface);
        int err = ioctl(sock, SIOCGIFHWADDR, &req) ? errno : 0;
        close(sock);
        printf("uid=%u visible=%d hwaddr_errno=%d expected_hidden=%d\n", uid, visible, err, hidden);
        fflush(stdout);
        _exit(hidden ? (visible || err != ENODEV) : (!visible || err != 0));
    }
    int status;
    if (waitpid(child, &status, 0) < 0) return 1;
    return !WIFEXITED(status) || WEXITSTATUS(status) != 0;
}

int main(int argc, char **argv)
{
    if (argc != 3 || getuid() != 0) return 2;
    uid_t target = (uid_t)strtoul(argv[1], NULL, 10);
    uid_t control = (uid_t)strtoul(argv[2], NULL, 10);
    if (target < 10000 || control < 10000 || target == control) return 2;
    if (if_nametoindex(iface)) { fprintf(stderr, "Test interface already exists\n"); return 2; }
    int tun = open("/dev/net/tun", O_RDWR | O_CLOEXEC);
    if (tun < 0) { perror("open tun"); return 2; }
    struct ifreq req = {0};
    strcpy(req.ifr_name, iface);
    req.ifr_flags = IFF_TUN | IFF_NO_PI;
    if (ioctl(tun, TUNSETIFF, &req)) { perror("TUNSETIFF"); close(tun); return 2; }
    int failed = check(0, 0) | check(control, 0) | check(target, 1);
    close(tun);
    puts(failed ? "BUILTIN_PROBE_FAILED" : "BUILTIN_PROBE_OK");
    return failed;
}
