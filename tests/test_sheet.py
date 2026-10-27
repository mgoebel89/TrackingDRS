"""Tests fuer Stufe B: Tracking-Sheet (Plan, Endtermin, Ampel mit Problem, Verantwortliche, Meilensteine, Versionen)
und das Schul-Logo."""
import datetime
import os
import shutil
import tempfile
import unittest
from unittest import mock

from app import db, einstellungen, konten, projekte, sheet


class Sheet(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        with db.transaktion(self.con):
            k = konten.anlegen(self.con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
        # Projekt KW 44/2026 bis KW 2/2027, "heute" ist Mittwoch der KW 45
        self.pid = projekte.anlegen(self.con, "gob", "Klimaanlage", "BSMT 22b", "2026-10-26", "2027-01-04", [k["id"]],
                                    [{"vorname": "Lena", "nachname": "Schmitt"}, {"vorname": "Ben", "nachname": "Weber"}])
        heute = mock.patch.object(db, "heute", return_value=datetime.date(2026, 11, 4))
        heute.start()
        self.addCleanup(heute.stop)
        d = sheet.lesen(self.con, self.pid)
        self.planen_id = d["phasen"][1]["id"]
        self.lena, self.ben = sorted(d["mitglieder"], key=lambda m: m["vorname"], reverse=True)

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def team(self, **d):
        return sheet.aendern(self.con, self.pid, "team", "Team", d)

    def aufgabe(self, titel="Lüfter auslegen"):
        return self.team(aktion="aufgabe_neu", phase_id=self.planen_id, titel=titel)["aufgabe_id"]

    def finde(self, aid):
        for ph in sheet.lesen(self.con, self.pid)["phasen"]:
            for a in ph["aufgaben"]:
                if a["id"] == aid:
                    return a

    def test_wochen_und_jetzt(self):
        d = sheet.lesen(self.con, self.pid)
        self.assertEqual(d["wochen"][0], "2026-10-26")
        self.assertEqual(d["wochen"][-1], "2027-01-04")
        self.assertEqual(len(d["wochen"]), 11)
        self.assertEqual(d["jetzt"], "2026-11-02")

    def test_plan_ende_und_ursprung(self):
        aid = self.aufgabe()
        self.team(aktion="plan", aufgabe_id=aid, wochen=["2026-11-02", "2026-11-09"], wert=True)
        self.team(aktion="ende", aufgabe_id=aid, woche="2026-11-09")
        self.team(aktion="ende", aufgabe_id=aid, woche="2026-11-23")
        a = self.finde(aid)
        self.assertEqual(a["plan"], ["2026-11-02", "2026-11-09"])
        self.assertEqual((a["ende"], a["ende_ursprung"]), ("2026-11-23", "2026-11-09"))
        self.team(aktion="plan", aufgabe_id=aid, wochen=["2026-11-02"], wert=False)
        self.assertEqual(self.finde(aid)["plan"], ["2026-11-09"])
        with self.assertRaises(projekte.ProjektFehler):
            self.team(aktion="plan", aufgabe_id=aid, wochen=["2027-05-03"], wert=True)

    def test_ampel_nur_bis_heute_und_problem_pflicht(self):
        aid = self.aufgabe()
        self.team(aktion="ampel", aufgabe_id=aid, woche="2026-11-02", ampel="g")
        with self.assertRaises(projekte.ProjektFehler):
            self.team(aktion="ampel", aufgabe_id=aid, woche="2026-11-09", ampel="g")   # Zukunft
        with self.assertRaises(projekte.ProjektFehler):
            self.team(aktion="ampel", aufgabe_id=aid, woche="2026-11-02", ampel="y", problem="Zu laut")
        self.team(aktion="ampel", aufgabe_id=aid, woche="2026-11-02", ampel="y", problem="Zu laut",
                  massnahme="Drehzahl senken", verantwortlich_id=self.ben["id"])
        a = self.finde(aid)
        self.assertEqual(a["ampel"], {"2026-11-02": "y"})
        self.assertEqual(a["probleme"][0]["massnahme"], "Drehzahl senken")
        self.team(aktion="ampel", aufgabe_id=aid, woche="2026-11-02", ampel=None)
        a = self.finde(aid)
        self.assertEqual(a["ampel"], {})
        self.assertEqual(len(a["probleme"]), 1)   # das Problem bleibt als Verlauf

    def test_gesamtstatus_daten(self):
        a1, a2 = self.aufgabe("A"), self.aufgabe("B")
        self.team(aktion="ampel", aufgabe_id=a1, woche="2026-11-02", ampel="g")
        self.team(aktion="ampel", aufgabe_id=a2, woche="2026-11-02", ampel="r", problem="P", massnahme="M",
                  verantwortlich_id=self.lena["id"])
        ampeln = [a["ampel"].get("2026-11-02") for ph in sheet.lesen(self.con, self.pid)["phasen"] for a in ph["aufgaben"]]
        self.assertIn("r", ampeln)

    def test_verantwortlich_genau_einer(self):
        aid = self.aufgabe()
        self.team(aktion="verantwortlich", aufgabe_id=aid, mitglied_id=self.lena["id"])
        self.team(aktion="verantwortlich", aufgabe_id=aid, mitglied_id=self.ben["id"])
        self.assertEqual(self.finde(aid)["verantwortlich_id"], self.ben["id"])
        with self.assertRaises(projekte.ProjektFehler):
            self.team(aktion="verantwortlich", aufgabe_id=aid, mitglied_id=None)
        projekte.mitglied_aendern(self.con, "gob", self.pid, self.lena["id"], {"aktiv": False})
        with self.assertRaises(projekte.ProjektFehler):
            self.team(aktion="verantwortlich", aufgabe_id=aid, mitglied_id=self.lena["id"])

    def test_verwerfen_sperrt_und_vorgaben_nur_lehrkraft(self):
        aid = self.aufgabe()
        self.team(aktion="verwerfen", aufgabe_id=aid, verworfen=True)
        with self.assertRaises(projekte.ProjektFehler):
            self.team(aktion="plan", aufgabe_id=aid, wochen=["2026-11-02"], wert=True)
        self.team(aktion="verwerfen", aufgabe_id=aid, verworfen=False)
        vorgabe = sheet.lesen(self.con, self.pid)["phasen"][3]["aufgaben"][0]["id"]
        with self.assertRaises(projekte.ProjektFehler):
            self.team(aktion="verwerfen", aufgabe_id=vorgabe, verworfen=True)
        with self.assertRaises(projekte.ProjektFehler):
            self.team(aktion="titel", aufgabe_id=vorgabe, titel="weg")
        sheet.aendern(self.con, self.pid, "lehrkraft", "gob", {"aktion": "titel", "aufgabe_id": vorgabe, "titel": "Doku da?"})
        self.assertEqual(self.finde(vorgabe)["titel"], "Doku da?")

    def test_reihenfolge(self):
        a, b = self.aufgabe("A"), self.aufgabe("B")
        self.team(aktion="verschieben", aufgabe_id=b, richtung=-1)
        titel = [x["titel"] for x in sheet.lesen(self.con, self.pid)["phasen"][1]["aufgaben"]]
        self.assertEqual(titel, ["B", "A"])

    def test_meilensteine(self):
        self.team(aktion="meilenstein_neu", woche="2026-11-16", titel="Konstruktion fertig")
        m = sheet.lesen(self.con, self.pid)["meilensteine"][0]
        sheet.aendern(self.con, self.pid, "lehrkraft", "gob", {"aktion": "meilenstein_aendern", "meilenstein_id": m["id"],
                                                               "woche": "2026-11-23"})
        self.team(aktion="meilenstein_verwerfen", meilenstein_id=m["id"], verworfen=True)
        m = sheet.lesen(self.con, self.pid)["meilensteine"][0]
        self.assertEqual((m["woche"], m["verworfen"]), ("2026-11-23", True))

    def test_versionen_und_basisplan(self):
        aid = self.aufgabe()
        self.team(aktion="plan", aufgabe_id=aid, wochen=["2026-11-02"], wert=True)
        v1 = sheet.basisplan_setzen(self.con, self.pid, "gob")
        self.team(aktion="plan", aufgabe_id=aid, wochen=["2026-11-09"], wert=True)
        v2 = sheet.basisplan_setzen(self.con, self.pid, "gob")
        alt = sheet.version_lesen(self.con, self.pid, v1)["daten"]["aufgaben"][str(aid)]
        self.assertEqual(alt["plan"], ["2026-11-02"])
        versionen = {v["id"]: v for v in sheet.lesen(self.con, self.pid)["versionen"]}
        self.assertFalse(versionen[v1]["aktiv"])
        self.assertTrue(versionen[v2]["aktiv"])

    def test_stand_und_verlauf_und_archiv(self):
        s0 = sheet.stand(self.con, self.pid)
        aid = self.aufgabe()
        self.assertGreater(sheet.stand(self.con, self.pid), s0)
        self.team(aktion="ende", aufgabe_id=aid, woche="2026-11-09")
        arten = [e["art"] for e in sheet.aufgabe_verlauf(self.con, self.pid, aid)]
        self.assertEqual(arten, ["ende", "aufgabe_neu"])
        projekte.archivieren(self.con, "gob", self.pid, True)
        with self.assertRaises(projekte.ProjektFehler):
            self.team(aktion="ende", aufgabe_id=aid, woche="2026-11-16")


class Logo(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def test_svg_und_png(self):
        einstellungen.logo_speichern(self.con, self.ordner, b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>')
        pfad, typ = einstellungen.logo_pfad(self.con, self.ordner)
        self.assertEqual(typ, "image/svg+xml")
        einstellungen.logo_speichern(self.con, self.ordner, b"\x89PNG\r\n\x1a\n" + b"0" * 20)
        pfad, typ = einstellungen.logo_pfad(self.con, self.ordner)
        self.assertEqual(typ, "image/png")
        self.assertFalse(os.path.exists(os.path.join(self.ordner, "logo.svg")))
        einstellungen.logo_entfernen(self.con, self.ordner)
        self.assertEqual(einstellungen.logo_pfad(self.con, self.ordner), (None, None))

    def test_gefaehrliches_svg_und_fremde_datei(self):
        with self.assertRaises(einstellungen.EinstellungFehler):
            einstellungen.logo_speichern(self.con, self.ordner, b'<svg><script>alert(1)</script></svg>')
        with self.assertRaises(einstellungen.EinstellungFehler):
            einstellungen.logo_speichern(self.con, self.ordner, b'<svg onload="x()"></svg>')
        with self.assertRaises(einstellungen.EinstellungFehler):
            einstellungen.logo_speichern(self.con, self.ordner, b"GIF89a....")


if __name__ == "__main__":
    unittest.main()
