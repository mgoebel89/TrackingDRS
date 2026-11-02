"""Tests fuer "trackingdrs vpn einrichten": Angaben aus der Server-Config pruefen (app/vpn.py) und Firewall auf wg0."""
import io
import ipaddress
import pathlib
import shutil
import socket
import tempfile
import unittest
from unittest import mock

from app import vpn

SCHLUESSEL = "xTIBA5rboUvnH4htodjb6e697QjLERt1NAB4mZqp8Dg="   # Beispiel aus der WireGuard-Doku (oeffentlich)
SCHULE = [("eth0", ipaddress.IPv4Network("192.168.0.0/16"))]


class Pruefen(unittest.TestCase):
    def test_ueblicher_fall(self):
        self.assertEqual(vpn.pruefen("vpn.example.de:51820", SCHLUESSEL, "10.8.0.20", "", "", SCHULE),
                         ("10.8.0.20", ["10.8.0.0/24"], "10.8.0.1"))
        self.assertEqual(vpn.pruefen("203.0.113.5:443", " " + SCHLUESSEL + " ", "10.8.0.20/24", "10.8.0.0/24, 172.16.5.0/24",
                                     "10.8.0.254", SCHULE), ("10.8.0.20", ["10.8.0.0/24", "172.16.5.0/24"], "10.8.0.254"))

    def test_hinweise_bei_falschen_angaben(self):
        faelle = [
            (("vpn.example.de", SCHLUESSEL, "10.8.0.20", ""), "Adresse:Port"),
            (("vpn.example.de:70000", SCHLUESSEL, "10.8.0.20", ""), "Adresse:Port"),
            (("vpn.example.de:51820", "PrivateKey = abc", "10.8.0.20", ""), "wg show wg0 public-key"),
            (("vpn.example.de:51820", SCHLUESSEL[:-4] + "====", "10.8.0.20", ""), "44 Zeichen"),
            (("vpn.example.de:51820", SCHLUESSEL, "10.8.0", ""), "IPv4"),
            (("vpn.example.de:51820", SCHLUESSEL, "10.8.0.20", "0.0.0.0/0"), "nicht alles"),
            (("vpn.example.de:51820", SCHLUESSEL, "10.8.0.20", "10.9.0.0/24"), "in keinem der Netze"),
            (("vpn.example.de:51820", SCHLUESSEL, "10.8.0.20", "10.8.0.0/24 192.168.178.0/24"), "eth0"),   # Schulnetz
        ]
        for argumente, hinweis in faelle:
            with self.subTest(argumente=argumente):
                with self.assertRaises(vpn.VpnFehler) as f:
                    vpn.pruefen(*argumente, lokal=SCHULE)
                self.assertIn(hinweis, str(f.exception))
        with self.assertRaises(vpn.VpnFehler):
            vpn.pruefen("vpn.example.de:51820", SCHLUESSEL, "10.8.0.1", "", "", SCHULE)   # gleiche Adresse wie der Server

    def test_aufruf_wie_aus_dem_skript(self):
        with mock.patch.object(vpn, "eigene_netze", return_value=SCHULE), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as aus, mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(vpn.main(["pruefen", "vpn.example.de:51820", SCHLUESSEL, "10.8.0.20", "", "10.8.0.1"]), 0)
            self.assertEqual(vpn.main(["pruefen", "vpn.example.de:51820", SCHLUESSEL, "192.168.7.9", "192.168.7.0/24"]), 1)
            self.assertEqual(vpn.main([]), 1)
        self.assertTrue(aus.getvalue().startswith("10.8.0.20|10.8.0.0/24|10.8.0.1\n"))
        self.assertIn("eth0", err.getvalue())


KONF = """# TrackingDRS: Verbindung zum WireGuard-Server
# Server-IP = 10.8.0.1
[Interface]
Address = 10.8.0.20/32
PostUp = wg set %i private-key /etc/wireguard/trackingdrs.key

[Peer]
PublicKey = xTIBA5rboUvnH4htodjb6e697QjLERt1NAB4mZqp8Dg=
Endpoint = vpn.example.de:51820
AllowedIPs = 10.8.0.0/24, 192.168.178.0/24
PersistentKeepalive = 25
"""


