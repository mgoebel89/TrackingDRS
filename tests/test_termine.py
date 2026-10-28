"""Tests fuer Stufe C1: Projektzeiten als Regeln, Ferien, Ausfaelle, angepasste Tage, Buchung mit Buchungsschluss,
Haekchen "erledigt", Warnungen, Version zum Buchungsschluss und Team-Links ueber HTTP."""
import datetime
import http.client
import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from app import db, konten, projekte, server, sheet, termine

DI = 1


class Termine(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        self.uhr("2026-11-02T10:00:00")   # Montag, KW 45
        with db.transaktion(self.con):
            self.gob = konten.anlegen(self.con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
            self.scu = konten.anlegen(self.con, "scu", "Herr Schu", "lehrkraft", "geheim123", vorlaeufig=False)
        leute = [{"vorname": "Lena", "nachname": "Schmitt"}, {"vorname": "Ben", "nachname": "Weber"}]
        self.klima = projekte.anlegen(self.con, "gob", "Klimaanlage", "BSMT 22b", "2026-10-26", "2027-01-04", [self.gob["id"]], leute)
        self.hub = projekte.anlegen(self.con, "gob", "Hubtisch", "bsmt 22b ", "2026-10-26", "2027-01-04", [self.gob["id"]], leute)
        self.fremd = projekte.anlegen(self.con, "scu", "Förderband", "BSMT 22b", "2026-10-26", "2027-01-04", [self.scu["id"]], leute)
        # Projekte "vorher" angelegt, damit Versionen zum Buchungsschluss entstehen duerfen
        self.con.execute("UPDATE projekt SET erstellt = '2026-10-01T08:00:00'")
        self.regel = termine.regel_anlegen(self.con, self.gob, self.regel_daten())

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def uhr(self, zeit):
        """Stellt die Uhr der Anwendung (db.jetzt, davon abgeleitet db.heute)."""
        if not hasattr(self, "zeit"):
            patcher = mock.patch.object(db, "jetzt", side_effect=lambda: self.zeit)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.zeit = zeit

    def regel_daten(self, **d):
        daten = {"klasse": "BSMT 22b", "wochentag": DI, "rhythmus": "ungerade", "von": "08:00", "bis": "11:15",
                 "fenster_von": "08:30", "fenster_bis": "10:00", "laenge": 15, "schluss_tage": 1, "schluss_zeit": "18:00",
                 "gueltig_von": "2026-08-01", "gueltig_bis": "2027-07-31"}
        daten.update(d)
        return daten

    def tage(self, pid):
        p = self.con.execute("SELECT * FROM projekt WHERE id = ?", (pid,)).fetchone()
        return [t["datum"] for t in termine.projekt_tage(self.con, p)]

    def ereignisse(self, pid, art):
        return [json.loads(e["daten"]) for e in self.con.execute("SELECT * FROM ereignis WHERE projekt_id = ? AND art = ?", (pid, art))]

    # --- Projekttage ---

    def test_projekttage_ungerade_kw_ferien_ausfall(self):
        self.assertEqual(self.tage(self.klima), ["2026-11-03", "2026-11-17", "2026-12-01", "2026-12-15", "2026-12-29", "2027-01-05"])
        termine.ferien_anlegen(self.con, self.gob, {"von": "2026-12-21", "bis": "2027-01-02", "name": "Weihnachtsferien"})
        termine.ausfall_anlegen(self.con, self.gob, {"von": "2026-12-01", "grund": "Prüfung", "klasse": "BSMT 22B"})
        termine.tag_anpassen(self.con, self.gob, self.regel, "2026-12-15", {"gestrichen": True, "grund": "Ausflug"})
        self.assertEqual(self.tage(self.klima), ["2026-11-03", "2026-11-17", "2027-01-05"])
        # Ausfall gilt nur fuer die eigenen Regeln: Herr Schu hat keine Regel, sein Projekt hat keine Tage
        self.assertEqual(self.tage(self.fremd), [])
        # die Uebersicht zeigt entfallene Tage mit Grund
        u = termine.uebersicht(self.con, self.gob, "2026-11-30", wochen=5)
        self.assertEqual([(t["datum"], t["entfaellt"]) for t in u["tage"]],
                         [("2026-12-01", "Prüfung"), ("2026-12-15", "Ausflug"), ("2026-12-29", "Weihnachtsferien")])

    def test_tag_anpassen_und_plaetze(self):
        termine.tag_anpassen(self.con, self.gob, self.regel, "2026-11-03", {"fenster_von": "09:00", "fenster_bis": "10:00", "laenge": 20})
        sicht = termine.termin_sicht(self.con, self.klima)
        tag = sicht["wochen"][0]["tage"][0]
        self.assertEqual([p["uhrzeit"] for p in tag["plaetze"]], ["09:00", "09:20", "09:40"])
        with self.assertRaises(projekte.ProjektFehler):   # Montag greift die Regel nicht
            termine.tag_anpassen(self.con, self.gob, self.regel, "2026-11-02", {"gestrichen": True, "grund": "x"})

    def test_regel_pruefungen(self):
        with self.assertRaises(projekte.ProjektFehler):   # gleiches Fenster, jede Woche ueberschneidet ungerade
            termine.regel_anlegen(self.con, self.gob, self.regel_daten(klasse="BSMT 23a", rhythmus="jede", fenster_von="09:30"))
        # gerade Wochen ueberschneiden ungerade nicht
        termine.regel_anlegen(self.con, self.gob, self.regel_daten(klasse="BSMT 23a", rhythmus="gerade"))
        with self.assertRaises(projekte.ProjektFehler):
            termine.regel_anlegen(self.con, self.gob, self.regel_daten(fenster_von="09:00", fenster_bis="09:10", wochentag=3))
        with self.assertRaises(projekte.ProjektFehler):
            termine.regel_anlegen(self.con, self.gob, self.regel_daten(wochentag=3, schluss_tage=0, schluss_zeit="09:00"))
        with self.assertRaises(projekte.ProjektFehler):   # fremde Regel
            termine.regel_aendern(self.con, self.scu, self.regel, {"laenge": 20})

    # --- Buchen ---

    def test_buchen_umbuchen_belegt_schluss(self):
        termine.buchen(self.con, self.klima, "team", "Team", self.regel, "2026-11-03", "08:45")
        with self.assertRaises(projekte.ProjektFehler):   # schon vergeben
            termine.buchen(self.con, self.hub, "team", "Team", self.regel, "2026-11-03", "08:45")
        with self.assertRaises(projekte.ProjektFehler):   # gibt es nicht
            termine.buchen(self.con, self.hub, "team", "Team", self.regel, "2026-11-03", "08:50")
        with self.assertRaises(projekte.ProjektFehler):   # Regel einer anderen Lehrkraft
            termine.buchen(self.con, self.fremd, "team", "Team", self.regel, "2026-11-03", "09:00")
        # umbuchen: ein Termin je Woche, der alte wird frei
        termine.buchen(self.con, self.klima, "team", "Team", self.regel, "2026-11-03", "09:15")
        termine.buchen(self.con, self.hub, "team", "Team", self.regel, "2026-11-03", "08:45")
        sicht = termine.termin_sicht(self.con, self.hub)
        status = {p["uhrzeit"]: p["status"] for p in sicht["wochen"][0]["tage"][0]["plaetze"]}
        self.assertEqual((status["08:45"], status["09:15"], status["08:30"]), ("eigen", "belegt", "frei"))
        self.assertNotIn("team", sicht["wochen"][0]["tage"][0]["plaetze"][3])   # Team sieht nicht, wer
        lk = termine.termin_sicht(self.con, self.hub, lehrkraft=True)
        self.assertEqual(lk["wochen"][0]["tage"][0]["plaetze"][3]["team"], "Klimaanlage")
        self.assertEqual(len(self.ereignisse(self.klima, "termin_gebucht")), 2)
        # nach dem Buchungsschluss (Mo 18:00) darf nur noch die Lehrkraft aendern
        self.uhr("2026-11-02T18:00:00")
        with self.assertRaises(projekte.ProjektFehler):
            termine.buchen(self.con, self.klima, "team", "Team", self.regel, "2026-11-03", "09:30")
        with self.assertRaises(projekte.ProjektFehler):
            termine.stornieren(self.con, self.klima, "team", "Team", "2026-11-02")
        self.assertTrue(termine.termin_sicht(self.con, self.klima)["wochen"][0]["fest"])
        termine.buchen(self.con, self.klima, "lehrkraft", "gob", self.regel, "2026-11-03", "09:30")
        termine.stornieren(self.con, self.hub, "lehrkraft", "gob", "2026-11-02")
        aktiv = self.con.execute("SELECT projekt_id, uhrzeit FROM buchung WHERE aktiv = 1").fetchall()
        self.assertEqual([tuple(z) for z in aktiv], [(self.klima, "09:30")])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM buchung").fetchone()[0], 4)   # nichts geloescht

    def test_aenderungen_heben_buchungen_auf(self):
        termine.buchen(self.con, self.klima, "team", "Team", self.regel, "2026-11-17", "09:45")
        termine.regel_aendern(self.con, self.gob, self.regel, {"fenster_bis": "09:30"})
        self.assertEqual(self.ereignisse(self.klima, "termin_entfallen")[0]["uhrzeit"], "09:45")
        termine.buchen(self.con, self.klima, "team", "Team", self.regel, "2026-11-17", "08:30")
        termine.ferien_anlegen(self.con, self.gob, {"von": "2026-11-16", "bis": "2026-11-20", "name": "Herbstferien"})
        self.assertEqual(self.ereignisse(self.klima, "termin_entfallen")[1]["grund"], "Herbstferien")
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM buchung WHERE aktiv = 1").fetchone()[0], 0)

    # --- Erledigt, Warnungen, Versionen ---

    def aufgabe(self, pid, titel, plan=(), ende=None):
        ph = sheet.lesen(self.con, pid)["phasen"][1]["id"]
        aid = sheet.aendern(self.con, pid, "team", "Team", {"aktion": "aufgabe_neu", "phase_id": ph, "titel": titel})["aufgabe_id"]
        if plan:
            sheet.aendern(self.con, pid, "team", "Team", {"aktion": "plan", "aufgabe_id": aid, "wochen": list(plan), "wert": True})
        if ende:
            sheet.aendern(self.con, pid, "team", "Team", {"aktion": "ende", "aufgabe_id": aid, "woche": ende})
        return aid

    def arten(self, pid):
        return {w["art"]: w["stufe"] for w in termine.warnungen(self.con, pid)}

    def test_warnungen(self):
        aid = self.aufgabe(self.klima, "Lüfter auslegen", plan=["2026-10-26", "2026-11-02"], ende="2026-10-26")
        a = self.arten(self.klima)
        self.assertEqual(a["termin_offen"], "hinweis")
        self.assertEqual(a["ampel_offen"], "hinweis")
        self.assertEqual(a["endtermin"], "warnung")
        self.assertEqual(a["verantwortlich_fehlt"], "hinweis")
        self.uhr("2026-11-02T18:05:00")
        a = self.arten(self.klima)
        self.assertEqual((a["termin_fehlt"], a["nicht_aktualisiert"]), ("warnung", "warnung"))
        sheet.aendern(self.con, self.klima, "team", "Team", {"aktion": "ampel", "aufgabe_id": aid, "woche": "2026-11-02", "ampel": "g"})
        sheet.aendern(self.con, self.klima, "team", "Team", {"aktion": "erledigt", "aufgabe_id": aid})
        termine.buchen(self.con, self.klima, "lehrkraft", "gob", self.regel, "2026-11-03", "08:30")
        a = self.arten(self.klima)
        self.assertNotIn("termin_fehlt", a)
        self.assertNotIn("nicht_aktualisiert", a)
        self.assertNotIn("endtermin", a)
        self.assertTrue(sheet.lesen(self.con, self.klima)["phasen"][1]["aufgaben"][0]["erledigt"])
        self.assertEqual(len(self.ereignisse(self.klima, "erledigt")), 1)
        # Woche ohne Projekttag (KW 46): nur die naechste Projektwoche zaehlt, ihr Schluss ist erst Mo 16.11.
        self.uhr("2026-11-10T09:00:00")
        self.assertEqual(self.arten(self.klima).get("termin_offen"), "hinweis")

    def test_version_zum_buchungsschluss(self):
        termine.buchen(self.con, self.klima, "team", "Team", self.regel, "2026-11-03", "08:30")
        self.assertEqual(termine.faellige_versionen(self.con), 0)
        self.uhr("2026-11-02T18:00:30")
        self.assertEqual(termine.faellige_versionen(self.con), 2)   # Klimaanlage und Hubtisch
        self.assertEqual(termine.faellige_versionen(self.con), 0)   # nur einmal je Woche
        v = self.con.execute("SELECT * FROM version WHERE projekt_id = ?", (self.klima,)).fetchone()
        self.assertEqual((v["art"], v["woche"]), ("buchungsschluss", "2026-11-02"))
        self.assertIn("KW 45", v["name"])
        self.assertEqual(self.ereignisse(self.klima, "version")[0]["versionsart"], "buchungsschluss")
        # Server war zum naechsten Buchungsschluss (Mo 16.11., 18:00) laenger als 2 Tage aus: nichts nachholen
        self.uhr("2026-11-19T19:00:00")
        self.assertEqual(termine.faellige_versionen(self.con), 0)

    def test_projektwochen_im_sheet(self):
        d = sheet.lesen(self.con, self.klima)
        self.assertEqual(d["projektwochen"][:2], ["2026-11-02", "2026-11-16"])
        self.assertIsNone(sheet.lesen(self.con, self.fremd)["projektwochen"])   # ohne Regel: nichts schraffieren


class TeamUeberHTTP(unittest.TestCase):
    """Neben HTTPS bedient der HTTP-Port nur die Team-Seiten; Lehrerpfade werden umgeleitet oder abgelehnt."""

    @classmethod
    def setUpClass(cls):
        cls.ordner = tempfile.mkdtemp()
        con = db.oeffnen(cls.ordner)
        with db.transaktion(con):
            k = konten.anlegen(con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
        pid = projekte.anlegen(con, "gob", "Klimaanlage", "BSMT 22b", "2026-10-26", "2027-01-04", [k["id"]], [])
        cls.token = con.execute("SELECT link_token FROM projekt WHERE id = ?", (pid,)).fetchone()[0]
        con.close()
        cls.srv = server.HTTPServer(("127.0.0.1", 0), server.TeamHandler, os.path.join(cls.ordner, "trackingdrs.sqlite"))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.ordner, ignore_errors=True)

    def anfrage(self, methode, pfad, daten=None):
        v = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        v.request(methode, pfad, body=json.dumps(daten).encode() if daten is not None else None,
                  headers={"X-TrackingDRS": "1", "Content-Type": "application/json", "Host": "trackingdrs.schule"})
        a = v.getresponse()
        roh = a.read()
        v.close()
        return a, roh

    def test_team_ja_lehrer_nein(self):
        a, roh = self.anfrage("GET", "/t/" + self.token)
        self.assertEqual(a.status, 200)
        self.assertIn(b"team.js", roh)
        a, roh = self.anfrage("GET", "/api/t/%s/termine" % self.token)
        self.assertEqual(a.status, 200)
        self.assertEqual(json.loads(roh)["termine"]["wochen"], [])
        self.assertEqual(self.anfrage("GET", "/static/stil.css")[0].status, 200)
        a, _ = self.anfrage("GET", "/lehrer")
        self.assertEqual((a.status, a.getheader("Location")), (301, "https://trackingdrs.schule/lehrer"))
        a, roh = self.anfrage("POST", "/api/anmelden", {"kuerzel": "gob", "passwort": "geheim123"})
        self.assertEqual(a.status, 403)
        self.assertIsNone(a.getheader("Set-Cookie"))
        self.assertEqual(self.anfrage("GET", "/api/projekte")[0].status, 301)


if __name__ == "__main__":
    unittest.main()
