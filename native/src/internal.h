#ifndef XPN_INTERNAL_H
#define XPN_INTERNAL_H
#include "xpn.h"
#include <jansson.h>
#include <openssl/ssl.h>
#include <pthread.h>
#include <stdatomic.h>
#include <time.h>
#include <libwebsockets.h>

#define XPN_MAX_PEERS 256
#define XPN_QUEUE 512
#define XPN_TLS_LIMIT (128 * 1024)
#define XPN_SESSION_SECONDS 3600
typedef struct {
    char id[37], address[16], endpoint[2048];
    unsigned char key[32];
    uint32_t ip;
    int full, hybrid;
    unsigned routes_count;
    struct { uint32_t net, mask; } routes[32];
} profile;
typedef struct peer {
    struct xpn *owner;
    struct lws *wsi;
    SSL *ssl;
    profile config;
    int authenticated;
    unsigned char frame[XPN_MTU + 2];
    size_t have;
    time_t born, checked;
    unsigned bytes_since_update;
} peer;
struct queued { size_t length; unsigned char data[XPN_MTU]; };
struct xpn {
    int server, port;
    char control[1024], path[2048], host[256];
    profile config;
    profile cached[XPN_MAX_PEERS];
    size_t cached_count;
    xpn_callbacks cb;
    SSL_CTX *tls;
    struct lws_context *context;
    struct lws *client_wsi;
    peer *peers[XPN_MAX_PEERS];
    atomic_int stop;
    pthread_mutex_t lock;
    struct queued *queue;
    size_t head, count;
    int result;
};
int profile_parse(const char *, profile *);
int packet_valid(const unsigned char *, size_t, uint32_t *, uint32_t *);
int packet_allowed(const profile *, const unsigned char *, size_t);
int decode64(const char *, unsigned char *, size_t);
char *control_get(const char *, const char *);
int core_init(peer *);
int core_receive(peer *, const void *, size_t);
int core_send(peer *, const unsigned char *, size_t);
void core_free(peer *);
int xpn_callback(struct lws *, enum lws_callback_reasons, void *, void *, size_t);
int lookup_profile(struct xpn *, const char *, profile *);
extern char xpn_ca_file[4096];
#endif
