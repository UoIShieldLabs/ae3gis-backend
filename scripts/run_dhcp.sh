#!/bin/sh
set -eu

# Interface and IP you want to serve from.
# Override via env if needed (e.g., IFACE=eth1 IP_CIDR=192.168.0.254/24)
IFACE="${IFACE:-eth0}"
IP_CIDR="${IP_CIDR:-192.168.0.1/24}"

CONF="${CONF:-/etc/dhcp/dhcpd.conf}"
LEASES="${LEASES:-/var/lib/dhcp/dhcpd.leases}"

mkdir -p /var/lib/dhcp /run
[ -f "$LEASES" ] || touch "$LEASES"

# Ensure interface is up with the correct IP (ignore error if already set)
ip addr add "$IP_CIDR" dev "$IFACE" 2>/dev/null || true
ip link set "$IFACE" up

echo "Starting ISC DHCP on $IFACE with $IP_CIDR"
# exec /usr/sbin/dhcpd -4 -f -d -cf "$CONF" -lf "$LEASES" "$IFACE"
/usr/sbin/dhcpd -4 -cf "$CONF" -lf "$LEASES" "$IFACE"