class Sperrtest(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ordner, True)
        p = mock.patch.object(vpn, "VPN_DIR", self.ordner)
        p.start()
        self.addCleanup(p.stop)

    def test_ziele_aus_der_config(self):
        adresse, netze, server = vpn.konf_lesen(KONF)
        self.assertEqual((str(adresse), [str(n) for n in netze], str(server)), ("10.8.0.20", ["10.8.0.0/24", "192.168.178.0/24"], "10.8.0.1"))
        # Server, ein weiterer VPN-Teilnehmer, Fritzbox und das naechste Geraet im Heimnetz; der Container selbst nie
        self.assertEqual(vpn.sperrziele(adresse, netze, server), ["10.8.0.1", "10.8.0.2", "192.168.178.1", "192.168.178.2"])
        a = ipaddress.IPv4Address("10.8.0.2")
        self.assertEqual(vpn.sperrziele(a, [ipaddress.IPv4Network("10.8.0.0/24")], None), ["10.8.0.1"])

    def test_ergebnisse(self):
        verbunden = lambda: (12, True)
        dicht = vpn.sperrtest(KONF, verbunden, lambda ziele: vpn.proben(ziele, tcp=lambda z, p: False, ping=lambda z: False))
        self.assertEqual((dicht["ergebnis"], dicht["durch"]), ("dicht", []))
        self.assertEqual(len(dicht["proben"]), 4 * (1 + len(vpn.PORTS)))
        offen = vpn.sperrtest(KONF, verbunden, lambda ziele: vpn.proben(
            ziele, tcp=lambda z, p: z == "192.168.178.1" and p == 80, ping=lambda z: z == "10.8.0.1"))
        self.assertEqual((offen["ergebnis"], offen["durch"]), ("offen", ["10.8.0.1 Ping", "192.168.178.1 TCP 80"]))
        nie = lambda ziele: self.fail("ohne Verbindung wird nicht geprobt")
        self.assertEqual(vpn.sperrtest(KONF, lambda: (None, True), nie)["ergebnis"], "keine_verbindung")
        self.assertEqual(vpn.sperrtest(KONF, lambda: (vpn.HANDSHAKE_MAX + 1, True), nie)["ergebnis"], "keine_verbindung")
        self.assertEqual(vpn.sperrtest(KONF, lambda: (None, False), nie)["ergebnis"], "aus")

    def test_ablegen_und_fuer_den_lehrerbereich(self):
        self.assertIsNone(vpn.kurz())   # ohne VPN keine Karte
        erg = vpn.sperrtest(KONF, lambda: (5, True), lambda ziele: [("10.8.0.1", "TCP 22", True)])
        vpn.ablegen(erg)
        k = vpn.kurz()
        self.assertEqual((k["ergebnis"], k["durch"], k["adresse"], k["alt"]), ("offen", ["10.8.0.1 TCP 22"], "10.8.0.20", False))
        vpn.ablegen(dict(erg, zeit="2020-01-01T05:30:00"))
        self.assertTrue(vpn.kurz()["alt"])

    def test_tcp_abgelehnt_heisst_durchgekommen(self):
        # "abgelehnt" (RST) heisst: die Gegenseite hat geantwortet. Nur Zeitueberschreitung oder keine Route = gesperrt.
        for fehler, durch in ((ConnectionRefusedError, True), (socket.timeout, False), (OSError(113, "No route"), False)):
            with self.subTest(fehler=fehler), mock.patch.object(socket, "create_connection", side_effect=fehler):
                self.assertEqual(vpn._tcp("10.8.0.1", 22), durch)
        with mock.patch.object(socket, "create_connection") as verbindung:
            self.assertTrue(vpn._tcp("10.8.0.1", 22))
            verbindung.return_value.close.assert_called_once()


class Firewall(unittest.TestCase):
    def test_wg0_nur_https(self):
        regeln = (pathlib.Path(__file__).resolve().parent.parent / "deploy" / "firewall.nft").read_text(encoding="utf-8")
        zeilen = [z.strip() for z in regeln.splitlines()]
        self.assertIn('iifname "wg0" tcp dport 443 accept', zeilen)
        self.assertIn('iifname "wg0" drop', zeilen)
        # der Drop muss vor den allgemeinen Freigaben (22, 80, Ping) stehen
        self.assertLess(zeilen.index('iifname "wg0" drop'), zeilen.index("tcp dport { 22, 80, 443 } accept"))
        self.assertLess(zeilen.index('iifname "wg0" drop'), zeilen.index("meta l4proto { icmp, ipv6-icmp } accept"))

    def test_sperre_auf_dem_server(self):
        skript = (pathlib.Path(__file__).resolve().parent.parent / "vps" / "sperre.sh").read_text(encoding="utf-8")
        zeilen = [z.strip() for z in skript.splitlines()]
        for kette in ("eingang", "weiter"):
            with self.subTest(kette=kette):
                # erst Antworten durchlassen, dann alles Neue vom Container verwerfen; Hooks vor den uebrigen Regeln
                rumpf = zeilen[zeilen.index("chain %s {" % kette):]
                self.assertTrue(rumpf[1].startswith("type filter hook") and "priority filter - 10; policy accept;" in rumpf[1])
                self.assertEqual(rumpf[2], "ip saddr @container ct state established,related accept")
                self.assertTrue(rumpf[3].startswith("ip saddr @container counter drop"))
        self.assertIn("ip daddr @container tcp dport 443 ct state new accept", zeilen)
