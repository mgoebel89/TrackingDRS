"""WireGuard (Stufe G): Angaben fuer "trackingdrs vpn einrichten" pruefen.

Aufruf aus deploy/vpn.sh (als root, im Repo-Ordner):
  python3 -m app.vpn pruefen <server:port> <schluessel> <adresse> "<netze>" [<server-ip>]
Ausgabe: adresse|netze|server-ip (bereinigt), sonst eine Fehlermeldung und Exit 1.
"""
import base64
import ipaddress
import re
import subprocess
import sys


class VpnFehler(Exception):
    pass


def eigene_netze():
    """Netze der anderen Schnittstellen (eth0 im Schulnetz): das VPN darf sie nicht ueberdecken."""
    aus = subprocess.run(["ip", "-4", "-o", "addr", "show", "scope", "global"], capture_output=True, text=True).stdout
    netze = []
    for zeile in aus.splitlines():
        teile = zeile.split()
        if len(teile) >= 4 and teile[2] == "inet" and teile[1] != "wg0":
            netze.append((teile[1], ipaddress.ip_interface(teile[3]).network))
    return netze


def pruefen(server, schluessel, adresse, netze, server_ip="", lokal=()):
    """Gibt (adresse, [netze], server_ip) zurueck oder wirft VpnFehler mit einem Hinweis, wo die Angabe steht."""
    server = (server or "").strip()
    m = re.fullmatch(r"([A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\]):(\d{1,5})", server)
    if not m or not 0 < int(m.group(2)) < 65536:
        raise VpnFehler("Server bitte als Adresse:Port, z. B. vpn.example.de:51820 (Port = ListenPort der Server-Config).")
    try:
        roh = base64.b64decode((schluessel or "").strip(), validate=True)
    except ValueError:
        roh = b""
    if len(roh) != 32:
        raise VpnFehler("Der öffentliche Schlüssel des Servers hat 44 Zeichen und endet auf „=“. "
                        "Auf dem Server: wg show wg0 public-key (nicht den PrivateKey aus der Config nehmen).")
    try:
        a = ipaddress.IPv4Address((adresse or "").strip().split("/")[0])
    except ValueError:
        raise VpnFehler("Die VPN-Adresse des Containers bitte als IPv4-Adresse, z. B. 10.8.0.20.") from None
    liste = []
    for n in (netze or "").replace(",", " ").split():
        try:
            liste.append(ipaddress.IPv4Network(n, strict=False))
        except ValueError:
            raise VpnFehler("Netz ungültig: %s (z. B. 10.8.0.0/24)" % n) from None
    if not liste:
        liste = [ipaddress.IPv4Network("%s/24" % a, strict=False)]
    if any(n.prefixlen < 8 for n in liste):
        raise VpnFehler("Nur das VPN-Netz (und ggf. das Heimnetz) soll über den Tunnel laufen, nicht alles (0.0.0.0/0).")
    if not any(a in n for n in liste):
        raise VpnFehler("Die VPN-Adresse %s liegt in keinem der Netze %s." % (a, " ".join(map(str, liste))))
    for name, netz in lokal:
        for n in liste:
            if n.overlaps(netz):
                raise VpnFehler("%s überschneidet sich mit dem Netz von %s (%s): dann wäre der Container dort nicht mehr "
                                "erreichbar." % (n, name, netz))
    try:
        s = ipaddress.IPv4Address(server_ip.strip()) if server_ip and server_ip.strip() else next(liste[0].hosts())
    except ValueError:
        raise VpnFehler("Die VPN-Adresse des Servers bitte als IPv4-Adresse, z. B. 10.8.0.1.") from None
    if s == a:
        raise VpnFehler("Container und Server können nicht dieselbe VPN-Adresse haben.")
    return str(a), [str(n) for n in liste], str(s)


def main(argv):
    if len(argv) < 5 or argv[0] != "pruefen":
        print(__doc__)
        return 1
    try:
        a, netze, s = pruefen(argv[1], argv[2], argv[3], argv[4], argv[5] if len(argv) > 5 else "", eigene_netze())
    except VpnFehler as f:
        print("Fehler: %s" % f, file=sys.stderr)
        return 1
    print("%s|%s|%s" % (a, " ".join(netze), s))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
