#!/usr/bin/env bash
# TrackingDRS-Testcontainer anlegen. Auf dem Proxmox-Host (Shell des Knotens) als root ausfuehren.
# Nur Testumgebung: Ubuntu 24.04, unprivilegiert, 1 Kern, 1 GB RAM, 8 GB Platte, 192.168.7.2/16.
# Der SSH-Schluessel ist der von Claude (Datei ~/.ssh/trackingdrs_test_ed25519 auf dem PC).
set -euo pipefail

SPEICHER=$(pvesm status -content rootdir | awk 'NR>1 {print $1}' | head -1)
VORLAGEN=$(pvesm status -content vztmpl | awk 'NR>1 {print $1}' | head -1)
pveam update >/dev/null
VORLAGE=$(pveam available --section system | awk '/ubuntu-24\.04-standard/ {print $2}' | sort -V | tail -1)
pveam list "$VORLAGEN" | grep -q "$VORLAGE" || pveam download "$VORLAGEN" "$VORLAGE"
CTID=$(pvesh get /cluster/nextid)

cat > /tmp/trackingdrs-test.pub <<'SCHLUESSEL'
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJTXWnTVyHlRRP1eyee9agQVLrTCs12vZWvrtQgspPBC claude-trackingdrs-test
SCHLUESSEL

pct create "$CTID" "$VORLAGEN:vztmpl/$VORLAGE" --hostname trackingdrs-test \
  --cores 1 --memory 1024 --swap 512 --rootfs "$SPEICHER:8" \
  --net0 name=eth0,bridge=vmbr0,ip=192.168.7.2/16,gw=192.168.2.1 --nameserver 192.168.2.1 \
  --unprivileged 1 --features nesting=1 --onboot 1 --ostype ubuntu \
  --ssh-public-keys /tmp/trackingdrs-test.pub --description "TrackingDRS Testumgebung (nicht produktiv)"
rm -f /tmp/trackingdrs-test.pub
pct start "$CTID"
echo "Fertig: Container $CTID (trackingdrs-test) laeuft auf 192.168.7.2"
