#define _POSIX_C_SOURCE 200809L
#include "xpn.h"
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed=PTHREAD_COND_INITIALIZER;
static int connected,received,disconnected,benchmarking,benchmark_done;
static unsigned bench_sent,bench_received;
#define BENCH_PACKETS 10000U
static unsigned char benchmark_packet[XPN_MTU];
static xpn *server,*client;
static void server_packet(void *opaque,const unsigned char *data,size_t length) {
    (void)opaque; assert(length==20 || length==XPN_MTU);
    unsigned char reply[XPN_MTU]; memcpy(reply,data,length);
    memcpy(reply+12,data+16,4); memcpy(reply+16,data+12,4);
    assert(xpn_send(server,reply,length)==0);
}
static void client_packet(void *opaque,const unsigned char *data,size_t length) {
    (void)opaque; assert((length==20 || length==XPN_MTU) && data[12]==10 && data[13]==20 && data[16]==10 && data[17]==77 && data[19]==2);
    pthread_mutex_lock(&lock);
    if(benchmarking) {
        bench_received++;
        if(bench_sent<BENCH_PACKETS) { assert(xpn_send(client,benchmark_packet,XPN_MTU)==0); bench_sent++; }
        if(bench_received==BENCH_PACKETS) benchmark_done=1;
    } else received=1;
    pthread_cond_broadcast(&changed); pthread_mutex_unlock(&lock);
}
static void client_state(void *opaque,int ready,const char *message) {
    (void)opaque; fprintf(stderr,"Transport state: %s\n",message);
    pthread_mutex_lock(&lock); if(ready) connected=1; else disconnected=1; pthread_cond_broadcast(&changed); pthread_mutex_unlock(&lock);
}
static void *service(void *arg) { xpn_run(arg); return NULL; }
static void wait_for(int *value) {
    struct timespec limit; clock_gettime(CLOCK_REALTIME,&limit); limit.tv_sec+=20;
    pthread_mutex_lock(&lock);
    while(!*value) assert(pthread_cond_timedwait(&changed,&lock,&limit)==0);
    pthread_mutex_unlock(&lock);
}
int main(int argc,char **argv) {
    assert(argc==5); assert(xpn_global_init()==0); assert(xpn_set_ca_file(argv[3])==0);
    char invitation[4096],error[256]; FILE *file=fopen(argv[4],"rb"); assert(file);
    size_t n=fread(invitation,1,sizeof(invitation)-1,file); invitation[n]=0; fclose(file);
    char *profile=xpn_enroll(invitation,error,sizeof(error));
    if(!profile) fprintf(stderr,"Enrollment failed: %s\n",error);
    assert(profile);
    server=xpn_server_new(atoi(argv[1]),argv[2],"/xpn/vpn",(xpn_callbacks){server_packet,NULL,NULL}); assert(server);
    pthread_t server_thread,client_thread;
    assert(!pthread_create(&server_thread,NULL,service,server));
    client=xpn_client_new(profile,(xpn_callbacks){client_packet,client_state,NULL}); assert(client); xpn_free(profile);
    assert(!pthread_create(&client_thread,NULL,service,client));
    if (getenv("XPN_TEST_EXPECT_REJECTION")) {
        wait_for(&disconnected);
        pthread_mutex_lock(&lock); assert(!connected && !received); pthread_mutex_unlock(&lock);
        xpn_stop(client); xpn_stop(server); pthread_join(client_thread,NULL); pthread_join(server_thread,NULL);
        xpn_destroy(client); xpn_destroy(server);
        puts("REJECTED"); return 0;
    }
    wait_for(&connected);
    unsigned char packet[20]={0x45,0,0,20}; packet[12]=10;packet[13]=77;packet[15]=2;packet[16]=10;packet[17]=20;packet[19]=1;
    assert(xpn_send(client,packet,20)==0); wait_for(&received);
    const char *idle=getenv("XPN_TEST_IDLE_SECONDS");
    if(idle) {
        long seconds=strtol(idle,NULL,10); assert(seconds>=0 && seconds<=30);
        struct timespec pause={seconds,0}; nanosleep(&pause,NULL);
    }
    memcpy(benchmark_packet,packet,20); benchmark_packet[2]=(unsigned char)(XPN_MTU>>8); benchmark_packet[3]=(unsigned char)XPN_MTU;
    struct timespec start,end; clock_gettime(CLOCK_MONOTONIC,&start);
    pthread_mutex_lock(&lock); benchmarking=1; bench_sent=32; pthread_mutex_unlock(&lock);
    for(unsigned i=0;i<32;i++) assert(xpn_send(client,benchmark_packet,XPN_MTU)==0);
    wait_for(&benchmark_done); clock_gettime(CLOCK_MONOTONIC,&end);
    double seconds=(double)(end.tv_sec-start.tv_sec)+(double)(end.tv_nsec-start.tv_nsec)/1e9;
    printf("BENCHMARK %.1f Mbps per direction, simultaneous loopback round trips\n",BENCH_PACKETS*(double)XPN_MTU*8/seconds/1e6);
    puts("ROUNDTRIP"); fflush(stdout);
    /* Parent revokes the credential after observing the successful round trip. */
    wait_for(&disconnected);
    xpn_stop(client); xpn_stop(server); pthread_join(client_thread,NULL); pthread_join(server_thread,NULL);
    xpn_destroy(client); xpn_destroy(server);
    puts("REVOCATION"); return 0;
}
