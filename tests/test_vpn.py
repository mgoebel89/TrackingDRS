"""Tests fuer "trackingdrs vpn einrichten": Angaben aus der Server-Config pruefen (app/vpn.py) und Firewall auf wg0."""
import base64
import io
import ipaddress
import json
import os
import pathlib
import shutil
import socket
import tempfile
import threading
import unittest
import http.client
from unittest import mock

from app import db, konten, server, vpn

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


class AusDerOberflaeche(unittest.TestCase):
    """Auftraege aus dem Lehrerbereich: Webdienst prueft und legt ab, root liest, prueft erneut und loescht."""

    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ordner, True)
        self.daten = os.path.join(self.ordner, "daten")
        self.einheit = os.path.join(self.ordner, "trackingdrs-vpn-anfrage.path")
        self.konf = os.path.join(self.ordner, "wg0.conf")
        for name, wert in (("VPN_DIR", os.path.join(self.ordner, "stand")), ("EINHEIT", self.einheit), ("KONF", self.konf)):
            p = mock.patch.object(vpn, name, wert)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(vpn, "eigene_netze", return_value=SCHULE)
        p.start()
        self.addCleanup(p.stop)
        self.formular = {"aktion": "einrichten", "server": "203.0.113.5", "port": "51820", "schluessel": SCHLUESSEL,
                         "adresse": "10.8.0.20", "server_ip": "", "netze": "", "server_if": "wg0"}

    def test_server_text(self):
        self.assertEqual(vpn.server_text(" vpn.example.de ", ""), "vpn.example.de:51820")
        self.assertEqual(vpn.server_text("2001:db8::1", "443"), "[2001:db8::1]:443")
        self.assertEqual(vpn.server_text("[2001:db8::1]", "443"), "[2001:db8::1]:443")

    def test_anfrage_hin_und_zurueck(self):
        with self.assertRaises(vpn.VpnFehler):   # ohne Container (Units fehlen)
            vpn.anfordern(self.daten, self.formular)
        open(self.einheit, "w").close()
        for falsch, hinweis in ((dict(self.formular, schluessel="geheim"), "44 Zeichen"),
                                (dict(self.formular, server_if="wg0; rm -rf /"), "Schnittstelle"),
                                (dict(self.formular, netze="10.8.0.0/24 192.168.7.0/24"), "eth0"),
                                ({"aktion": "loeschen"}, "Unbekannte")):
            with self.subTest(hinweis=hinweis), self.assertRaises(vpn.VpnFehler) as f:
                vpn.anfordern(self.daten, falsch)
            self.assertIn(hinweis, str(f.exception))
        vpn.anfordern(self.daten, self.formular)
        self.assertTrue(vpn.web_stand(self.daten)["wartet"])
        with self.assertRaises(vpn.VpnFehler):   # nicht zwei Auftraege auf einmal
            vpn.anfordern(self.daten, {"aktion": "sperrtest"})
        pfad = os.path.join(self.daten, "vpn", "anfrage.json")
        self.assertEqual(vpn.anfrage_lesen(pfad), {"aktion": "einrichten", "server": "203.0.113.5:51820", "schluessel": SCHLUESSEL,
                                                    "adresse": "10.8.0.20", "netze": "10.8.0.0/24", "server_ip": "10.8.0.1",
                                                    "server_if": "wg0", "alle": False})
        self.assertFalse(os.path.exists(pfad))   # gelesen = geloescht
        with self.assertRaises(vpn.VpnFehler):
            vpn.anfrage_lesen(pfad)

    def test_root_prueft_die_datei_noch_einmal(self):
        pfad = os.path.join(self.ordner, "anfrage.json")
        with open(pfad, "w", encoding="utf-8") as f:   # so koennte sie aussehen, wenn jemand den Webdienst uebernimmt
            json.dump(dict(self.formular, server="x:1\nPostUp = rm -rf /"), f)
        with self.assertRaises(vpn.VpnFehler):
            vpn.anfrage_lesen(pfad)
        self.assertFalse(os.path.exists(pfad))
        with open(pfad, "w") as f:
            f.write("{kaputt")
        with self.assertRaises(vpn.VpnFehler):
            vpn.anfrage_lesen(pfad)

    def test_info_fuer_die_seite(self):
        with open(self.konf, "w", encoding="utf-8") as f:
            f.write(KONF + "PrivateKey = darf-nie-auf-die-seite\n")
        info = vpn.info_ablegen(SCHLUESSEL, True, "wg1")
        self.assertEqual((info["adresse"], info["server"], info["server_schluessel"], info["container_schluessel"], info["server_if"]),
                         ("10.8.0.20", "vpn.example.de:51820", SCHLUESSEL, SCHLUESSEL, "wg1"))
        self.assertNotIn("darf-nie", info["konf"])
        self.assertEqual(vpn.info_ablegen(SCHLUESSEL, False)["server_if"], "wg1")   # bleibt beim Ausschalten
        self.assertFalse(vpn.web_stand(self.daten)["einrichtung"]["aktiv"])
        with self.assertRaises(vpn.VpnFehler):
            vpn.info_ablegen("kein schluessel", True)

    def test_haengender_auftrag_blockiert_nicht_ewig(self):
        vpn._schreiben("lauf.json", {"aktion": "einrichten", "beginn": "2020-01-01T10:00:00", "ende": None, "ergebnis": None})
        self.assertFalse(vpn.web_stand(self.daten)["laeuft"])
        vpn._schreiben("lauf.json", {"aktion": "einrichten", "beginn": db.jetzt(), "ende": None, "ergebnis": None})
        self.assertTrue(vpn.web_stand(self.daten)["laeuft"])


