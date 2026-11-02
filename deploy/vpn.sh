#!/bin/bash
# WireGuard (Stufe G): der Container als Teilnehmer im bestehenden VPN, damit der Lehrerbereich von zuhause erreichbar
# ist. Als /usr/local/sbin/trackingdrs-vpn installiert, Aufruf als root ueber "trackingdrs vpn ...".
#
#   trackingdrs vpn einrichten   fragt Server (Adresse:Port), oeffentlichen Schluessel des Servers, VPN-Adresse des
#                                Containers und die Netze ueber das VPN. Erzeugt den Schluessel im Container (er verlaesst
#                                ihn nie), schreibt /etc/wireguard/wg0.conf, nimmt die VPN-Adresse ins Zertifikat auf,
#                                startet die Verbindung und zeigt den Block fuer die Server-Config.
#   trackingdrs vpn status       Verbindung, letzter Handshake, Ping zum Server
#   trackingdrs vpn server       den Block fuer die Server-Config noch einmal zeigen
#   trackingdrs vpn aus          Verbindung beenden und beim Start nicht mehr aufbauen (Schluessel und Config bleiben)
#
# Ohne Rueckfragen:
#   trackingdrs vpn einrichten --server vpn.example.de:51820 --server-schluessel <44 Zeichen> --adresse 10.8.0.20 \
#     [--netze "10.8.0.0/24 192.168.178.0/24"] [--server-ip 10.8.0.1]
#
# Sicherheit: Nur die angegebenen Netze laufen ueber den Tunnel (kein 0.0.0.0/0), der Container leitet nichts weiter,
# und die Firewall (deploy/firewall.nft) laesst auf wg0 nur HTTPS (443) herein. Auf dem Server bekommt der Container
# nur seine eine Adresse (AllowedIPs .../32); die Sperrregeln dort folgen in Stufe G.
set -euo pipefail
WG=/etc/wireguard
CONF=$WG/wg0.conf
SCHLUESSEL=$WG/trackingdrs.key
TLS_IPS=/etc/trackingdrs/tls-ips
REPO=/opt/trackingdrs

[ "$(id -u)" = 0 ] || { echo "Bitte als root ausfuehren."; exit 1; }

fehler() { echo "Fehler: $*" >&2; exit 1; }

frage() {   # frage <Text> <Vorgabe>: Antwort von der Konsole, leer = Vorgabe
  local antwort
  [ -t 0 ] || fehler "$1: bitte als Option angeben (siehe Kopf von trackingdrs-vpn)."
  read -r -p "$1${2:+ [$2]}: " antwort
  echo "${antwort:-$2}"
}

aus_conf() {   # aus_conf <Schluessel>: Wert aus der vorhandenen wg0.conf (Vorgabe beim erneuten Einrichten)
  [ -r "$CONF" ] && sed -n "s/^$1 *= *//p" "$CONF" | head -1 || true
}

