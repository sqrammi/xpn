#ifndef XPN_H
#define XPN_H
#include <stddef.h>
#include <stdint.h>

#define XPN_MTU 1400
#define XPN_PROFILE_MAX 8192
typedef struct xpn xpn;
/* Callbacks run on the service thread. They must be fast and must not destroy xpn.
 * IPv4 packets only. Use xpn_send from any thread. Do not retain packet pointers. */
typedef void (*xpn_packet_fn)(void *, const unsigned char *, size_t);
typedef void (*xpn_state_fn)(void *, int connected, const char *message);
typedef struct {
    xpn_packet_fn packet;
    xpn_state_fn state;
    void *opaque;
} xpn_callbacks;

/* Initialize once before creating clients; no global cleanup while clients live. */
int xpn_global_init(void);
/* Optional bundled PEM trust store for platforms without OpenSSL system roots.
 * Set once, before any instance/enrollment, on the initialization thread. */
int xpn_set_ca_file(const char *path);
int xpn_validate_profile(const char *profile_json);
/* Returns decrypted JSON (including a private PSK), or NULL. Free with xpn_free.
 * invite is an HTTPS /join#token=...&key=... URI. No redirects are followed. */
char *xpn_enroll(const char *invite, char *error, size_t error_size);
void xpn_free(void *value);
xpn *xpn_client_new(const char *profile_json, xpn_callbacks callbacks);
/* Optional numeric dial address, set before xpn_run. Keeps the profile's HTTP
 * Host, TLS hostname validation, SNI and certificate pins unchanged. */
int xpn_client_set_address(xpn *instance, const char *address);
/* Select v2 transport before xpn_run. Outer TLS is ALWAYS required. Turning
 * inner_encryption off encrypts packets only in outer TLS; PSK TLS still
 * authenticates the connection. require_pq requires hybrid outer key exchange
 * and hybrid PSK authentication, with no classical fallback. */
int xpn_client_set_encryption(xpn *instance, int inner_encryption, int require_pq);
/* Enable v3 active/standby connections before xpn_run. Both authenticate and
 * retain the selected encryption. Requires a v3 server; no silent downgrade. */
int xpn_client_set_standby(xpn *instance, int enabled);
/* Linux server uses a single TUN and calls xpn_send for packets coming from TUN.
 * control_socket is the Node Unix socket. listen_path includes any URL prefix. */
xpn *xpn_server_new(int port, const char *control_socket, const char *listen_path, xpn_callbacks callbacks);
/* Run on an owned background thread. Stop before destroy; join the thread first. */
int xpn_run(xpn *instance);
void xpn_stop(xpn *instance);
int xpn_send(xpn *instance, const unsigned char *packet, size_t length);
void xpn_destroy(xpn *instance);
#endif
