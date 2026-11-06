"""Tests fuer Stufe J5: Lehrernotizen als gemeinsamer Zeitstrahl."""
import shutil
import tempfile
import unittest
from unittest import mock

from app import besprechung, db, konten, notizen, projekte


class Notizen(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        self.zeit = "2026-11-06T09:00:00"
        uhr = mock.patch.object(db, "jetzt", side_effect=lambda: self.zeit)
        uhr.start()
        self.addCleanup(uhr.stop)
        with db.transaktion(self.con):
            self.gob = konten.anlegen(self.con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
            self.rot = konten.anlegen(self.con, "rot", "Anna Roth", "lehrkraft", "geheim123", vorlaeufig=False)
        self.pid = projekte.anlegen(self.con, "gob", "Klimaanlage", "BSMT 22b", "2026-10-26", "2027-01-04", [self.gob["id"]], [])

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def test_zeitstrahl_dringend_und_rechte(self):
        a = notizen.anlegen(self.con, self.rot, {"ueberschrift": "Lüfter erst nach Freigabe bestellen", "text": "Schaltung fehlt noch.",
                                                 "dringend": True, "projekt_id": self.pid})
        self.zeit = "2026-11-06T09:30:00"
        notizen.anlegen(self.con, self.gob, {"ueberschrift": "Raum 212 am Do belegt"})
        with self.assertRaises(projekte.ProjektFehler):
            notizen.anlegen(self.con, self.gob, {"ueberschrift": "  "})
        l = notizen.liste(self.con, self.gob)
        self.assertEqual([n["ueberschrift"] for n in l["notizen"]], ["Raum 212 am Do belegt", "Lüfter erst nach Freigabe bestellen"])
        self.assertEqual((l["notizen"][1]["wer"], l["notizen"][1]["projekt"]), ("Anna Roth", "Klimaanlage"))
        # dringend und noch nicht aufgeklappt: zaehlt fuer gob, nicht fuer die Verfasserin
        self.assertEqual(notizen.zaehler(self.con, self.gob)["dringend_ungelesen"], 1)
        self.assertEqual(notizen.zaehler(self.con, self.rot)["dringend_ungelesen"], 0)
        notizen.aendern(self.con, self.gob, a, {"aktion": "gelesen"})
        self.assertEqual(notizen.zaehler(self.con, self.gob)["dringend_ungelesen"], 0)
        # aendern und verwerfen nur die Verfasserin
        with self.assertRaises(projekte.ProjektFehler):
            notizen.aendern(self.con, self.gob, a, {"aktion": "verwerfen"})
        notizen.aendern(self.con, self.rot, a, {"aktion": "aendern", "ueberschrift": "Lüfter: Freigabe da", "text": "", "dringend": False})
        n = [x for x in notizen.liste(self.con, self.gob)["notizen"] if x["id"] == a][0]
        self.assertEqual((n["ueberschrift"], n["dringend"], n["projekt_id"]), ("Lüfter: Freigabe da", False, None))
        self.assertIsNotNone(n["geaendert"])
        notizen.aendern(self.con, self.rot, a, {"aktion": "verwerfen"})
        self.assertNotIn(a, [x["id"] for x in notizen.liste(self.con, self.gob)["notizen"]])

    def test_besprechungsnotizen_im_zeitstrahl(self):
        besprechung.aendern(self.con, self.pid, "lehrkraft", "gob", {"aktion": "notizen", "text": "Team wirkt unsicher."})
        l = notizen.liste(self.con, self.rot)["notizen"]
        self.assertEqual(len(l), 1)
        self.assertEqual(l[0]["art"], "besprechung")
        self.assertTrue(l[0]["ueberschrift"].startswith("Notizen zur Besprechung Klimaanlage, KW "))
        self.assertEqual(notizen.zaehler(self.con, self.rot)["dringend_ungelesen"], 0)

    def test_alte_notizen_werden_uebernommen(self):
        ordner = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, ordner, True)
        with mock.patch.object(db, "MIGRATIONEN", db.MIGRATIONEN[:13]):
            con = db.oeffnen(ordner)
        with db.transaktion(con):
            konten.anlegen(con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
        pid = projekte.anlegen(con, "gob", "Hubtisch", "BSMT 22b", "2026-10-26", "2027-01-04", [1], [])
        with db.transaktion(con):
            con.execute("INSERT INTO notiz (projekt_id, text, erstellt, wer) VALUES (?, ?, '2026-11-01T10:00:00', 'gob')",
                        (pid, "Gespräch mit Lena\nSie übernimmt die Steuerung."))
            con.execute("INSERT INTO notiz (projekt_id, text, erstellt, wer, verworfen) VALUES (?, 'weg', '2026-11-01T11:00:00', 'gob', 1)", (pid,))
        con.close()
        con = db.oeffnen(ordner)
        z = con.execute("SELECT ueberschrift, projekt_id, lehrkraft_id, verworfen FROM lehrernotiz ORDER BY id").fetchall()
        self.assertEqual([tuple(x) for x in z][1], ("weg", pid, 1, 1))
        self.assertEqual(z[0][0], "Gespräch mit Lena")
        con.close()


if __name__ == "__main__":
    unittest.main()