server_block() {
  local pub adresse
  [ -s "$SCHLUESSEL" ] && [ -r "$CONF" ] || fehler "Noch nicht eingerichtet: trackingdrs vpn einrichten"
  pub=$(wg pubkey < "$SCHLUESSEL")
  adresse=$(aus_conf Address); adresse=${adresse%/*}
  cat <<EOF

=== Auf dem Server in dessen WireGuard-Config (z. B. /etc/wireguard/wg0.conf) einfuegen: ===

[Peer]
# TrackingDRS $(hostname -s): nur diese eine Adresse
PublicKey = $pub
AllowedIPs = $adresse/32

=== Danach auf dem Server uebernehmen (ohne bestehende Verbindungen zu trennen): ===
  wg syncconf wg0 <(wg-quick strip wg0)
Dann hier pruefen: trackingdrs vpn status
EOF
}

testen() {   # testen <Server-IP>: wartet kurz auf den ersten Handshake
  local server_ip=$1 hs=0
  for _ in $(seq 1 8); do
    hs=$(wg show wg0 latest-handshakes 2>/dev/null | awk '{print $2}' | head -1)
    [ "${hs:-0}" != 0 ] && break
    sleep 1
  done
  if [ "${hs:-0}" = 0 ]; then
    echo "Noch keine Verbindung zum Server. Steht der Block unten schon in der Server-Config? Ist ausgehendes UDP"
    echo "zum Port des Servers frei? Spaeter erneut pruefen: trackingdrs vpn status"
    return 1
  fi
  echo "Verbindung steht (letzter Handshake vor $(( $(date +%s) - hs )) s)."
  if ping -c 1 -W 2 "$server_ip" >/dev/null 2>&1; then echo "Server $server_ip antwortet."; else
    echo "Server $server_ip antwortet nicht auf Ping (das kann so gewollt sein)."; fi
}

einrichten() {
  local server="" schl="" adresse="" netze="" server_ip=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --server) server=$2; shift 2 ;;
      --server-schluessel) schl=$2; shift 2 ;;
      --adresse) adresse=$2; shift 2 ;;
      --netze) netze=$2; shift 2 ;;
      --server-ip) server_ip=$2; shift 2 ;;
      *) fehler "Unbekannte Option $1" ;;
    esac
  done
  local alt_adresse; alt_adresse=$(aus_conf Address)
  if [ -z "$server" ] || [ -z "$schl" ] || [ -z "$adresse" ]; then
    echo "WireGuard fuer TrackingDRS einrichten. Die Angaben findest du so:"
    echo "  Port: ListenPort in der Server-Config. Adresse: oeffentlicher Name oder IP des Servers."
    echo "  Schluessel: auf dem Server  wg show wg0 public-key  (den PrivateKey bitte nirgends eintippen)."
    echo "  VPN-Adresse: eine freie Adresse im VPN-Netz (in der Server-Config bei keinem [Peer] unter AllowedIPs)."
    echo
  fi
  [ -n "$server" ] || server=$(frage "Server (Adresse:Port)" "$(aus_conf Endpoint)")
  [ -n "$schl" ] || schl=$(frage "Oeffentlicher Schluessel des Servers" "$(aus_conf PublicKey)")
  [ -n "$adresse" ] || adresse=$(frage "VPN-Adresse dieses Containers" "${alt_adresse%/*}")
  if [ -z "$netze" ]; then
    netze=$(aus_conf AllowedIPs | tr -d ',')
    [ -t 0 ] && [ -z "$netze" ] && netze=$(frage "Netze ueber das VPN (VPN-Netz, ggf. Heimnetz hinter der Fritzbox)" "${adresse%.*}.0/24")
  fi
  local erg
  erg=$(cd "$REPO" && python3 -m app.vpn pruefen "$server" "$schl" "$adresse" "$netze" "$server_ip") || exit 1
  IFS='|' read -r adresse netze server_ip <<< "$erg"

  if ! command -v wg-quick >/dev/null; then
    echo "==> wireguard-tools installieren"
    export DEBIAN_FRONTEND=noninteractive
    apt-get install -y -q --no-install-recommends wireguard-tools >/dev/null 2>&1 \
      || { apt-get update -q >/dev/null; apt-get install -y -q --no-install-recommends wireguard-tools >/dev/null; }
  fi
  install -d -o root -g root -m 700 "$WG"
  if [ ! -s "$SCHLUESSEL" ]; then
    ( umask 077; wg genkey > "$SCHLUESSEL" )
    echo "==> Neuer Schluessel fuer den Container erzeugt"
  fi

  echo "==> $CONF"
  ( umask 077; cat > "$CONF.neu" <<EOF
# TrackingDRS: Verbindung zum WireGuard-Server (trackingdrs vpn einrichten). Nur diese Netze laufen ueber den Tunnel.
# Der Schluessel liegt in $SCHLUESSEL und verlaesst den Container nicht.
# Server-IP = $server_ip
[Interface]
Address = $adresse/32
PostUp = wg set %i private-key $SCHLUESSEL

[Peer]
PublicKey = $schl
Endpoint = $server
AllowedIPs = ${netze// /, }
# hinter dem Router der Schule: Verbindung offen halten, damit der Server den Container erreicht
PersistentKeepalive = 25
EOF
  )
  mv -f "$CONF.neu" "$CONF"

  echo "==> Zertifikat (VPN-Adresse dazu)"
  install -d -m 755 /etc/trackingdrs
  touch "$TLS_IPS"
  [ -n "$alt_adresse" ] && [ "${alt_adresse%/*}" != "$adresse" ] && sed -i "/^${alt_adresse%/*}\$/d" "$TLS_IPS"
  grep -qx "$adresse" "$TLS_IPS" || echo "$adresse" >> "$TLS_IPS"
  local tls; tls=$(/usr/local/sbin/trackingdrs-tls --neustart)
  [ -n "$tls" ] && echo "$tls"
  if printf '%s' "$tls" | grep -q "neue Zertifizierungsstelle"; then
    echo "  HINWEIS: Das Stammzertifikat ist neu. Auf den Geraeten erneut installieren: http://<container>/ca.crt"
  fi

  echo "==> Verbindung starten"
  systemctl enable -q wg-quick@wg0
  systemctl restart wg-quick@wg0
  testen "$server_ip" || true
  server_block
  echo "Von zuhause (ueber das VPN) dann: https://$adresse"
}

status() {
  [ -r "$CONF" ] || { echo "VPN nicht eingerichtet (trackingdrs vpn einrichten)."; return 1; }
  echo "Dienst: $(systemctl is-active wg-quick@wg0 || true), beim Start: $(systemctl is-enabled wg-quick@wg0 2>/dev/null || true)"
  wg show wg0 2>/dev/null || { echo "wg0 ist nicht aktiv."; return 1; }
  echo
  testen "$(aus_conf "# Server-IP")"
}

case "${1:-}" in
  einrichten) shift; einrichten "$@" ;;
  status) status ;;
  server) server_block ;;
  aus) systemctl disable --now wg-quick@wg0 2>/dev/null || true; echo "VPN aus. Wieder an: trackingdrs vpn einrichten" ;;
  *) sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
