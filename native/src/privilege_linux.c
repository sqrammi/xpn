#define _GNU_SOURCE
#include "privilege.h"
#include <linux/capability.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>

static int refuse(char *error, size_t size, const char *reason) {
    if (error && size) snprintf(error,size,"Server privilege check failed: %s. Start using xpn-native.service as xpn-packet.",reason);
    return -1;
}
int xpn_server_restrict(char *error, size_t size) {
    uid_t real_uid,effective_uid,saved_uid;
    gid_t real_gid,effective_gid,saved_gid;
    if (getresuid(&real_uid,&effective_uid,&saved_uid) || getresgid(&real_gid,&effective_gid,&saved_gid))
        return refuse(error,size,"cannot inspect credentials");
    if (!real_uid || !effective_uid || !saved_uid || real_uid!=effective_uid || real_uid!=saved_uid)
        return refuse(error,size,"root or mismatched real/effective/saved UIDs");
    if (!real_gid || !effective_gid || !saved_gid || real_gid!=effective_gid || real_gid!=saved_gid)
        return refuse(error,size,"root or mismatched real/effective/saved GIDs");
    int count=getgroups(0,NULL);
    if (count<0 || count>65536) return refuse(error,size,"cannot inspect supplementary groups");
    if (count) {
        gid_t *groups=malloc((size_t)count*sizeof(*groups));
        if (!groups) return refuse(error,size,"cannot inspect supplementary groups");
        int n=getgroups(count,groups), has_root=0;
        for (int i=0;i<n;i++) if (!groups[i]) has_root=1;
        free(groups);
        if (n!=count || has_root) return refuse(error,size,"root supplementary group or changing groups");
    }
    struct __user_cap_header_struct header={.version=_LINUX_CAPABILITY_VERSION_3,.pid=0};
    struct __user_cap_data_struct caps[2]={{0},{0}};
    if (syscall(SYS_capget,&header,caps)) return refuse(error,size,"cannot inspect Linux capabilities");
    for (unsigned i=0;i<2;i++)
        if (caps[i].effective || caps[i].permitted || caps[i].inheritable)
            return refuse(error,size,"retained Linux capabilities");
    /* Ambient capabilities are a subset of permitted/inheritable; clear them
     * explicitly too. Any failure is fatal before untrusted input is handled. */
    if (prctl(PR_CAP_AMBIENT,PR_CAP_AMBIENT_CLEAR_ALL,0,0,0))
        return refuse(error,size,"cannot clear ambient capabilities");
    if (prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0) || prctl(PR_GET_NO_NEW_PRIVS,0,0,0,0)!=1)
        return refuse(error,size,"cannot lock out privilege acquisition");
    if (prctl(PR_SET_DUMPABLE,0,0,0,0) || prctl(PR_GET_DUMPABLE,0,0,0,0)!=0)
        return refuse(error,size,"cannot disable process dumps");
    if (error && size) error[0]=0;
    return 0;
}
