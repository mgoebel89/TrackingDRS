#!/bin/bash
# TrackingDRS im Container installieren oder aktualisieren (Ubuntu 24.04 / Debian 12). Als root aus dem Repo-Ordner:
#
#   git clone https://github.com/mgoebel89/TrackingDRS /opt/trackingdrs && bash /opt/trackingdrs/deploy/install.sh
#
# Legt den Systembenutzer trackingdrs an, Daten in /var/lib/trackingdrs (Datenbank, Zertifikate, spaeter Fotos),
# Dienste: trackingdrs (Webseite 80/443), trackingdrs-tls.timer (Zertifikat), trackingdrs-firewall (nur 22/80/443),
# trackingdrs-update-pruefen.timer/.path und trackingdrs-update-ausfuehren.path (Update aus dem Lehrerbereich),
# trackingdrs-sperrtest.timer (taeglicher Sperrtest, nur mit VPN), trackingdrs-vpn-anfrage.path (VPN aus dem Lehrerbereich).
# Befehle danach: trackingdrs (Konsole, z.B. trackingdrs einrichtungscode), trackingdrs-update.
set -euo pipefail
ZIEL=/opt/trackingdrs
DATEN=/var/lib/trackingdrs

cd "$(dirname "$(readlink -f "$0")")/.."
[ "$(pwd)" = "$ZIEL" ] || { echo "Bitte aus $ZIEL aufrufen (git clone ... $ZIEL)."; exit 1; }
[ "$(id -u)" = 0 ] || { echo "Bitte als root ausfuehren."; exit 1; }

echo "==> Pakete"
fehlt=""
for befehl in python3 openssl nft git; do command -v "$befehl" >/dev/null || fehlt=1; done
[ -e /usr/share/zoneinfo/Europe/Berlin ] || fehlt=1
python3 -c 'import icalendar, recurring_ical_events' 2>/dev/null || fehlt=1   # Kalender-Abos (ICS)
if [ -n "$fehlt" ]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -q >/dev/null
  apt-get install -y -q python3 openssl nftables git ca-certificates tzdata python3-icalendar \
    python3-recurring-ical-events >/dev/null
fi
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "TrackingDRS braucht Python 3.11 oder neuer."; exit 1; }

echo "==> Benutzer und Ordner"
id trackingdrs >/dev/null 2>&1 || useradd --system --home-dir "$DATEN" --shell /usr/sbin/nologin trackingdrs
install -d -o trackingdrs -g trackingdrs -m 750 "$DATEN" "$DATEN/update" "$DATEN/sicherungen" "$DATEN/vpn"
install -d -o root -g root -m 755 /var/lib/trackingdrs-update /var/lib/trackingdrs-vpn   # Update- und Sperrtest-Ergebnisse, fuer den Webdienst nur lesbar
find "$DATEN" -maxdepth 1 -name 'trackingdrs.sqlite*' -exec chmod 640 {} +
install -d -o root -g root -m 755 /etc/trackingdrs
# der Code gehoert root: der Webdienst kann ihn nicht veraendern
chown -R root:root "$ZIEL"
chmod -R go-w "$ZIEL"

echo "==> Befehle, Dienste, Firewall"
install -o root -g root -m 755 deploy/tls.sh /usr/local/sbin/trackingdrs-tls
install -o root -g root -m 755 deploy/update.sh /usr/local/sbin/trackingdrs-update
install -o root -g root -m 755 deploy/selbstupdate.sh /usr/local/sbin/trackingdrs-selbstupdate
install -o root -g root -m 755 deploy/vpn.sh /usr/local/sbin/trackingdrs-vpn
install -o root -g root -m 755 deploy/trackingdrs-cli.sh /usr/local/bin/trackingdrs
install -o root -g root -m 644 deploy/firewall.nft /etc/trackingdrs/firewall.nft
UPDATE_EINHEITEN="trackingdrs-update-pruefen.path trackingdrs-update-pruefen.timer trackingdrs-update-ausfuehren.path trackingdrs-sperrtest.timer trackingdrs-vpn-anfrage.path"
for einheit in trackingdrs.service trackingdrs-tls.service trackingdrs-tls.timer trackingdrs-firewall.service \
    trackingdrs-update-pruefen.service trackingdrs-update-ausfuehren.service trackingdrs-sperrtest.service trackingdrs-vpn-anfrage.service \
    $UPDATE_EINHEITEN; do
  install -o root -g root -m 644 "deploy/$einheit" "/etc/systemd/system/$einheit"
done
systemctl daemon-reload
/usr/local/sbin/trackingdrs-tls
systemctl enable -q trackingdrs-firewall.service trackingdrs-tls.timer trackingdrs.service $UPDATE_EINHEITEN
systemctl restart trackingdrs-firewall.service   # Regeln neu laden (auch nach einem Update)
systemctl start trackingdrs-tls.timer $UPDATE_EINHEITEN
systemctl restart trackingdrs.service

for _ in $(seq 1 20); do
  systemctl is-active --quiet trackingdrs.service && python3 - 2>/dev/null <<'PRUEFEN' && break
import ssl, urllib.request
kontext = ssl.create_default_context(cafile="/var/lib/trackingdrs/tls/ca.crt")
kontext.check_hostname = False
urllib.request.urlopen("https://127.0.0.1/api/status", context=kontext, timeout=3).read()
PRUEFEN
  sleep 1
done
if ! systemctl is-active --quiet trackingdrs.service; then
  journalctl -u trackingdrs.service -n 30 --no-pager
  echo "Der Dienst trackingdrs laeuft nicht (siehe oben)."
  exit 1
fi

# einmal nach einer neueren Version suchen (im Hintergrund, damit die Einstellungen gleich den Stand zeigen)
systemctl start --no-block trackingdrs-update-pruefen.service

ip=$(hostname -I | awk '{print $1}')
code=$(/usr/local/bin/trackingdrs einrichtungscode 2>/dev/null || true)
echo
echo "TrackingDRS laeuft: https://$ip"
echo "  Stammzertifikat fuer die Geraete: http://$ip/ca.crt"
if [ -n "$code" ] && [ "${code#Die Einrichtung}" = "$code" ]; then
  echo "  Erstes Admin-Konto anlegen: https://$ip/einrichtung   Einrichtungscode: $code"
fi
