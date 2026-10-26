#ifndef XPN_PRIVILEGE_H
#define XPN_PRIVILEGE_H
#include <stddef.h>
/* Linux xpnd server entry point only. Call while single-threaded, before any
 * library initialization, TUN descriptor, credential read or listening socket.
 * Reject privileged launches rather than accept clients and drop privileges
 * later. systemd (or an equivalent supervisor) supplies the non-root identity. */
int xpn_server_restrict(char *error, size_t size);
#endif
