"""Tests fuer Stufe D2: Besprechungstafel (Zonen, Post-its, Striche, Umwandeln in Ergebnisse, Fotos, Einfrieren)."""
import base64
import os
import shutil
import tempfile
import unittest
from unittest import mock

from app import besprechung, db, konten, projekte, sheet, tafel, termine

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200


class Tafel(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        self.zeit = "2026-11-02T10:00:00"
        uhr = mock.patch.object(db, "jetzt", side_effect=lambda: self.zeit)
        uhr.start()
        self.addCleanup(uhr.stop)
        with db.transaktion(self.con):
            self.gob = konten.anlegen(self.con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
        leute = [{"vorname": "Lena", "nachname": "Schmitt"}]
        self.pid = projekte.anlegen(self.con, "gob", "Klimaanlage", "BSMT 22b", "2026-10-26", "2027-01-04", [self.gob["id"]], leute)
        self.anderes = projekte.anlegen(self.con, "gob", "Hubtisch", "BSMT 22b", "2026-10-26", "2027-01-04", [self.gob["id"]], leute)
        self.con.execute("UPDATE projekt SET erstellt = '2026-10-01T08:00:00'")
        regel = termine.regel_anlegen(self.con, self.gob, {
            "klasse": "BSMT 22b", "wochentag": 1, "rhythmus": "jede", "von": "08:00", "bis": "11:15", "fenster_von": "08:30",
            "fenster_bis": "10:00", "laenge": 15, "schluss_tage": 1, "schluss_zeit": "18:00",
            "gueltig_von": "2026-08-01", "gueltig_bis": "2027-07-31"})
        termine.buchen(self.con, self.pid, "team", "Team", regel, "2026-11-03", "08:45")
        self.woche = "2026-11-02"

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def team(self, **d):
        return besprechung.aendern(self.con, self.pid, "team", "Team", d)

    def board(self, **d):
        return tafel.aendern(self.con, self.pid, "gob", dict(d, woche=self.woche))

    def zettel(self):
        return {z["key"]: z for z in tafel.lesen(self.con, self.pid)["postits"]}

    def test_zonen_der_zusammenfassung(self):
        # Auftrag aus einer frueheren Besprechung, Problem im Raster, Frage und Idee des Teams
        with db.transaktion(self.con):
            self.con.execute("INSERT INTO eintrag (projekt_id, art, text, frist, erstellt, wer_art, wer) "
                             "VALUES (?, 'auftrag', 'Datenblatt suchen', '2026-10-30', '2026-10-27T09:00:00', 'lehrkraft', 'gob')", (self.pid,))
        ph = sheet.lesen(self.con, self.pid)["phasen"][1]["id"]
        lena = sheet.lesen(self.con, self.pid)["mitglieder"][0]["id"]
        aid = sheet.aendern(self.con, self.pid, "team", "Team", {"aktion": "aufgabe_neu", "phase_id": ph, "titel": "Lüfter"})["aufgabe_id"]
        sheet.aendern(self.con, self.pid, "team", "Team", {"aktion": "ampel", "aufgabe_id": aid, "woche": self.woche, "ampel": "y",
                                                           "problem": "zu laut", "massnahme": "anderen suchen", "verantwortlich_id": lena})
        self.team(aktion="eintrag_neu", art="frage", text="24 V?")
        self.team(aktion="eintrag_neu", art="idee", text="2 Lüfter parallel")
        z = list(self.zettel().values())
        zone = {x["text"]: x["zone"] for x in z}
        self.assertEqual(zone["Datenblatt suchen"], "seit")
        self.assertEqual(zone["zu laut"], "seit")
        self.assertEqual(zone["24 V?"], "seit")
        self.assertEqual(zone["2 Lüfter parallel"], "ideen")   # in dieser Besprechung entstanden
        self.assertIn("aenderung", [x["art"] for x in z])
        self.assertTrue([x for x in z if x["text"] == "Datenblatt suchen"][0]["ueberfaellig"])

    def test_striche_und_positionen(self):
        sid = self.board(aktion="strich", farbe="#D4005E", breite=6, punkte=[[10, 10, .5], [200, 5000, .9], [300, 40]])["strich_id"]
        self.board(aktion="strich", punkte=[[1, 1], [2, 2]], farbe="lila")
        t = tafel.lesen(self.con, self.pid)
        self.assertEqual(t["striche"][0]["punkte"][1], [200, 900, 0.9])   # auf die Tafel begrenzt
        self.assertEqual(t["striche"][1]["farbe"], "#1d2433")             # unbekannte Farbe -> Standard
        self.board(aktion="strich_weg", ids=[sid])
        self.assertEqual([s["id"] for s in tafel.lesen(self.con, self.pid)["striche"]], [2])
        self.board(aktion="position", key="pabc", x=500, y=300)
        self.assertEqual(tafel.lesen(self.con, self.pid)["positionen"], {"pabc": [500, 300]})

    def test_ablegen_wird_zum_ergebnis(self):
        frage = self.team(aktion="eintrag_neu", art="frage", text="Lüfter bestellen?")["eintrag_id"]
        with self.assertRaises(projekte.ProjektFehler):   # Auftrag ohne Frist
            self.board(aktion="ablegen", key="e%d" % frage, zone="auftraege", x=1200, y=400)
        self.board(aktion="ablegen", key="e%d" % frage, zone="auftraege", x=1200, y=400, frist="2026-11-10")
        z = self.zettel()["e%d" % frage]
        self.assertEqual((z["art"], z["zone"], z["frist"]), ("auftrag", "auftraege", "2026-11-10"))
        self.assertEqual(tafel.lesen(self.con, self.pid)["positionen"]["e%d" % frage], [1200, 400])
        # zurueck in die Mitte: wieder eine Idee
        self.board(aktion="ablegen", key="e%d" % frage, zone="ideen", x=700, y=200)
        self.assertEqual(self.zettel()["e%d" % frage]["art"], "idee")
        # neues Post-it direkt als Absprache, Problem aus der Zusammenfassung als Auftrag
        neu = self.board(aktion="postit", zone="absprachen", text="24 V ist frei", x=1100, y=100)["key"]
        self.assertEqual(self.zettel()[neu]["art"], "absprache")
        self.board(aktion="ablegen", key="pxyz", zone="auftraege", text="Alternative suchen", frist="2026-11-10", x=1300, y=450)
        self.assertIn("Alternative suchen", [z["text"] for z in self.zettel().values() if z["zone"] == "auftraege"])
        # Meilenstein: steht im Sheet, die Idee ist damit verworfen
        self.board(aktion="ablegen", key="e%d" % frage, zone="meilensteine", meilenstein_woche="2026-11-23", x=1200, y=700)
        self.assertIn("Lüfter bestellen?", [m["titel"] for m in sheet.lesen(self.con, self.pid)["meilensteine"]])
        self.assertNotIn("e%d" % frage, self.zettel())
        self.assertEqual(len([e for e in besprechung.lesen(self.con, self.pid, True)["ergebnis"]]), 3)

    def test_fotos_vom_team(self):
        tafel.team_senden(self.con, self.pid, self.ordner, {"bild": base64.b64encode(JPEG).decode(), "text": "Gehäuse"})
        z = [x for x in self.zettel().values() if x.get("bild")][0]
        self.assertEqual((z["text"], z["zone"]), ("Gehäuse", "ideen"))
        pfad, typ = tafel.bild_pfad(self.con, self.ordner, self.pid, z["bild"])
        self.assertTrue(os.path.exists(pfad))
        self.assertEqual(typ, "image/jpeg")
        self.assertEqual(tafel.bild_pfad(self.con, self.ordner, self.anderes, z["bild"]), (None, None))   # fremdes Projekt
        self.assertEqual(tafel.bild_pfad(self.con, self.ordner, self.pid, "../../etc/passwd"), (None, None))
        for falsch in ("kein base64!", base64.b64encode(b"<svg onload=alert(1)>").decode()):
            with self.assertRaises(projekte.ProjektFehler):
                tafel.team_senden(self.con, self.pid, self.ordner, {"bild": falsch})

    def test_einfrieren_beim_abschliessen(self):
        self.board(aktion="strich", punkte=[[10, 10], [20, 20]])
        self.board(aktion="postit", zone="ideen", text="Skizze Gehäuse", x=600, y=300)
        b = besprechung._zeile(self.con, self.pid, self.woche)
        besprechung.aendern(self.con, self.pid, "lehrkraft", "gob", {"aktion": "abschliessen", "woche": self.woche})
        alt = tafel.eingefroren(self.con, self.pid, b["id"])
        self.assertEqual(len(alt["striche"]), 1)
        self.assertIn("Skizze Gehäuse", [z["text"] for z in alt["postits"]])
        self.assertTrue(besprechung.lesen(self.con, self.pid)["protokolle"][0]["tafel"])
        with self.assertRaises(projekte.ProjektFehler):
            self.board(aktion="strich", punkte=[[1, 1], [2, 2]])
        with self.assertRaises(projekte.ProjektFehler):
            tafel.eingefroren(self.con, self.anderes, b["id"])

    def test_anwesenheit(self):
        tafel.melden(self.pid, "tafel")
        tafel.melden(self.pid, "g-1")
        tafel.melden(self.pid, "g-2")
        self.assertEqual(tafel.anwesend(self.pid), {"tafel": True, "geraete": 2})
        self.assertEqual(tafel.anwesend(self.anderes), {"tafel": False, "geraete": 0})


if __name__ == "__main__":
    unittest.main()
