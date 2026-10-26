#define _POSIX_C_SOURCE 200809L
#define _DEFAULT_SOURCE
#include "xpn.h"
#include "privilege.h"
#include <linux/if_tun.h>
#include <net/if.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static volatile sig_atomic_t interrupted;
struct bridge { int fd; xpn *vpn; atomic_int stopping; };
static void handle(int sig) { (void)sig; interrupted=1; }
static void packet(void *opaque, const unsigned char *data, size_t length) {
    struct bridge *b=opaque;
    /* Nonblocking TUN applies bounded backpressure: drop, never block all peers. */
    ssize_t n=write(b->fd,data,length); (void)n;
}
static void state(void *opaque, int ready, const char *message) {
    (void)opaque; fprintf(stderr,"%s\n",message);
    if (ready) { puts("CONNECTED"); fflush(stdout); }
}
static void *reader(void *opaque) {
    struct bridge *b=opaque;
    struct pollfd p={ .fd=b->fd, .events=POLLIN };
    while(!atomic_load(&b->stopping)) {
        if(interrupted) { xpn_stop(b->vpn); break; }
        if(poll(&p,1,100)<=0) continue;
        unsigned char data[XPN_MTU+1]; ssize_t n=read(b->fd,data,sizeof(data));
        if(n>0) xpn_send(b->vpn,data,(size_t)n);
    }
    return NULL;
}
static int tun_open(const char *name) {
    if(strlen(name)>=IFNAMSIZ) return -1;
    int fd=open("/dev/net/tun",O_RDWR|O_NONBLOCK|O_CLOEXEC); if(fd<0) return -1;
    struct ifreq req; memset(&req,0,sizeof(req)); req.ifr_flags=IFF_TUN|IFF_NO_PI; strcpy(req.ifr_name,name);
    if(ioctl(fd,TUNSETIFF,&req)<0) { close(fd); return -1; } return fd;
}
static char *read_profile(const char *path) {
    FILE *file=fopen(path,"rb"); if(!file) return NULL;
    char *text=calloc(XPN_PROFILE_MAX+1,1); if(!text) { fclose(file); return NULL; }
    size_t n=fread(text,1,XPN_PROFILE_MAX+1,file); fclose(file);
    if(n>XPN_PROFILE_MAX) { free(text); return NULL; } return text;
}
int main(int argc,char **argv) {
    /* A supervisor must select the unprivileged server identity BEFORE exec.
     * Do this before curl/OpenSSL, TUN, control snapshots and worker threads. */
    if (argc>1 && !strcmp(argv[1],"server")) {
        char error[256];
        if (xpn_server_restrict(error,sizeof(error))) { fprintf(stderr,"%s\n",error); return 1; }
    }
    if(xpn_global_init()) return 1;
    if(argc==4 && !strcmp(argv[1],"enroll")) {
        char error[256], invitation[4098]={0}; const char *uri=argv[2];
        if(!strcmp(uri,"-")) {
            if(!fgets(invitation,sizeof(invitation),stdin)) return 1;
            invitation[strcspn(invitation,"\r\n")]=0; uri=invitation;
        }
        char *profile=xpn_enroll(uri,error,sizeof(error));
        memset(invitation,0,sizeof(invitation));
        if(!profile) { fprintf(stderr,"%s\n",error); return 1; }
        int fd=open(argv[3],O_WRONLY|O_CREAT|O_EXCL,0600);
        int ok=fd>=0 && write(fd,profile,strlen(profile))==(ssize_t)strlen(profile);
        if(fd>=0) close(fd);
        xpn_free(profile); return ok ? 0 : 1;
    }
    int server=argc==7 && !strcmp(argv[1],"server");
    int client=argc>=4 && argc<=7 && !strcmp(argv[1],"client");
    if(!server && !client) { fprintf(stderr,"Usage: xpnd server PORT SOCKET PATH TUN --loopback\n       xpnd client PROFILE TUN [--outer-only|--inner-encryption] [--require-pq] [--single-stream]\n       xpnd enroll INVITATION NEW_PROFILE\n"); return 2; }
    int selected=0,inner=1,pq=0,standby=1;
    if (client) for (int i=4;i<argc;i++) {
        if (!strcmp(argv[i],"--single-stream")) { standby=0; continue; }
        if (!strcmp(argv[i],"--outer-only")) inner=0;
        else if (!strcmp(argv[i],"--inner-encryption")) inner=1;
        else if (!strcmp(argv[i],"--require-pq")) pq=1;
        else { fprintf(stderr,"Unknown client encryption option\n"); return 2; }
        selected=1;
    }
    if(server && strcmp(argv[6],"--loopback")) return 2;
    struct bridge b={ .fd=tun_open(server ? argv[5] : argv[3]) }; atomic_init(&b.stopping,0);
    if(b.fd<0) { perror("TUN (preconfigure the interface, or use the Linux launcher)"); return 1; }
    xpn_callbacks cb={packet,state,&b};
    if(server) { char *end=NULL; long port=strtol(argv[2],&end,10); if(*end || port<1 || port>65535) { close(b.fd); return 2; } b.vpn=xpn_server_new((int)port,argv[3],argv[4],cb); }
    else { char *text=read_profile(argv[2]); if(text) { b.vpn=xpn_client_new(text,cb); xpn_free(text); } }
    if(!b.vpn) { fprintf(stderr,"Invalid configuration or native dependency initialization failure\n"); close(b.fd); return 1; }
    if(client && selected && xpn_client_set_encryption(b.vpn,inner,pq)) {
        fprintf(stderr,"Selected encryption is unavailable or conflicts with the device's hybrid policy\n");
        xpn_destroy(b.vpn); close(b.fd); return 1;
    }
    if(client && xpn_client_set_standby(b.vpn,standby)) { xpn_destroy(b.vpn); close(b.fd); return 1; }
    signal(SIGINT,handle); signal(SIGTERM,handle); signal(SIGPIPE,SIG_IGN);
    pthread_t thread;
    if(pthread_create(&thread,NULL,reader,&b)) { xpn_destroy(b.vpn); close(b.fd); return 1; }
    int result=xpn_run(b.vpn);
    atomic_store(&b.stopping,1); pthread_join(thread,NULL); xpn_destroy(b.vpn); close(b.fd);
    return result ? 1 : 0;
}