PRIVAT = base64.b64encode(bytes(range(32))).decode()        # Testwerte, keine echten Schluessel
PSK = base64.b64encode(bytes(range(32, 64))).decode()
CLIENT = """# Client-Datei fuer den Container, so wie man sie fuer ein Handy schreibt
[Interface]
PrivateKey = %s
Address = 10.8.0.20/24, fd00:8::20/64
DNS = 1.1.1.1

[Peer]
PublicKey = %s
PresharedKey = %s
Endpoint = vpn.example.de:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
""" % (PRIVAT, SCHLUESSEL, PSK)


class ClientDatei(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ordner, True)
        einheit = os.path.join(self.ordner, "einheit.path")
        open(einheit, "w").close()
        self.daten = os.path.join(self.ordner, "daten")
        self.wg = os.path.join(self.ordner, "wireguard")
        for name, wert in (("VPN_DIR", os.path.join(self.ordner, "stand")), ("EINHEIT", einheit),
                           ("SCHLUESSEL", os.path.join(self.wg, "trackingdrs.key")), ("PSK", os.path.join(self.wg, "trackingdrs.psk"))):
            p = mock.patch.object(vpn, name, wert)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(vpn, "eigene_netze", return_value=SCHULE)
        p.start()
        self.addCleanup(p.stop)

    def test_typische_datei(self):
        angaben, privat, psk, hinweise = vpn.conf_einlesen(CLIENT, SCHULE)
        self.assertEqual(angaben, {"server": "vpn.example.de:51820", "schluessel": SCHLUESSEL, "adresse": "10.8.0.20",
                                   "netze": "10.8.0.0/24", "server_ip": "10.8.0.1", "alle": True})
        self.assertEqual((privat, psk), (PRIVAT, PSK))
        text = " ".join(hinweise)
        for teil in ("IPv4-Adresse 10.8.0.20", "0.0.0.0/0", "DNS"):
            self.assertIn(teil, text)

    def test_heimnetz_ja_schulnetz_nein(self):
        datei = CLIENT.replace("AllowedIPs = 0.0.0.0/0, ::/0", "AllowedIPs = 10.8.0.0/24, 192.168.178.0/24, 172.16.5.0/24") \
            .replace("PresharedKey = %s\n" % PSK, "")
        angaben, _, psk, hinweise = vpn.conf_einlesen(datei, [("eth0", ipaddress.IPv4Network("192.168.178.0/24"))])
        self.assertEqual((angaben["netze"], psk), ("10.8.0.0/24 172.16.5.0/24", None))
        self.assertTrue(any("eth0" in h for h in hinweise))
        # Heimnetz mit denselben Adressen wie das Schulnetz: keine Route dorthin, aber alle Absender zulassen
        self.assertTrue(angaben["alle"])
        ohne = datei.replace(", 192.168.178.0/24", "")
        self.assertFalse(vpn.conf_einlesen(ohne, [("eth0", ipaddress.IPv4Network("192.168.178.0/24"))])[0]["alle"])
        # Adresse ohne Netzangabe und VPN-Netz fehlt in AllowedIPs: VPN-Netz /24 kommt dazu, das Schulnetz bleibt draussen
        angaben = vpn.conf_einlesen(datei.replace("Address = 10.8.0.20/24, fd00:8::20/64", "Address = 10.8.0.20/32")
                                    .replace("AllowedIPs = 10.8.0.0/24, ", "AllowedIPs = "), SCHULE)[0]
        self.assertEqual(angaben["netze"], "10.8.0.0/24 172.16.5.0/24")

    def test_falsche_dateien(self):
        faelle = [
            ("hallo", "keine WireGuard-Config"),
            (CLIENT.replace("PrivateKey = " + PRIVAT, "PrivateKey = abc"), "PrivateKey"),
            (CLIENT.replace("Endpoint = vpn.example.de:51820\n", ""), "Endpoint"),
            (CLIENT + "\n[Peer]\nPublicKey = %s\nAllowedIPs = 10.8.0.3/32\n" % SCHLUESSEL, "mehrere [Peer]"),
            (CLIENT.replace("Address = 10.8.0.20/24, fd00:8::20/64", "Address = fd00:8::20/64"), "IPv4"),
            (CLIENT.replace("PresharedKey = " + PSK, "PresharedKey = kurz"), "PresharedKey"),
            (CLIENT + "#" * 4000, "zu groß"),
        ]
        for text, hinweis in faelle:
            with self.subTest(hinweis=hinweis), self.assertRaises(vpn.VpnFehler) as f:
                vpn.conf_einlesen(text, SCHULE)
            self.assertIn(hinweis, str(f.exception))
            self.assertNotIn(PRIVAT, str(f.exception))

    def test_von_der_seite_bis_zu_root(self):
        r = vpn.anfordern(self.daten, {"aktion": "einrichten", "conf": CLIENT, "server_if": "wg1"})
        self.assertNotIn("privat", r)
        self.assertNotIn("psk", r)
        self.assertTrue(r["hinweise"])
        pfad = os.path.join(self.daten, "vpn", "anfrage.json")
        if os.name == "posix":
            self.assertEqual(os.stat(pfad).st_mode & 0o777, 0o600)
        with mock.patch("sys.stdout", new_callable=io.StringIO) as aus, mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(vpn.main(["anfrage-lesen", pfad]), 0)
        self.assertEqual(aus.getvalue().strip(),
                         "einrichten|vpn.example.de:51820|%s|10.8.0.20|10.8.0.0/24|10.8.0.1|wg1|1|1|1" % SCHLUESSEL)
        self.assertNotIn(PRIVAT, aus.getvalue() + err.getvalue())
        self.assertIn("Hinweis:", err.getvalue())
        with open(vpn.SCHLUESSEL) as f:
            self.assertEqual(f.read().strip(), PRIVAT)
        with open(vpn.PSK) as f:
            self.assertEqual(f.read().strip(), PSK)
        # ohne PresharedKey in der neuen Datei verschwindet der alte
        datei = os.path.join(self.ordner, "ohne-psk.conf")
        with open(datei, "w", encoding="utf-8") as f:
            f.write(CLIENT.replace("PresharedKey = %s\n" % PSK, ""))
        with mock.patch("sys.stdout", new_callable=io.StringIO) as aus, mock.patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(vpn.main(["conf-lesen", datei]), 0)
        self.assertTrue(aus.getvalue().strip().endswith("||1|1"))
        self.assertFalse(os.path.exists(vpn.PSK))


