"""Tests fuer Stufe J6: Oberpunkte (Phasen) je Projekt umbenennen, anlegen, umsortieren, entfernen, Standard."""
import shutil
import tempfile
import unittest

from app import db, konten, projekte, sheet

STANDARD = ["Informieren", "Planen", "Realisieren", "Kontrollieren"]   # app/vorlagen/standard.json


class Phasen(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        with db.transaktion(self.con):
            self.gob = konten.anlegen(self.con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
        self.pid = projekte.anlegen(self.con, "gob", "Klimaanlage", "BSMT 22b", "2026-10-26", "2027-01-04", [self.gob["id"]], [])

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def namen(self):
        return [p["name"] for p in projekte.phasen_sicht(self.con, self.pid)["phasen"]]

    def ph(self, name):
        return next(p for p in projekte.phasen_sicht(self.con, self.pid)["phasen"] if p["name"] == name)

    def aendern(self, **d):
        return projekte.phasen_aendern(self.con, "gob", self.pid, d)

    def test_standard_ist_die_vollstaendige_handlung(self):
        s = projekte.phasen_sicht(self.con, self.pid)
        self.assertEqual(s["standard"], STANDARD)
        self.assertEqual(self.namen(), STANDARD)
        self.assertTrue(s["ist_standard"])

    def test_aendern_und_wiederherstellen(self):
        # eine Taetigkeit des Teams unter "Bewerten"
        bewerten = self.ph("Realisieren")
        sheet.aendern(self.con, self.pid, "team", "Team", {"aktion": "aufgabe_neu", "phase_id": bewerten["id"], "titel": "Präsentation"})
        n_bewerten = self.ph("Realisieren")["alle"]
        self.assertFalse(self.aendern(aktion="umbenennen", phase_id=self.ph("Planen")["id"], name="Konzept wählen")["ist_standard"])
        self.aendern(aktion="neu", name="Dokumentieren")
        self.aendern(aktion="verschieben", phase_id=self.ph("Dokumentieren")["id"], richtung=-1)
        self.assertEqual(self.namen()[-2:], ["Dokumentieren", "Kontrollieren"])
        with self.assertRaises(projekte.ProjektFehler):   # mit Taetigkeiten nur mit Ziel
            self.aendern(aktion="entfernen", phase_id=bewerten["id"])
        self.aendern(aktion="entfernen", phase_id=bewerten["id"], ziel_id=self.ph("Kontrollieren")["id"])
        self.assertNotIn("Realisieren", self.namen())
        titel = [a["titel"] for ph in sheet.lesen(self.con, self.pid)["phasen"] if ph["name"] == "Kontrollieren" for a in ph["aufgaben"]]
        self.assertIn("Präsentation", titel)
        arten = [z[0] for z in self.con.execute("SELECT art FROM ereignis WHERE art LIKE 'phase%' ORDER BY id")]
        self.assertEqual(arten, ["phase_umbenannt", "phase_neu", "phase_verschoben", "phase_entfernt"])
        # Standard wiederherstellen: alle Taetigkeiten bleiben erhalten
        vorher = self.con.execute("SELECT COUNT(*) FROM aufgabe WHERE projekt_id = ?", (self.pid,)).fetchone()[0]
        s = self.aendern(aktion="standard")
        self.assertTrue(s["ist_standard"])
        self.assertEqual(self.namen(), STANDARD)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM aufgabe WHERE projekt_id = ?", (self.pid,)).fetchone()[0], vorher)
        self.assertGreaterEqual(n_bewerten, 1)

    def test_grenzen(self):
        with self.assertRaises(projekte.ProjektFehler):
            self.aendern(aktion="umbenennen", phase_id=self.ph("Planen")["id"], name="  ")
        for name in STANDARD[1:]:
            ph = self.ph(name)
            ziel = self.ph("Informieren")["id"]
            self.aendern(aktion="entfernen", phase_id=ph["id"], ziel_id=ziel if ph["alle"] else None)
        with self.assertRaises(projekte.ProjektFehler):   # mindestens einer bleibt
            self.aendern(aktion="entfernen", phase_id=self.ph("Informieren")["id"])


if __name__ == "__main__":
    unittest.main()
