#!/bin/bash
# HTTPS: eigene kleine Zertifizierungsstelle (CA) im Container und das Zertifikat der Webseite. Laeuft als root
# (install.sh legt es als /usr/local/sbin/trackingdrs-tls ab; der Webdienst ruft es vor jedem Start auf, ein Timer
# jede Woche).
#
#   trackingdrs-tls              CA anlegen, falls noch keine da ist; Webseiten-Zertifikat erneuern, wenn es fehlt,
#                                in weniger als 30 Tagen ablaeuft oder eine IP-Adresse des Containers nicht enthaelt
#   trackingdrs-tls --neustart   dasselbe, und bei einem neuen Zertifikat den Webdienst neu starten (Timer)
#
# Die CA darf nur Zertifikate fuer das /16-Netz des Containers und seinen Namen ausstellen (Namensbeschraenkung).
# Wer ihr Stammzertifikat auf einem Geraet installiert, vertraut ihr also nur dafuer, nicht fuer fremde Webseiten -
# auch dann nicht, wenn jemand den Container uebernimmt. Weitere Adressen (z.B. die VPN-Adresse) per
# TRACKINGDRS_TLS_IPS="192.168.7.2 10.8.0.20" oder Datei /etc/trackingdrs/tls-ips (eine Adresse je Zeile).
#
# Dateien in /var/lib/trackingdrs/tls (Ordner root:trackingdrs 750):
#   ca.key      Schluessel der CA          root 600 (verlaesst den Container nie)
#   ca.crt      Stammzertifikat der CA     644      (Download: http://<container>/ca.crt)
#   server.key  Schluessel der Webseite    root:trackingdrs 640
#   server.crt  Zertifikat der Webseite    644      (397 Tage, wird vorher erneuert)
set -euo pipefail
DIR="${TLS_DIR:-/var/lib/trackingdrs/tls}"
NAME="$(hostname -s)"
NEUSTART=""
[ "${1:-}" = "--neustart" ] && NEUSTART=1

install -d -o root -g trackingdrs -m 750 "$DIR"
cd "$DIR"

extra=""
[ -r /etc/trackingdrs/tls-ips ] && extra=$(grep -v '^#' /etc/trackingdrs/tls-ips || true)
ips=$(echo "${TRACKINGDRS_TLS_IPS:-$(hostname -I) $extra}" | tr ' ' '\n' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' \
  | grep -v '^127\.' | sort -u || true)
[ -n "$ips" ] || { echo "trackingdrs-tls: keine IPv4-Adresse gefunden" >&2; exit 1; }

# Container in ein anderes Netz umgezogen? Die alte CA darf dafuer nicht ausstellen: sichern und neu anlegen.
if [ -s ca.crt ]; then
  erlaubt_alt=$(openssl x509 -in ca.crt -noout -ext nameConstraints 2>/dev/null || true)
  for ip in $ips; do
    if ! printf '%s\n' "$erlaubt_alt" | grep -qF "IP:${ip%.*.*}.0.0/255.255.0.0"; then
      alt="ca-alt-$(date +%Y%m%d-%H%M%S)"
      mv ca.crt "$alt.crt"; mv ca.key "$alt.key"
      echo "trackingdrs-tls: Adresse $ip liegt ausserhalb der bisherigen CA, alte CA gesichert als $alt.*;" \
           "die Geraete muessen das neue Stammzertifikat installieren"
      break
    fi
  done
fi

if [ ! -s ca.key ] || [ ! -s ca.crt ]; then
  netze=$(for ip in $ips; do echo "${ip%.*.*}.0.0"; done | sort -u)
  erlaubt="permitted;DNS:$NAME,permitted;DNS:$NAME.local"
  for n in $netze; do erlaubt="$erlaubt,permitted;IP:$n/255.255.0.0"; done
  ( umask 077; openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out ca.key 2>/dev/null )
  openssl req -x509 -new -key ca.key -sha256 -days 3650 -out ca.crt \
    -subj "/O=TrackingDRS/CN=TrackingDRS $NAME" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "nameConstraints=critical,$erlaubt"
  chmod 600 ca.key; chmod 644 ca.crt
  rm -f server.crt
  echo "trackingdrs-tls: neue Zertifizierungsstelle (erlaubt: $erlaubt)"
fi

erneuern=""
if [ ! -s server.key ] || [ ! -s server.crt ]; then
  erneuern="fehlt"
elif ! openssl x509 -in server.crt -noout -checkend $((30 * 86400)) >/dev/null; then
  erneuern="laeuft bald ab"
elif ! openssl verify -CAfile ca.crt server.crt >/dev/null 2>&1; then
  erneuern="passt nicht zur CA"
else
  for ip in $ips; do
    openssl x509 -in server.crt -noout -ext subjectAltName 2>/dev/null | grep -qE "IP Address:${ip//./\\.}(,|$)" \
      || erneuern="neue IP $ip"
  done
fi

if [ -n "$erneuern" ]; then
  san="DNS:$NAME,DNS:$NAME.local"
  for ip in $ips; do san="$san,IP:$ip"; done
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  ( umask 077; openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$tmp/server.key" 2>/dev/null )
  openssl req -new -key "$tmp/server.key" -subj "/O=TrackingDRS/CN=$NAME" -out "$tmp/server.csr"
  printf 'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\nsubjectAltName=%s\n' \
    "$san" > "$tmp/ext.cnf"
  openssl x509 -req -in "$tmp/server.csr" -CA ca.crt -CAkey ca.key -CAcreateserial -sha256 -days 397 \
    -extfile "$tmp/ext.cnf" -out "$tmp/server.crt" 2>/dev/null
  openssl verify -CAfile ca.crt "$tmp/server.crt" >/dev/null
  install -o root -g trackingdrs -m 640 "$tmp/server.key" server.key
  install -o root -g root -m 644 "$tmp/server.crt" server.crt
  echo "trackingdrs-tls: Zertifikat der Webseite neu ($erneuern): $san"
  if [ -n "$NEUSTART" ]; then
    systemctl try-restart trackingdrs.service
  fi
fi
