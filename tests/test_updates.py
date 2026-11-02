"""Tests fuer das Update aus dem Lehrerbereich: Anfrage-Dateien, Stand lesen, Sicherung vor dem Update, Skripte."""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from unittest import mock

from app import VERSION, db, updates

DEPLOY = pathlib.Path(__file__).resolve().parent.parent / "deploy"


class Update(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.daten = os.path.join(self.ordner, "daten")
        self.stand_dir = os.path.join(self.ordner, "stand")
        self.einheit = os.path.join(self.ordner, "trackingdrs-update-ausfuehren.path")
        os.makedirs(self.stand_dir)
        self.con = db.oeffnen(self.daten)
        for name, wert in (("STAND_DIR", self.stand_dir), ("EINHEIT", self.einheit)):
            p = mock.patch.object(updates, name, wert)
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def schreiben(self, name, daten):
        with open(os.path.join(self.stand_dir, name), "w", encoding="utf-8") as f:
            json.dump(daten, f)

    def test_ohne_container(self):
        s = updates.stand(self.daten)
        self.assertEqual((s["eingerichtet"], s["version"], s["pruefung"], s["laeuft"]), (False, VERSION, None, False))
        with self.assertRaises(updates.UpdateFehler):
            updates.anfordern(self.daten, "pruefen")
        self.assertIsNone(updates.kurz())

    def test_anfragen_und_stand(self):
        open(self.einheit, "w").close()
        with self.assertRaises(updates.UpdateFehler):
            updates.anfordern(self.daten, "rm -rf")
        updates.anfordern(self.daten, "pruefen")
        self.assertTrue(updates.stand(self.daten)["wartet"]["pruefen"])
        updates.anfordern(self.daten, "ausfuehren")
        with self.assertRaises(updates.UpdateFehler):   # nicht zweimal
            updates.anfordern(self.daten, "ausfuehren")
        os.remove(os.path.join(self.daten, "update", "ausfuehren"))
        self.schreiben("lauf.json", {"beginn": "2026-11-02T10:00:00", "ende": None, "ergebnis": None})
        self.assertTrue(updates.stand(self.daten)["laeuft"])
        with self.assertRaises(updates.UpdateFehler):
            updates.anfordern(self.daten, "ausfuehren")
        self.schreiben("lauf.json", {"beginn": "2026-11-02T10:00:00", "ende": "2026-11-02T10:01:10", "ergebnis": "ok"})
        self.assertFalse(updates.stand(self.daten)["laeuft"])
        # Hinweis fuer Admins nur, wenn die Pruefung zur laufenden Version passt und Neues gefunden hat
        pruefung = {"zeit": "2026-11-02T06:10:00", "fehler": None, "installiert": {"version": VERSION, "stand": "3f4f0be"},
                    "verfuegbar": {"version": "9.9.9", "stand": "abc1234"}, "neu": 2, "aenderungen": []}
        self.schreiben("stand.json", pruefung)
        self.assertEqual(updates.kurz(), {"neu": 2, "version": "9.9.9"})
        self.schreiben("stand.json", dict(pruefung, installiert={"version": "0.0.1", "stand": "x"}))
        self.assertIsNone(updates.kurz())   # Pruefung von vor dem letzten Update
        self.schreiben("stand.json", dict(pruefung, neu=0))
        self.assertIsNone(updates.kurz())
        with open(os.path.join(self.stand_dir, "stand.json"), "w") as f:
            f.write("{kaputt")
        self.assertIsNone(updates.stand(self.daten)["pruefung"])

    def test_sicherung_vor_dem_update(self):
        zeit = {"jetzt": ""}
        with mock.patch.object(db, "jetzt", side_effect=lambda: zeit["jetzt"]):
            for tag in range(1, 8):
                zeit["jetzt"] = "2026-11-%02dT10:00:00" % tag
                pfad = updates.sicherung_ablegen(self.con, self.daten)
        self.assertEqual(os.path.basename(pfad), "vor-update-2026-11-07_10-00-00.zip")
        with zipfile.ZipFile(pfad) as z:
            self.assertIn("trackingdrs.sqlite", z.namelist())
        namen = [s["name"] for s in updates.sicherungen(self.daten)]
        self.assertEqual(len(namen), 5)
        self.assertEqual(namen[-1], "vor-update-2026-11-03_10-00-00.zip")   # die aeltesten sind weg
        self.assertEqual(updates.sicherung_pfad(self.daten, namen[0]), pfad)
        for falsch in ("../trackingdrs.sqlite", "vor-update-../../x.zip", "vor-update-2026.zip"):
            with self.assertRaises(updates.UpdateFehler):
                updates.sicherung_pfad(self.daten, falsch)


@unittest.skipUnless(shutil.which("bash"), "ohne bash")
class Skripte(unittest.TestCase):
    def test_bash_syntax(self):
        for name in ("install.sh", "update.sh", "selbstupdate.sh", "tls.sh", "vpn.sh", "trackingdrs-cli.sh"):
            with self.subTest(name=name):
                r = subprocess.run(["bash", "-n", str(DEPLOY / name)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_einheiten_vollstaendig(self):
        install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
        for einheit in DEPLOY.glob("trackingdrs-update-*"):
            with self.subTest(einheit=einheit.name):
                self.assertIn(einheit.name, install)
        self.assertIn("/var/lib/trackingdrs/update/ausfuehren", (DEPLOY / "trackingdrs-update-ausfuehren.path").read_text(encoding="utf-8"))
