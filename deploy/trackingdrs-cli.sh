#!/bin/sh
# Konsolenbefehle von TrackingDRS (als /usr/local/bin/trackingdrs installiert). Ohne Argument: Hilfe.
cd /opt/trackingdrs || exit 1
exec runuser -u trackingdrs -- env TRACKINGDRS_DATEN=/var/lib/trackingdrs python3 -m app.cli "$@"
