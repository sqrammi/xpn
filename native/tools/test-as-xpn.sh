#!/bin/sh
# Run checkout tests through a temporary read-only bind mount when /root (or a
# private home) prevents the service account from traversing the source path.
# No source copies or host permission changes. Root is needed for mount setup.
# Usage: sudo env PATH="$PATH" sh native/tools/test-as-xpn.sh [--root] COMMAND ...
# --root is only for the TUN harness, which drops its server/Node identities.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run this test wrapper as root.' >&2; exit 1; }
XPN_TEST_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
XPN_RUN_IDENTITY=user
if [ "${1:-}" = --root ]; then XPN_RUN_IDENTITY=root; shift; fi
[ "$#" -gt 0 ] || { echo 'Supply a test command with checkout-relative arguments.' >&2; exit 2; }
XPN_TEST_NODE=$(command -v node)
case "$XPN_TEST_NODE" in
    "$XPN_TEST_ROOT"/*) XPN_TEST_NODE=${XPN_TEST_NODE#"$XPN_TEST_ROOT"/};;
esac
XPN_TEST_VIEW=$(mktemp -d /tmp/xpn-source.XXXXXX)
trap 'rmdir "$XPN_TEST_VIEW"' EXIT
chmod 755 "$XPN_TEST_VIEW"
unshare --mount --propagation private -- sh -eu -c '
    source=$1; view=$2; node=$3; mode=$4; shift 4
    mount --bind "$source" "$view"
    mount -o remount,bind,ro "$view"
    cd "$view"
    case "$node" in /*) ;; *) node=$view/$node;; esac
    PATH=$(dirname "$node"):/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
    export PATH
    if [ "$mode" = root ]; then exec "$@"; fi
    exec setpriv --reuid=xpn --regid=xpn --clear-groups \
      --bounding-set=-all --inh-caps=-all --ambient-caps=-all --no-new-privs "$@"
' sh "$XPN_TEST_ROOT" "$XPN_TEST_VIEW" "$XPN_TEST_NODE" "$XPN_RUN_IDENTITY" "$@"
