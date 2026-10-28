"""Tests fuer Stufe A: Datenbank, Konten, Projekte, Team-Link und Webserver (ohne TLS).
Aufruf im Repo-Ordner:  python3 -m unittest discover -s tests
"""
import ast
import http.client
import json
import os
import pathlib
import shutil
import tempfile
import threading
import unittest

from app import db, konten, projekte, server

REPO = pathlib.Path(__file__).resolve().parent.parent


class Python311(unittest.TestCase):
    """Der Container hat Python 3.12, das Repo soll aber auch mit 3.11 laufen (Debian 12)."""

    def test_syntax(self):
        for datei in REPO.rglob("*.py"):
            with self.subTest(datei=str(datei.relative_to(REPO))):
                ast.parse(datei.read_text(encoding="utf-8"), feature_version=(3, 11))


class MitDatenbank(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def admin(self, kuerzel="gob"):
        with db.transaktion(self.con):
            return konten.anlegen(self.con, kuerzel, "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)


class Konten(MitDatenbank):
    def test_anmelden_und_sitzung(self):
        k = self.admin()
        wert, konto = konten.anmelden(self.con, "GOB", "geheim123")
        self.assertEqual(konto["id"], k["id"])
        self.assertEqual(konten.sitzung_pruefen(self.con, wert)["kuerzel"], "gob")
        with self.assertRaises(konten.KontoFehler):
            konten.anmelden(self.con, "gob", "falsch123")
        with self.assertRaises(konten.KontoFehler):
            konten.anmelden(self.con, "xyz", "geheim123")

    def test_passwortwechsel_beendet_alte_anmeldungen(self):
        k = self.admin()
        wert, _ = konten.anmelden(self.con, "gob", "geheim123")
        with db.transaktion(self.con):
            konten.passwort_aendern(self.con, k["id"], "geheim123", "neuesPasswort")
        self.assertIsNone(konten.sitzung_pruefen(self.con, wert))
        neu, _ = konten.anmelden(self.con, "gob", "neuesPasswort")
        self.assertIsNotNone(konten.sitzung_pruefen(self.con, neu))

    def test_abmelden_und_ablauf_und_faelschung(self):
        self.admin()
        wert, _ = konten.anmelden(self.con, "gob", "geheim123")
        self.assertIsNone(konten.sitzung_pruefen(self.con, wert, uhr=10 ** 12))
        self.assertIsNone(konten.sitzung_pruefen(self.con, wert[:-1] + ("0" if wert[-1] != "0" else "1")))
        konten.abmelden(self.con, wert)
        self.assertIsNone(konten.sitzung_pruefen(self.con, wert))

    def test_letzter_admin_bleibt(self):
        k = self.admin()
        with self.assertRaises(konten.KontoFehler):
            konten.aendern(self.con, k["id"], rolle="lehrkraft")
        with self.assertRaises(konten.KontoFehler):
            konten.aendern(self.con, k["id"], gesperrt=True)

    def test_gesperrtes_konto(self):
        self.admin()
        with db.transaktion(self.con):
            l = konten.anlegen(self.con, "scu", "Herr Schu", "lehrkraft", "start12345")
        wert, konto = konten.anmelden(self.con, "scu", "start12345")
        self.assertTrue(konto["pw_vorlaeufig"])
        konten.aendern(self.con, l["id"], gesperrt=True)
        self.assertIsNone(konten.sitzung_pruefen(self.con, wert))
        with self.assertRaises(konten.KontoFehler):
            konten.anmelden(self.con, "scu", "start12345")

    def test_kuerzel_und_passwortregeln(self):
        with self.assertRaises(konten.KontoFehler):
            konten.anlegen(self.con, "G", "Name", "admin", "geheim123")
        with self.assertRaises(konten.KontoFehler):
            konten.anlegen(self.con, "gob", "Name", "admin", "kurz")
        self.admin()
        with self.assertRaises(konten.KontoFehler):
            konten.anlegen(self.con, "gob", "Name", "admin", "geheim123")

    def test_einrichtung(self):
        code = konten.einrichtungscode(self.con)
        self.assertRegex(code, r"[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}")
        with self.assertRaises(konten.KontoFehler):
            konten.einrichten(self.con, "0000-0000-0000", "gob", "Matthias", "geheim123")
        konten.einrichten(self.con, code.lower(), "gob", "Matthias", "geheim123")
        self.assertIsNone(konten.einrichtungscode(self.con))
        with self.assertRaises(konten.KontoFehler):
            konten.einrichten(self.con, code, "abc", "Noch wer", "geheim123")

    def test_sperre(self):
        uhr = [1000.0]
        s = konten.Sperre(uhr=lambda: uhr[0])
        for _ in range(konten.FEHLVERSUCHE - 1):
            self.assertEqual(s.fehlversuch("pc"), 0)
        self.assertEqual(s.fehlversuch("pc"), konten.SPERRE_S)
        self.assertGreater(s.wartezeit("pc"), 0)
        uhr[0] += konten.SPERRE_S + 1
        self.assertEqual(s.wartezeit("pc"), 0)


class Projekte(MitDatenbank):
    def projekt(self, **extra):
        k = self.admin()
        werte = dict(titel="Klimaanlage", klasse="BSMT 22b", start="2026-11-04", ende="2027-03-26", lehrkraefte=[k["id"]],
                     mitglieder=[{"vorname": "Lena", "nachname": "Schmitt"}, {"vorname": "Leon", "nachname": "Sauer"}])
        werte.update(extra)
        return k, projekte.anlegen(self.con, "gob", **werte)

    def test_anlegen_aus_vorlage(self):
        _k, pid = self.projekt()
        d = projekte.details(self.con, pid)
        self.assertEqual([p["name"] for p in d["phasen"]], ["Informieren", "Planen", "Realisieren", "Kontrollieren"])
        self.assertEqual(len(d["phasen"][3]["aufgaben"]), 3)
        self.assertEqual(d["start"], "2026-11-02")   # Montag der Woche
        self.assertEqual(d["schuljahr"], "2026/27")
        self.assertEqual(sorted(m["kuerzel"] for m in d["mitglieder"]), ["LS", "LS2"])
        self.assertEqual(d["verlauf"][0]["art"], "projekt_angelegt")

    def test_pruefungen(self):
        k = self.admin()
        with self.assertRaises(projekte.ProjektFehler):
            projekte.anlegen(self.con, "gob", "", "BSMT", "2026-11-02", "2027-01-01", [k["id"]], [])
        with self.assertRaises(projekte.ProjektFehler):
            projekte.anlegen(self.con, "gob", "X", "BSMT", "2026-11-02", "2026-01-01", [k["id"]], [])
        with self.assertRaises(projekte.ProjektFehler):
            projekte.anlegen(self.con, "gob", "X", "BSMT", "2026-11-02", "2027-01-01", [], [])
        with self.assertRaises(projekte.ProjektFehler):
            projekte.anlegen(self.con, "gob", "X", "BSMT", "2026-11-02", "2027-01-01", [k["id"]], [{"vorname": "Lena"}])

    def test_teamlink_und_archiv(self):
        _k, pid = self.projekt()
        token = projekte.details(self.con, pid)["link_token"]
        sicht = projekte.team_sicht(self.con, token)
        self.assertEqual(sicht["titel"], "Klimaanlage")
        self.assertNotIn("link_token", sicht)
        neu = projekte.link_erneuern(self.con, "gob", pid)
        self.assertIsNone(projekte.team_sicht(self.con, token))
        self.assertIsNotNone(projekte.team_sicht(self.con, neu))
        projekte.archivieren(self.con, "gob", pid, True)
        self.assertIsNone(projekte.team_sicht(self.con, neu))
        self.assertIsNone(projekte.team_sicht(self.con, "kurz"))

    def test_sichtbarkeit_teamteaching(self):
        k, pid = self.projekt()
        with db.transaktion(self.con):
            l = konten.anlegen(self.con, "scu", "Herr Schu", "lehrkraft", "start12345")
        self.assertFalse(projekte.darf(self.con, l, pid))
        self.assertEqual(projekte.liste(self.con, l), [])
        projekte.aendern(self.con, "gob", pid, {"lehrkraefte": [k["id"], l["id"]]})
        self.assertTrue(projekte.darf(self.con, l, pid))
        self.assertEqual(len(projekte.liste(self.con, l)), 1)
        self.assertEqual(projekte.details(self.con, pid)["verlauf"][0]["art"], "lehrkraefte_geaendert")

    def test_mitglieder(self):
        _k, pid = self.projekt()
        mid = projekte.mitglied_anlegen(self.con, "gob", pid, "Mia", "Klein")
        projekte.mitglied_aendern(self.con, "gob", pid, mid, {"aktiv": False})
        sicht = projekte.team_sicht(self.con, projekte.details(self.con, pid)["link_token"])
        self.assertNotIn("Mia", [m["vorname"] for m in sicht["mitglieder"]])


class Webserver(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ordner = tempfile.mkdtemp()
        db.oeffnen(cls.ordner).close()
        cls.srv = server.HTTPServer(("127.0.0.1", 0), server.Handler, os.path.join(cls.ordner, "trackingdrs.sqlite"))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.port = cls.srv.server_address[1]
        cls.cookie = None

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.ordner, ignore_errors=True)

    def anfrage(self, methode, pfad, daten=None, kopf=True, cookie=True):
        verbindung = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        koepfe = {}
        if kopf:
            koepfe["X-TrackingDRS"] = "1"
        if cookie and Webserver.cookie:
            koepfe["Cookie"] = Webserver.cookie
        inhalt = None
        if daten is not None:
            inhalt = json.dumps(daten).encode()
            koepfe["Content-Type"] = "application/json"
        verbindung.request(methode, pfad, body=inhalt, headers=koepfe)
        antwort = verbindung.getresponse()
        roh = antwort.read()
        setze = antwort.getheader("Set-Cookie")
        if setze:
            Webserver.cookie = setze.split(";")[0]
        try:
            text = json.loads(roh)
        except ValueError:
            text = roh
        verbindung.close()
        return antwort, text

    def test_ablauf(self):
        a, d = self.anfrage("GET", "/api/status")
        self.assertFalse(d["eingerichtet"])
        a, _ = self.anfrage("GET", "/")
        self.assertEqual(a.getheader("Location"), "/einrichtung")
        self.assertEqual(a.getheader("Referrer-Policy"), "no-referrer")

        con = db.verbinden(os.path.join(self.ordner, "trackingdrs.sqlite"))
        code = konten.einrichtungscode(con)
        con.close()
        a, _ = self.anfrage("POST", "/api/einrichtung", {"code": code, "kuerzel": "gob", "name": "M. Göbel", "passwort": "geheim123"},
                            kopf=False)
        self.assertEqual(a.status, 403)   # ohne X-TrackingDRS
        a, d = self.anfrage("POST", "/api/einrichtung", {"code": code, "kuerzel": "gob", "name": "M. Göbel", "passwort": "geheim123"})
        self.assertEqual(a.status, 200, d)
        self.assertIn("HttpOnly", a.getheader("Set-Cookie"))

        a, d = self.anfrage("GET", "/api/ich")
        self.assertEqual(d["konto"]["kuerzel"], "gob")
        a, d = self.anfrage("POST", "/api/projekte", {"titel": "Förderband", "klasse": "BSMT 22a", "start": "2026-11-02",
                                                      "ende": "2027-02-01", "mitglieder": [{"vorname": "Ben", "nachname": "Weber"}]})
        self.assertEqual(a.status, 200, d)
        pid, token = d["projekt"]["id"], d["projekt"]["link_token"]
        a, d = self.anfrage("GET", "/api/projekte")
        self.assertEqual([p["titel"] for p in d["projekte"]], ["Förderband"])

        a, d = self.anfrage("GET", "/api/t/" + token, cookie=False)
        self.assertEqual(d["projekt"]["mitglieder"][0]["kuerzel"], "BW")
        a, d = self.anfrage("GET", "/t/" + token, cookie=False)
        self.assertEqual(a.status, 200)
        self.assertIn(b"team.js", d)
        a, d = self.anfrage("GET", "/api/t/" + "x" * 32, cookie=False)
        self.assertEqual(a.status, 404)

        # das Tracking-Sheet bearbeitet nur das Team, die Lehrkraft liest und setzt Meilensteine
        a, d = self.anfrage("GET", "/api/projekte/%d/sheet" % pid)
        self.assertEqual(a.status, 200)
        phase = d["sheet"]["phasen"][0]["id"]
        a, d = self.anfrage("POST", "/api/projekte/%d/sheet" % pid, {"aktion": "aufgabe_neu", "phase_id": phase, "titel": "X"})
        self.assertEqual(a.status, 403)
        a, d = self.anfrage("POST", "/api/projekte/%d/sheet" % pid, {"aktion": "meilenstein_neu", "woche": "2026-11-16",
                                                                   "titel": "Konstruktion fertig"})
        self.assertEqual(a.status, 200, d)
        self.assertEqual(d["sheet"]["meilensteine"][0]["titel"], "Konstruktion fertig")
        a, d = self.anfrage("POST", "/api/t/%s/sheet" % token, {"aktion": "aufgabe_neu", "phase_id": phase, "titel": "X"}, cookie=False)
        self.assertEqual(a.status, 200, d)

        a, d = self.anfrage("POST", "/api/projekte/%d" % pid, {"titel": ""})
        self.assertEqual(a.status, 400)
        self.assertIn("Projekttitel", d["fehler"])

        a, _ = self.anfrage("GET", "/api/projekte", cookie=False)
        self.assertEqual(a.status, 401)
        a, _ = self.anfrage("POST", "/api/abmelden", {})
        a, _ = self.anfrage("GET", "/api/projekte")
        self.assertEqual(a.status, 401)

    def test_statisch_und_unbekannt(self):
        a, d = self.anfrage("GET", "/static/stil.css")
        self.assertEqual(a.status, 200)
        self.assertIn("text/css", a.getheader("Content-Type"))
        a, _ = self.anfrage("GET", "/static/../app/db.py")
        self.assertEqual(a.status, 404)
        a, _ = self.anfrage("GET", "/gibtsnicht")
        self.assertEqual(a.status, 404)


if __name__ == "__main__":
    unittest.main()
