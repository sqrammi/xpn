#!/bin/bash
# Installed-package check: private network, separate runtime/state, no boot enable.
set -euo pipefail
work=$1
unit=xpn-gateway-releasecheck.service
unitfile=/run/systemd/system/$unit
fixture=/run/xpn-gateway-releasecheck-fixture.py
runtime=/run/xpn-gateway-releasecheck
state=/var/lib/xpn-gateway-releasecheck
for path in "$unitfile" "$fixture" "$runtime" "$state"; do
  test ! -e "$path" || { echo "Refusing existing smoke-test path: $path"; exit 1; }
done
if systemctl cat "$unit" >/dev/null 2>&1; then exit 1; fi
cleanup() {
  systemctl stop "$unit" || true
  journalctl -u "$unit" --no-pager > "$work/gateway-service-journal.log"
  rm -f "$unitfile" "$fixture" "$state/policy.json"
  rmdir "$state" 2>/dev/null || true
  systemctl daemon-reload
  systemctl reset-failed "$unit" 2>/dev/null || true
}
trap cleanup EXIT
umask 077
cat > "$fixture" <<'PY'
import functools, importlib.util, os, pathlib, subprocess
assert str(pathlib.Path('/proc/self/ns/net').readlink()) != os.environ['XPN_TEST_HOST_NETNS']
subprocess.run(['/usr/sbin/nft', '-f', '-'], input='table inet xpn {\n chain gateway_forward { }\n chain gateway_nat { }\n}\n', text=True, check=True)
subprocess.run(['/usr/sbin/ip', 'link', 'add', 'wg0', 'type', 'wireguard'], check=True)
spec = importlib.util.spec_from_file_location('gateway', '/usr/share/xpn/deploy/gateway.py')
gateway = importlib.util.module_from_spec(spec); spec.loader.exec_module(gateway)
gateway.SOCKET = '/run/xpn-gateway-releasecheck/control.sock'
gateway.Gateway = functools.partial(gateway.Gateway, path=pathlib.Path('/var/lib/xpn-gateway-releasecheck/policy.json'))
gateway.main()
PY
python3 - "$unitfile" "$fixture" <<'PY'
import pathlib, sys
text=pathlib.Path('/usr/lib/systemd/system/xpn-gateway.service').read_text()
for line in ['Requires=xpn-network.service\n','After=xpn-network.service\n','PartOf=xpn-network.service\n']:
    assert line in text
    text=text.replace(line, '')
text=text.replace('ExecStart=/usr/bin/python3 /usr/share/xpn/deploy/gateway.py', 'ExecStart=/usr/bin/python3 '+sys.argv[2])
text=text.replace('RuntimeDirectory=xpn-gateway\n', 'RuntimeDirectory=xpn-gateway-releasecheck\n')
text=text.replace('StateDirectory=xpn-gateway\n', 'StateDirectory=xpn-gateway-releasecheck\n')
text=text.replace('[Service]\n', '[Service]\nPrivateNetwork=yes\nEnvironment=XPN_TEST_HOST_NETNS='+str(pathlib.Path('/proc/1/ns/net').readlink())+'\n')
pathlib.Path(sys.argv[1]).write_text(text)
PY
systemd-analyze verify "$unitfile"
systemctl daemon-reload
systemctl start "$unit"
ready() {
  for attempt in $(seq 1 50); do
    test ! -S "$runtime/control.sock" || return 0
    sleep 0.1
  done
  return 1
}
ready
pid=$(systemctl show "$unit" -p MainPID --value)
test "$(readlink /proc/"$pid"/ns/net)" != "$(readlink /proc/1/ns/net)"
grep -q 'CapEff:.*0000000000001000' /proc/"$pid"/status
grep -q 'NoNewPrivs:.*1' /proc/"$pid"/status
request() {
  setpriv --reuid=xpn --regid=xpn --clear-groups --bounding-set=-all --no-new-privs python3 - "$1" <<'PY'
import json, socket, sys
mode=sys.argv[1]
def call(data):
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(5); sock.connect('/run/xpn-gateway-releasecheck/control.sock')
        sock.sendall(json.dumps(data).encode()+b'\n')
        result=json.loads(sock.makefile().readline())
        assert 'error' not in result, result
        return result
state=call({'action':'get'})
if mode == 'enable':
    assert not state['policy']['enabled'] and state['revision']==0
    policy=dict(enabled=True, interface='wg0', sources=['172.9.0.0/16'], targets=[], allDevices=True, tcpPorts=[22], udpPorts=[], allowPing=True)
    result=call(dict(action='set', revision=0, policy=policy))
    assert result['revision']==1 and result['applied']
else:
    assert state['revision']==1 and state['policy']['enabled'] and state['policy']['allDevices']
    result=call(dict(action='set', revision=1, policy={**state['policy'], 'enabled':False}))
    assert result['revision']==2 and not result['policy']['enabled']
PY
}
request enable
test "$(stat -c '%U:%G %a' "$runtime/control.sock")" = 'root:xpn 660'
test "$(stat -c '%U %a' "$state/policy.json")" = 'root 600'
systemctl restart "$unit"
ready
request disable
echo 'PASS: installed gateway sandbox, unprivileged socket access, atomic apply, saved-policy restore and live disable'
