// Rebuild: gcc -O2 -shared -fPIC -Wall -Wextra -o _blockmeta.so _blockmeta.c -ldl
//
// LD_PRELOAD shim that blocks libc connect() to cloud metadata addresses.
// Loaded into the bash sandbox via /etc/ld.so.preload (bind-mounted by Sandbox.run).
//
// Blocked:
//   169.254.0.0/16   IPv4 link-local — covers 169.254.169.254 (GCP/AWS/Azure metadata)
//   fe80::/10        IPv6 link-local
//   fd00:ec2::/32    AWS-style IPv6 metadata (defensive)
//
// Bypassable by static binaries, raw syscall, programs linking __connect aliases.
// See docs/sandbox-security.md for the threat boundary.

#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <netinet/in.h>
#include <sys/socket.h>

static int (*real_connect)(int, const struct sockaddr*, socklen_t);

static int blocked(const struct sockaddr *a) {
    if (a->sa_family == AF_INET) {
        unsigned int ip = ntohl(((const struct sockaddr_in*)a)->sin_addr.s_addr);
        return (ip & 0xffff0000u) == 0xa9fe0000u;  // 169.254.0.0/16
    }
    if (a->sa_family == AF_INET6) {
        const unsigned char *b = ((const struct sockaddr_in6*)a)->sin6_addr.s6_addr;
        if (b[0] == 0xfe && (b[1] & 0xc0) == 0x80) return 1;          // fe80::/10
        if (b[0] == 0xfd && b[1] == 0x00 && b[2] == 0xec && b[3] == 0x02) return 1;  // fd00:ec2::/32
    }
    return 0;
}

int connect(int fd, const struct sockaddr *addr, socklen_t len) {
    if (!real_connect) real_connect = dlsym(RTLD_NEXT, "connect");
    if (addr && blocked(addr)) {
        errno = ECONNREFUSED;
        return -1;
    }
    return real_connect(fd, addr, len);
}
