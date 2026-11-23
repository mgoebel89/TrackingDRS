#!/bin/bash
# TrackingDRS (Stufe G): Sperrregeln auf dem WireGuard-Server (VPS). Laeuft auf dem Server, nicht im Container.
#
#   bash sperre.sh einrichten 10.8.0.20 [192.168.7.2]   VPN-Adresse und Zugriffsadresse des Containers
#                                                       (stehen in "trackingdrs vpn server" im Container)
#   bash sperre.sh status
#   bash sperre.sh aus
#
# Vom Container kommen nur Antworten auf bestehende Verbindungen durch. Jede neue Verbindung, die er selbst aufbaut,
# wird verworfen: ins Heimnetz, zu anderen VPN-Teilnehmern und zum Server selbst. Neue Verbindungen zum Container
# gibt es nur auf HTTPS (443). Die Sperre haelt auch, wenn jemand den Container als root uebernimmt.
#
# Eigene nft-Tabelle "trackingdrs_sperre": andere Regeln (ufw, iptables, eigene nft-Tabellen) bleiben, wie sie sind.
# Ein Drop dort ist endgueltig, kein Accept in einer anderen Tabelle hebt ihn auf. Die Tabelle wird vor dem Netz
# geladen (trackingdrs-sperre.service), es gibt also nach einem Neustart keine offene Luecke.
#
# Holen (Repo oeffentlich):
#   curl -fsSLO https://raw.githubusercontent.com/mgoebel89/TrackingDRS/main/vps/sperre.sh
set -euo pipefail
TABELLE=trackingdrs_sperre
REGELN=/etc/trackingdrs-sperre.nft
EINHEIT=/etc/systemd/system/trackingdrs-sperre.service

[ "$(id -u)" = 0 ] || { echo "Bitte als root ausfuehren (sudo bash $0 ...)."; exit 1; }

fehler() { echo "Fehler: $*" >&2; exit 1; }

ipv4() { [[ $1 =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]] || return 1
  local t; for t in "${BASH_REMATCH[@]:1}"; do [ "$t" -le 255 ] || return 1; done; }

peer_pruefen() {   # peer_pruefen <ip> "<alle Adressen in der Sperre>": hat der Peer nur diese Adressen (je /32)?
  local ip=$1 menge=" ${2:-$1} " zeile a erlaubt="" fremd=""
  command -v wg >/dev/null || { echo "  Hinweis: wg nicht gefunden, Peer nicht geprueft."; return; }
  zeile=$(wg show all allowed-ips 2>/dev/null | grep -E "(^|[[:space:]])$ip/32([[:space:]]|$)" || true)
  if [ -z "$zeile" ]; then
    echo "  Hinweis: kein Peer mit AllowedIPs = $ip/32 aktiv. Im Container zeigt  trackingdrs vpn server  den Block."
    return
  fi
  # VPN-Adresse und Zugriffsadresse des Containers stehen beide in der Sperre und duerfen beim Peer stehen
  for a in $(echo "$zeile" | awk '{for (i = 3; i <= NF; i++) print $i}'); do
    if [[ $a == */32 && $menge == *" ${a%/32} "* ]]; then erlaubt="$erlaubt $a"; else fremd="$fremd $a"; fi
  done
  if [ -n "$fremd" ]; then
    echo "  WARNUNG: Der Peer mit $ip hat AllowedIPs, die nicht in der Sperre stehen:$fremd"
    echo "           Fuer den Container gehoeren dort nur seine VPN-Adresse und die Zugriffsadresse hin (je /32), und"
    echo "           beide in die Sperre: bash $0 einrichten <VPN-Adresse> <Zugriffsadresse>"
  else
    echo "  Peer gefunden: $(echo "$zeile" | awk '{print $2}'), AllowedIPs$erlaubt"
  fi
}

