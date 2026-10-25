#!/bin/sh
# Run once as root on the Ubuntu SERVER. Does not flush existing firewall tables.
set -eu
XPN_WAN_IFACE=${XPN_WAN_IFACE:-$(ip -4 route show default | awk 'NR==1 {print $5}')}
case "$XPN_WAN_IFACE" in ''|*[!a-zA-Z0-9_.:-]*) echo 'Set XPN_WAN_IFACE to your outbound network interface' >&2; exit 1;; esac
id xpn >/dev/null
if ! ip link show xpn0 >/dev/null 2>&1; then ip tuntap add dev xpn0 mode tun user xpn; fi
ip address replace 10.77.0.1/24 dev xpn0
ip link set dev xpn0 mtu 1400 up
sysctl -w net.ipv4.ip_forward=1
sysctl -w net.ipv4.conf.xpn0.rp_filter=2
sysctl -w net.ipv4.conf.xpn0.accept_source_route=0
if nft list table inet xpn >/dev/null 2>&1; then
    # Replace only our table, atomically with the new ruleset below.
    XPN_DELETE='delete table inet xpn'
else XPN_DELETE=''; fi
nft -f - <<EOF
$XPN_DELETE
table inet xpn {
    chain input {
        type filter hook input priority -10; policy accept;
        iifname "xpn0" drop
    }
    chain forward {
        type filter hook forward priority -10; policy accept;
        iifname "xpn0" ip saddr != 10.77.0.0/24 drop
        iifname "xpn0" ip daddr { 10.77.0.0/24, 169.254.0.0/16, 127.0.0.0/8, 224.0.0.0/4 } drop
        iifname "xpn0" oifname "$XPN_WAN_IFACE" accept
        iifname "$XPN_WAN_IFACE" oifname "xpn0" ct state established,related accept
        iifname "xpn0" drop
        oifname "xpn0" drop
    }
    chain nat {
        type nat hook postrouting priority srcnat; policy accept;
        ip saddr 10.77.0.0/24 oifname "$XPN_WAN_IFACE" masquerade
    }
}
EOF
echo 'XPN interface and dedicated nftables table configured.'
echo 'If another firewall has a FORWARD drop policy, add equivalent allow rules there as well.'
