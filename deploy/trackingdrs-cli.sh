#!/bin/sh
# Konsolenbefehle von TrackingDRS (als /usr/local/bin/trackingdrs installiert). Ohne Argument: Hilfe.
cd /opt/trackingdrs || exit 1
# WireGuard braucht root: trackingdrs vpn ... (deploy/vpn.sh)
if [ "${1:-}" = vpn ]; then
  shift
  exec /usr/local/sbin/trackingdrs-vpn "$@"
fi
exec runuser -u trackingdrs -- env TRACKINGDRS_DATEN=/var/lib/trackingdrs python3 -m app.cli "$@"