class Api(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ordner, True)
        einheit = os.path.join(self.ordner, "einheit.path")
        open(einheit, "w").close()
        for name, wert in (("VPN_DIR", os.path.join(self.ordner, "stand")), ("EINHEIT", einheit)):
            p = mock.patch.object(vpn, name, wert)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(vpn, "eigene_netze", return_value=SCHULE)
        p.start()
        self.addCleanup(p.stop)
        con = db.oeffnen(self.ordner)
        konten.anlegen(con, "gob", "M. Göbel", "admin", "geheim123", vorlaeufig=False)
        konten.anlegen(con, "abc", "A. Beispiel", "lehrkraft", "geheim456", vorlaeufig=False)
        self.cookies = {k: "tdrs=" + konten.anmelden(con, k, pw)[0] for k, pw in (("gob", "geheim123"), ("abc", "geheim456"))}
        con.commit()
        con.close()
        self.srv = server.HTTPServer(("127.0.0.1", 0), server.Handler, os.path.join(self.ordner, "trackingdrs.sqlite"))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def post(self, daten, wer="gob"):
        v = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        v.request("POST", "/api/vpn", body=json.dumps(daten).encode(), headers={
            "X-TrackingDRS": "1", "Content-Type": "application/json", "Cookie": self.cookies[wer]})
        a = v.getresponse()
        d = json.loads(a.read())
        v.close()
        return a.status, d

    def test_einrichten_nur_admin_mit_passwort(self):
        formular = {"aktion": "einrichten", "server": "203.0.113.5", "port": "51820", "schluessel": SCHLUESSEL, "adresse": "10.8.0.20"}
        self.assertEqual(self.post(dict(formular, passwort="geheim456"), "abc")[0], 403)
        status, d = self.post(dict(formular, passwort="falsch"))
        self.assertEqual((status, d["fehler"]), (400, "Das Passwort stimmt nicht."))
        status, d = self.post(dict(formular, passwort="geheim123"))
        self.assertEqual(status, 200, d)
        self.assertTrue(d["wartet"])
        with open(os.path.join(self.ordner, "vpn", "anfrage.json"), encoding="utf-8") as f:
            self.assertNotIn("passwort", f.read())   # das Passwort landet nie in der Anfrage

    def test_client_datei_kommt_nicht_zurueck(self):
        status, d = self.post({"aktion": "einrichten", "conf": CLIENT, "passwort": "geheim123"})
        self.assertEqual(status, 200, d)
        self.assertTrue(d["hinweise"])
        self.assertNotIn(PRIVAT, json.dumps(d))
        self.assertNotIn(PSK, json.dumps(d))


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