einrichten() {
  [ $# -ge 1 ] || fehler "Container-Adresse fehlt: bash $0 einrichten 10.8.0.20 [Zugriffsadresse]"
  local ip menge
  for ip in "$@"; do ipv4 "$ip" || fehler "$ip ist keine IPv4-Adresse (die VPN-Adresse des Containers, z. B. 10.8.0.20)."; done
  menge=$(IFS=,; echo "$*" | sed 's/,/, /g')

  if ! command -v nft >/dev/null; then
    command -v apt-get >/dev/null || fehler "nft fehlt (Paket nftables bitte installieren)."
    echo "==> nftables installieren"
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q nftables >/dev/null
  fi

  echo "==> $REGELN"
  cat > "$REGELN.neu" <<EOF
#!/usr/sbin/nft -f
# TrackingDRS: Sperre fuer den Container im VPN (vps/sperre.sh). Container: $menge
# Neue Verbindungen vom Container: verworfen. Zum Container: nur HTTPS. Antworten: frei.
table inet $TABELLE
delete table inet $TABELLE
table inet $TABELLE {
	set container {
		type ipv4_addr
		elements = { $menge }
	}
	# Pakete an den Server selbst (SSH, DNS, Ping, Web-Oberflaechen ...)
	chain eingang {
		type filter hook input priority filter - 10; policy accept;
		ip saddr @container ct state established,related accept
		ip saddr @container counter drop comment "Container -> Server"
	}
	# Pakete, die der Server weiterleitet (Heimnetz, Fritzbox, andere VPN-Teilnehmer)
	chain weiter {
		type filter hook forward priority filter - 10; policy accept;
		ip saddr @container ct state established,related accept
		ip saddr @container counter drop comment "Container -> VPN/Heimnetz"
		ip daddr @container tcp dport 443 ct state new accept
		ip daddr @container ct state established,related accept
		ip daddr @container counter drop comment "VPN -> Container ausser 443"
	}
}
EOF
  nft -c -f "$REGELN.neu" || { rm -f "$REGELN.neu"; fehler "nft lehnt die Regeln ab (siehe oben)."; }
  mv -f "$REGELN.neu" "$REGELN"

  echo "==> $EINHEIT"
  cat > "$EINHEIT" <<EOF
# TrackingDRS: Sperre fuer den Container im VPN laden, bevor das Netz (und WireGuard) startet.
[Unit]
Description=TrackingDRS: Sperrregeln fuer den Container im VPN
DefaultDependencies=no
Before=network-pre.target shutdown.target
Wants=network-pre.target
Conflicts=shutdown.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f $REGELN
ExecStop=/usr/sbin/nft delete table inet $TABELLE

[Install]
WantedBy=sysinit.target
EOF
  [ -x /usr/sbin/nft ] || sed -i "s#/usr/sbin/nft#$(command -v nft)#g" "$EINHEIT"
  systemctl daemon-reload
  systemctl enable -q trackingdrs-sperre.service
  systemctl restart trackingdrs-sperre.service
  echo "==> Sperre aktiv"
  for ip in "$@"; do peer_pruefen "$ip" "$*"; done
  weiterleitung
  echo
  echo "Im Container pruefen:  trackingdrs vpn sperrtest   (alles muss \"gesperrt\" sein)"
}

weiterleitung() {
  if [ "$(sysctl -n net.ipv4.ip_forward 2>/dev/null || echo 0)" != 1 ]; then
    echo "  Hinweis: net.ipv4.ip_forward ist aus. Dann erreicht auch dein Heimnetz den Container nicht ueber den Server."
  fi
}

status() {
  echo "Dienst: $(systemctl is-active trackingdrs-sperre.service 2>/dev/null || true), beim Start: $(systemctl is-enabled trackingdrs-sperre.service 2>/dev/null || true)"
  if ! nft list table inet "$TABELLE" 2>/dev/null; then
    echo "Sperre NICHT geladen. Einrichten: bash $0 einrichten <Container-Adresse>"
    return 1
  fi
  local ip menge
  menge=$(nft -j list set inet "$TABELLE" container 2>/dev/null | grep -oE '"[0-9]+(\.[0-9]+){3}"' | tr -d '"' | tr '\n' ' ')
  for ip in $menge; do
    peer_pruefen "$ip" "$menge"
  done
  weiterleitung
  echo "Die Zaehler bei \"counter drop\" zeigen, wie oft etwas verworfen wurde."
}

aus() {
  systemctl disable --now trackingdrs-sperre.service 2>/dev/null || true
  nft delete table inet "$TABELLE" 2>/dev/null || true
  echo "Sperre entfernt. Der Container kann jetzt wieder alles im VPN erreichen, was der Server erlaubt."
  echo "Wenn der Container nicht mehr ins VPN soll: seinen [Peer]-Block aus der Server-Config loeschen."
}

case "${1:-}" in
  einrichten) shift; einrichten "$@" ;;
  status) status ;;
  aus) aus ;;
  *) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
