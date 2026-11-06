"""Tests fuer Stufe J4: Hilfe-Knopf je Team, Reihe fuer die betreuenden Lehrkraefte, nur waehrend der Projektzeit."""
import shutil
import tempfile
import unittest
from unittest import mock

from app import db, hilfe, konten, projekte, termine

DI = 1


class Hilfe(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        self.zeit = "2026-11-03T09:00:00"   # Dienstag, KW 45 (ungerade): Projekttag 08:00 bis 11:15
        uhr = mock.patch.object(db, "jetzt", side_effect=lambda: self.zeit)
        uhr.start()
        self.addCleanup(uhr.stop)
        with db.transaktion(self.con):
            self.gob = konten.anlegen(self.con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
            self.scu = konten.anlegen(self.con, "scu", "Herr Schu", "lehrkraft", "geheim123", vorlaeufig=False)
        leute = [{"vorname": "Lena", "nachname": "Schmitt"}, {"vorname": "Ben", "nachname": "Weber"}]
        self.klima = projekte.anlegen(self.con, "gob", "Klimaanlage", "BSMT 22b", "2026-10-26", "2027-01-04", [self.gob["id"]], leute)
        self.hub = projekte.anlegen(self.con, "gob", "Hubtisch", "BSMT 22b", "2026-10-26", "2027-01-04", [self.gob["id"]], leute)
        self.fremd = projekte.anlegen(self.con, "scu", "Förderband", "BSMT 22b", "2026-10-26", "2027-01-04", [self.scu["id"]], leute)
        for konto in (self.gob, self.scu):
            termine.regel_anlegen(self.con, konto, {"klasse": "BSMT 22b", "wochentag": DI, "rhythmus": "jede", "von": "08:00", "bis": "11:15",
                                                    "fenster_von": "08:30", "fenster_bis": "10:00", "laenge": 15, "schluss_tage": 1,
                                                    "schluss_zeit": "18:00", "gueltig_von": "2026-08-01", "gueltig_bis": "2027-07-31"})

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def test_reihe_nummern_und_erledigt(self):
        hilfe.team_aendern(self.con, self.klima, {"aktion": "rufen", "wer": "Lena Schmitt"})
        with self.assertRaises(projekte.ProjektFehler):   # einmal je Team
            hilfe.team_aendern(self.con, self.klima, {"aktion": "rufen"})
        self.zeit = "2026-11-03T09:02:00"
        stand = hilfe.team_aendern(self.con, self.hub, {"aktion": "rufen"})
        self.assertEqual(stand["meldung"]["nr"], 2)
        hilfe.team_aendern(self.con, self.fremd, {"aktion": "rufen"})
        reihe = hilfe.reihe(self.con, self.gob)
        self.assertEqual([(m["nr"], m["projekt"], m["wer"]) for m in reihe], [(1, "Klimaanlage", "Lena Schmitt"), (2, "Hubtisch", "")])
        self.assertEqual([m["projekt"] for m in hilfe.reihe(self.con, self.scu)], ["Förderband"])   # nur betreute Projekte
        self.assertEqual(hilfe.team_stand(self.con, self.fremd)["meldung"]["nr"], 1)   # andere Lehrkraft, eigene Reihe
        # "Ich komme": das Team sieht den Namen, nochmal tippen nimmt es zurueck
        hilfe.lehrkraft_aendern(self.con, self.gob, reihe[0]["id"], {"aktion": "kommen"})
        self.assertEqual(hilfe.team_stand(self.con, self.klima)["meldung"]["kommt"], "Matthias Göbel")
        self.assertTrue(hilfe.reihe(self.con, self.gob)[0]["kommt_ich"])
        with self.assertRaises(projekte.ProjektFehler):   # fremde Lehrkraft
            hilfe.lehrkraft_aendern(self.con, self.scu, reihe[0]["id"], {"aktion": "erledigt"})
        hilfe.lehrkraft_aendern(self.con, self.gob, reihe[0]["id"], {"aktion": "erledigt"})
        self.assertIsNone(hilfe.team_stand(self.con, self.klima)["meldung"])
        self.assertEqual(hilfe.team_stand(self.con, self.hub)["meldung"]["nr"], 1)   # rueckt auf
        # zurueckziehen
        hilfe.team_aendern(self.con, self.hub, {"aktion": "zurueckziehen"})
        self.assertEqual(hilfe.reihe(self.con, self.gob), [])
        arten = [z[0] for z in self.con.execute("SELECT art FROM ereignis WHERE art LIKE 'hilfe%' ORDER BY id")]
        self.assertEqual(arten, ["hilfe_gerufen", "hilfe_gerufen", "hilfe_gerufen", "hilfe_erledigt", "hilfe_zurueck"])

    def test_nur_in_der_projektzeit(self):
        self.zeit = "2026-11-03T12:00:00"   # nach der Projektzeit
        self.assertIsNone(hilfe.team_stand(self.con, self.klima)["projektzeit"])
        with self.assertRaises(projekte.ProjektFehler):
            hilfe.team_aendern(self.con, self.klima, {"aktion": "rufen"})
        self.zeit = "2026-11-04T09:00:00"   # Mittwoch: kein Projekttag
        with self.assertRaises(projekte.ProjektFehler):
            hilfe.team_aendern(self.con, self.klima, {"aktion": "rufen"})

    def test_verfaellt_am_naechsten_tag(self):
        hilfe.team_aendern(self.con, self.klima, {"aktion": "rufen"})
        self.zeit = "2026-11-10T09:00:00"   # naechster Dienstag
        self.assertIsNone(hilfe.team_stand(self.con, self.klima)["meldung"])
        self.assertEqual(hilfe.reihe(self.con, self.gob), [])
        hilfe.team_aendern(self.con, self.klima, {"aktion": "rufen"})   # neuer Tag, neue Meldung
        self.assertEqual(len(hilfe.reihe(self.con, self.gob)), 1)


if __name__ == "__main__":
    unittest.main()