class AlleAbsender(unittest.TestCase):
    """Der Lehrerbereich fuer das ganze VPN: Routen nur fuers VPN-Netz, AllowedIPs 0.0.0.0/0, Kennzeichen in wg0.conf."""

    def test_formular_schalter(self):
        d = {"aktion": "einrichten", "server": "vpn.example.de:51820", "schluessel": SCHLUESSEL, "adresse": "10.8.0.20"}
        self.assertFalse(vpn.angaben_pruefen(d, SCHULE)["alle"])
        self.assertTrue(vpn.angaben_pruefen(dict(d, alle=True), SCHULE)["alle"])
        self.assertTrue(vpn.angaben_pruefen({"aktion": "einrichten", "conf": CLIENT.replace("0.0.0.0/0, ::/0", "10.8.0.0/24"),
                                             "alle": True}, SCHULE)["alle"])

    def test_konf_mit_netze_kommentar(self):
        text = """# Server-IP = 10.0.0.1
# Netze = 10.0.0.0/16
# Alle-Absender = ja
[Interface]
Address = 10.0.0.8/32
Table = off
[Peer]
AllowedIPs = 0.0.0.0/0
"""
        adresse, netze, server = vpn.konf_lesen(text)
        self.assertEqual((str(adresse), [str(n) for n in netze], str(server)), ("10.0.0.8", ["10.0.0.0/16"], "10.0.0.1"))
        self.assertTrue(vpn.alle_absender(text))
        self.assertFalse(vpn.alle_absender(text.replace("= ja", "= nein")))
        # Sperrtest zielt nie auf 0.0.0.0/0, auch bei alten Dateien ohne "# Netze"
        alt = """[Interface]
Address = 10.0.0.8/32
[Peer]
AllowedIPs = 0.0.0.0/0
"""
        self.assertEqual(vpn.konf_lesen(alt)[1], [])
