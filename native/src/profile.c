#include "internal.h"
#include <arpa/inet.h>
#include <curl/curl.h>
#include <openssl/evp.h>
#include <openssl/crypto.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct response { char *data; size_t length, cap; };
char xpn_ca_file[4096];
int xpn_set_ca_file(const char *path) {
    if (!path || !*path || strlen(path)>=sizeof(xpn_ca_file)) return -1;
    strcpy(xpn_ca_file,path); return 0;
}
static size_t collect(char *data, size_t size, size_t count, void *opaque) {
    struct response *r = opaque;
    size_t cap = r->cap ? r->cap : XPN_PROFILE_MAX;
    if (count && size > cap / count) return 0;
    size_t n = size * count;
    if (r->length + n > cap) return 0;
    char *next = realloc(r->data, r->length + n + 1);
    if (!next) return 0;
    r->data = next; memcpy(next + r->length, data, n); r->length += n; next[r->length] = 0;
    return n;
}
int xpn_global_init(void) { return curl_global_init(CURL_GLOBAL_DEFAULT) == CURLE_OK ? 0 : -1; }
void xpn_free(void *p) { if (p) { OPENSSL_cleanse(p, strlen(p)); free(p); } }
int decode64(const char *s, unsigned char *out, size_t cap) {
    size_t n = strlen(s), padded = (n + 3) / 4 * 4;
    if (!n || n > 11000 || padded / 4 * 3 > cap + 2) return -1;
    char *tmp = malloc(padded + 1); unsigned char *decoded = malloc(padded);
    if (!tmp || !decoded) { free(tmp); free(decoded); return -1; }
    for (size_t i = 0; i < n; i++) {
        char c = s[i];
        if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' || c == '_')) { free(tmp); free(decoded); return -1; }
        tmp[i] = c == '-' ? '+' : c == '_' ? '/' : c;
    }
    for (size_t i = n; i < padded; i++) tmp[i] = '=';
    tmp[padded] = 0;
    int length = EVP_DecodeBlock(decoded, (unsigned char *)tmp, (int)padded);
    if (length >= 0) length -= (int)(padded - n);
    if (length < 0 || (size_t)length > cap) length = -1;
    if (length >= 0) memcpy(out, decoded, (size_t)length);
    OPENSSL_cleanse(decoded, padded); free(decoded); free(tmp); return length;
}
static int field(json_t *j, const char *key, char *out, size_t size) {
    const char *value = json_string_value(json_object_get(j, key));
    if (!value || strlen(value) >= size) return -1;
    memcpy(out, value, strlen(value) + 1); return 0;
}
int profile_parse(const char *text, profile *p) {
    memset(p, 0, sizeof(*p));
    json_error_t err; json_t *j = json_loads(text, JSON_REJECT_DUPLICATES, &err);
    if (!j) return -1;
    int ok = -1; char key[64], mode[16];
    if (json_integer_value(json_object_get(j, "version")) != 1 || field(j,"id",p->id,sizeof(p->id)) || strlen(p->id) != 36 || field(j,"address",p->address,sizeof(p->address)) || field(j,"key",key,sizeof(key)) || decode64(key,p->key,32) != 32 || field(j,"mode",mode,sizeof(mode))) goto done;
    for (size_t i = 0; i < 36; i++) if (!((p->id[i] >= 'a' && p->id[i] <= 'f') || (p->id[i] >= '0' && p->id[i] <= '9') || p->id[i] == '-')) goto done;
    if (strcmp(mode,"psk") && strcmp(mode,"hybrid")) goto done;
    p->hybrid = !strcmp(mode,"hybrid");
    struct in_addr addr;
    if (inet_pton(AF_INET, p->address, &addr) != 1) goto done;
    p->ip = ntohl(addr.s_addr);
    if ((p->ip & 0xffffff00U) != 0x0a4d0000U || (p->ip & 255) < 2 || (p->ip & 255) > 254) goto done;
    if (field(j,"endpoint",p->endpoint,sizeof(p->endpoint)) || strncmp(p->endpoint,"wss://",6)) goto done;
    json_t *full = json_object_get(j,"fullTunnel"), *routes = json_object_get(j,"routes");
    if (!json_is_boolean(full) || !json_is_array(routes) || json_array_size(routes) > 32) goto done;
    p->full = json_is_true(full);
    for (size_t i = 0; i < json_array_size(routes); i++) {
        const char *r = json_string_value(json_array_get(routes,i)); char ip[16], extra; unsigned bits;
        if (!r || sscanf(r,"%15[0-9.]/%u%c",ip,&bits,&extra) != 2 || bits > 32 || inet_pton(AF_INET,ip,&addr) != 1) goto done;
        uint32_t mask = bits ? 0xffffffffU << (32 - bits) : 0;
        p->routes[i].mask = mask; p->routes[i].net = ntohl(addr.s_addr) & mask; p->routes_count++;
    }
    if (!p->full && !p->routes_count) goto done;
    ok = 0;
done:
    OPENSSL_cleanse(key,sizeof(key)); json_decref(j);
    if (ok) OPENSSL_cleanse(p,sizeof(*p));
    return ok;
}
int xpn_validate_profile(const char *text) {
    if (!text || strlen(text)>XPN_PROFILE_MAX) return -1;
    profile p; int result=profile_parse(text,&p); OPENSSL_cleanse(&p,sizeof(p)); return result;
}
int packet_valid(const unsigned char *p, size_t n, uint32_t *src, uint32_t *dst) {
    /* IPv4 options (including source routes) are deliberately unsupported. */
    if (n < 20 || n > XPN_MTU || p[0] != 0x45 || ((size_t)p[2] << 8 | p[3]) != n) return 0;
    *src = (uint32_t)p[12]<<24 | (uint32_t)p[13]<<16 | (uint32_t)p[14]<<8 | p[15];
    *dst = (uint32_t)p[16]<<24 | (uint32_t)p[17]<<16 | (uint32_t)p[18]<<8 | p[19];
    return 1;
}
int packet_allowed(const profile *c, const unsigned char *p, size_t n) {
    uint32_t src,dst;
    if (!packet_valid(p,n,&src,&dst) || src != c->ip) return 0;
    /* Deny peer-to-peer, tunnel-host access, multicast and AWS link-local metadata. */
    if ((dst & 0xffffff00U) == 0x0a4d0000U || (dst & 0xffff0000U) == 0xa9fe0000U || dst >= 0xe0000000U || (dst & 0xff000000U) == 0x7f000000U || (dst & 0xff000000U) == 0) return 0;
    if (c->full) return 1;
    for (unsigned i = 0; i < c->routes_count; i++) if ((dst & c->routes[i].mask) == c->routes[i].net) return 1;
    return 0;
}
char *control_get(const char *socket, const char *id) {
    char url[128]; snprintf(url,sizeof(url),"http://localhost/users%s%s",id ? "/" : "",id ? id : "");
    CURL *curl = curl_easy_init(); struct response r = { .cap = 2 * 1024 * 1024 }; long status = 0;
    if (!curl) return NULL;
    curl_easy_setopt(curl,CURLOPT_URL,url); curl_easy_setopt(curl,CURLOPT_UNIX_SOCKET_PATH,socket);
    curl_easy_setopt(curl,CURLOPT_PROXY,""); curl_easy_setopt(curl,CURLOPT_TIMEOUT_MS,1000L);
    curl_easy_setopt(curl,CURLOPT_WRITEFUNCTION,collect); curl_easy_setopt(curl,CURLOPT_WRITEDATA,&r);
    CURLcode result = curl_easy_perform(curl); curl_easy_getinfo(curl,CURLINFO_RESPONSE_CODE,&status); curl_easy_cleanup(curl);
    if (result || status != 200) { xpn_free(r.data); return NULL; } return r.data;
}
char *xpn_enroll(const char *invite, char *error, size_t error_size) {
    char *answer = NULL, *url = NULL, *body = NULL, *token = NULL, *key = NULL;
    unsigned char secret[32] = {0}, cipher[XPN_PROFILE_MAX], clear[XPN_PROFILE_MAX];
    struct response r = {0}; CURL *curl = NULL; CURLU *u = curl_url(); json_t *j = NULL; struct curl_slist *headers = NULL;
    if (error_size) snprintf(error,error_size,"Invalid, expired or unreachable invitation");
    if (!u || !invite || strlen(invite) > 4096 || strncmp(invite,"https://",8)) goto done;
    const char *fragment = strchr(invite,'#'); if (!fragment) goto done;
    char *query = strdup(fragment + 1); if (!query) goto done;
    char *save = NULL;
    for (char *part = strtok_r(query,"&",&save); part; part = strtok_r(NULL,"&",&save)) {
        if (!strncmp(part,"token=",6) && !token) token = strdup(part + 6);
        else if (!strncmp(part,"key=",4) && !key) key = strdup(part + 4);
        else { free(query); goto done; }
    }
    free(query);
    if (!token || strlen(token) != 43 || !key || decode64(key,secret,32) != 32) goto done;
    for (size_t i=0;i<43;i++) if (!((token[i]>='a'&&token[i]<='z')||(token[i]>='A'&&token[i]<='Z')||(token[i]>='0'&&token[i]<='9')||token[i]=='_'||token[i]=='-')) goto done;
    url = strndup(invite,(size_t)(fragment-invite)); if (!url || curl_url_set(u,CURLUPART_URL,url,0)) goto done;
    char *path = NULL, *user = NULL;
    if (curl_url_get(u,CURLUPART_USER,&user,0) == CURLUE_OK) { curl_free(user); goto done; }
    if (curl_url_get(u,CURLUPART_PATH,&path,0)) goto done;
    size_t n = strlen(path);
    if (n < 5 || strcmp(path+n-5,"/join")) { curl_free(path); goto done; }
    char endpoint[2048];
    if (n + 8 >= sizeof(endpoint)) { curl_free(path); goto done; }
    memcpy(endpoint,path,n-5); strcpy(endpoint+n-5,"/api/enroll"); curl_free(path);
    if (curl_url_set(u,CURLUPART_PATH,endpoint,0) || curl_url_set(u,CURLUPART_FRAGMENT,NULL,0) || curl_url_set(u,CURLUPART_QUERY,NULL,0)) goto done;
    free(url); url = NULL; char *curlurl = NULL;
    if (curl_url_get(u,CURLUPART_URL,&curlurl,0)) goto done;
    url = strdup(curlurl); curl_free(curlurl); if (!url) goto done;
    j = json_pack("{s:s}","token",token); if (!j) goto done;
    body = json_dumps(j,JSON_COMPACT); json_decref(j); j = NULL; if (!body) goto done;
    curl = curl_easy_init(); if (!curl) goto done;
    headers = curl_slist_append(NULL,"Content-Type: application/json");
    curl_easy_setopt(curl,CURLOPT_URL,url); curl_easy_setopt(curl,CURLOPT_POSTFIELDS,body);
    if (*xpn_ca_file) curl_easy_setopt(curl,CURLOPT_CAINFO,xpn_ca_file);
    curl_easy_setopt(curl,CURLOPT_HTTPHEADER,headers); curl_easy_setopt(curl,CURLOPT_TIMEOUT,20L);
    curl_easy_setopt(curl,CURLOPT_PROTOCOLS_STR,"https"); curl_easy_setopt(curl,CURLOPT_REDIR_PROTOCOLS_STR,"https");
    curl_easy_setopt(curl,CURLOPT_WRITEFUNCTION,collect); curl_easy_setopt(curl,CURLOPT_WRITEDATA,&r);
    long status = 0; CURLcode rc = curl_easy_perform(curl); curl_easy_getinfo(curl,CURLINFO_RESPONSE_CODE,&status);
    if (rc || status != 200 || !r.data) goto done;
    j = json_loads(r.data,JSON_REJECT_DUPLICATES,NULL); if (!j) goto done;
    const char *encoded = json_string_value(json_object_get(j,"ciphertext")); if (!encoded) goto done;
    int length = decode64(encoded,cipher,sizeof(cipher)); if (length < 29) goto done;
    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new(); if (!ctx) goto done;
    int written=0, final=0;
    int ok = EVP_DecryptInit_ex(ctx,EVP_aes_256_gcm(),NULL,secret,cipher) && EVP_DecryptUpdate(ctx,clear,&written,cipher+12,length-28) && EVP_CIPHER_CTX_ctrl(ctx,EVP_CTRL_GCM_SET_TAG,16,cipher+length-16) && EVP_DecryptFinal_ex(ctx,clear+written,&final);
    EVP_CIPHER_CTX_free(ctx);
    if (!ok || written+final >= XPN_PROFILE_MAX) goto done;
    clear[written+final]=0; profile p;
    if (profile_parse((char *)clear,&p)) goto done;
    OPENSSL_cleanse(&p,sizeof(p)); answer = strdup((char *)clear);
done:
    if (j) json_decref(j);
    if (curl) curl_easy_cleanup(curl);
    curl_url_cleanup(u); curl_slist_free_all(headers); free(url); free(body); xpn_free(token); xpn_free(key); xpn_free(r.data);
    OPENSSL_cleanse(secret,sizeof(secret)); OPENSSL_cleanse(clear,sizeof(clear)); return answer;
}
