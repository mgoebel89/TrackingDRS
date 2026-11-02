"""Tests fuer "trackingdrs vpn einrichten": Angaben aus der Server-Config pruefen (app/vpn.py) und Firewall auf wg0."""
import io
import ipaddress
import pathlib
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


class Firewall(unittest.TestCase):
    def test_wg0_nur_https(self):
        regeln = (pathlib.Path(__file__).resolve().parent.parent / "deploy" / "firewall.nft").read_text(encoding="utf-8")
        zeilen = [z.strip() for z in regeln.splitlines()]
        self.assertIn('iifname "wg0" tcp dport 443 accept', zeilen)
        self.assertIn('iifname "wg0" drop', zeilen)
        # der Drop muss vor den allgemeinen Freigaben (22, 80, Ping) stehen
        self.assertLess(zeilen.index('iifname "wg0" drop'), zeilen.index("tcp dport { 22, 80, 443 } accept"))
        self.assertLess(zeilen.index('iifname "wg0" drop'), zeilen.index("meta l4proto { icmp, ipv6-icmp } accept"))
