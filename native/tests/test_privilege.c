#define _GNU_SOURCE
#include "privilege.h"
#include <assert.h>
#include <errno.h>
#include <grp.h>
#include <linux/capability.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static void restricted_state(void) {
    assert(getuid()!=0 && geteuid()!=0 && getgid()!=0 && getegid()!=0);
    assert(prctl(PR_GET_NO_NEW_PRIVS,0,0,0,0)==1);
    assert(prctl(PR_GET_DUMPABLE,0,0,0,0)==0);
    assert(prctl(PR_SET_NO_NEW_PRIVS,0,0,0,0)==-1);
    assert(setuid(0)==-1 && errno==EPERM);
    assert(setgid(0)==-1 && errno==EPERM);
    struct __user_cap_header_struct header={.version=_LINUX_CAPABILITY_VERSION_3,.pid=0};
    struct __user_cap_data_struct caps[2]={{0},{0}};
    assert(syscall(SYS_capget,&header,caps)==0);
    for (unsigned i=0;i<2;i++) assert(!caps[i].effective && !caps[i].permitted && !caps[i].inheritable);
}
static void *worker(void *unused) { (void)unused; restricted_state(); return NULL; }
static void accepted(void) {
    char error[256]; int result=xpn_server_restrict(error,sizeof(error));
    if (result) fprintf(stderr,"%s\n",error);
    assert(result==0 && !*error); restricted_state();
    pthread_t thread; assert(!pthread_create(&thread,NULL,worker,NULL)); assert(!pthread_join(thread,NULL));
    pid_t pid=fork(); assert(pid>=0);
    if (!pid) { restricted_state(); _exit(0); }
    int status; assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && WEXITSTATUS(status)==0);
}
static void rejected(const char *reason) {
    char error[256]; assert(xpn_server_restrict(error,sizeof(error))==-1); assert(strstr(error,reason));
}
/* --root is an explicit isolated Linux test invocation, not a daemon. Every
 * credential mutation happens in a child; no users, TUN or network are created. */
static void root_case(unsigned which) {
    const uid_t uid=65534; const gid_t gid=65534;
    if (which==0) { rejected("UIDs"); return; }
    gid_t group=which==3 ? 0 : gid;
    assert(setgroups(1,&group)==0);
    assert(setresgid(which==2 ? 0 : gid,which==2 ? 0 : gid,which==2 ? 0 : gid)==0);
    if (which==4) assert(prctl(PR_SET_KEEPCAPS,1,0,0,0)==0);
    assert(setresuid(uid,uid,which==1 ? 0 : uid)==0);
    switch(which) {
    case 1: rejected("UIDs"); break;
    case 2: rejected("GIDs"); break;
    case 3: rejected("supplementary group"); break;
    case 4: rejected("capabilities"); break;
    case 5: accepted(); break;
    default: assert(0);
    }
}
int main(int argc,char **argv) {
    if (argc==2 && !strcmp(argv[1],"--root")) {
        assert(getuid()==0 && geteuid()==0);
        for (unsigned i=0;i<6;i++) {
            pid_t pid=fork(); assert(pid>=0);
            if (!pid) { root_case(i); _exit(0); }
            int status; assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && WEXITSTATUS(status)==0);
        }
        puts("Root, saved-root IDs, root groups, retained capabilities rejected; clean dropped identity accepted");
    } else {
        assert(argc==1);
        if (!getuid() || !geteuid()) rejected("UIDs"); else accepted();
        puts("Privilege guard and thread/child inheritance passed");
    }
    return 0;
}
