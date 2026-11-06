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

    def test_textmarker_pfeile_sticker(self):
        m = self.board(aktion="strich", marker=True, farbe="#f5c400", punkte=[[10, 10], [200, 10]])
        s = [x for x in tafel.lesen(self.con, self.pid)["striche"] if x["id"] == m["strich_id"]][0]
        self.assertTrue(s["marker"])
        self.assertEqual((s["farbe"], s["breite"]), ("#f5c400", 22))
        self.assertEqual(self.board(aktion="strich", farbe="#f5c400", punkte=[[1, 1], [2, 2]]) and
                         tafel.lesen(self.con, self.pid)["striche"][-1]["farbe"], "#1d2433")   # Stift: nur Stiftfarben
        k = self.board(aktion="postit", zone="ideen", text="2 Lüfter parallel?", x=600, y=300)["key"]
        p = self.board(aktion="pfeil", a={"key": k, "rx": 0.5, "ry": 1.2}, b={"x": 900, "y": 2000})["pfeil_id"]
        st = self.board(aktion="sticker", art="idee", key=k)["sticker_id"]
        frei = self.board(aktion="sticker", art="problem", x=700, y=100)["sticker_id"]
        with self.assertRaises(projekte.ProjektFehler):
            self.board(aktion="sticker", art="kaffee", x=1, y=1)
        o = tafel.lesen(self.con, self.pid)["objekte"]
        self.assertEqual(o["pfeile"][0]["a"], {"key": k, "rx": 0.5, "ry": 1.0})   # auf die Tafel begrenzt
        self.assertEqual(o["pfeile"][0]["b"], {"x": 900, "y": 900})
        self.assertEqual([(x["art"], x.get("key")) for x in o["sticker"]], [("idee", k), ("problem", None)])
        self.board(aktion="sticker_bewegen", id=frei, key=k)
        self.assertEqual(tafel.lesen(self.con, self.pid)["objekte"]["sticker"][1], {"id": frei, "art": "problem", "key": k})
        self.board(aktion="objekte_weg", pfeile=[p], sticker=[st])
        o = tafel.lesen(self.con, self.pid)["objekte"]
        self.assertEqual((o["pfeile"], [x["id"] for x in o["sticker"]]), ([], [frei]))
        # eingefroren: Pfeile und Sticker gehoeren dazu
        b = besprechung._zeile(self.con, self.pid, self.woche)
        besprechung.aendern(self.con, self.pid, "lehrkraft", "gob", {"aktion": "abschliessen", "woche": self.woche})
        self.assertEqual(len(tafel.eingefroren(self.con, self.pid, b["id"])["objekte"]["sticker"]), 1)

    def test_rahmen(self):
        s1 = self.board(aktion="strich", punkte=[[520, 120], [600, 200]])["strich_id"]
        s2 = self.board(aktion="strich", punkte=[[900, 600], [950, 650]])["strich_id"]   # draussen
        k = self.board(aktion="postit", zone="ideen", text="Lüfter oben", x=540, y=220)["key"]
        st = self.board(aktion="sticker", art="idee", x=700, y=150)["sticker_id"]
        r = self.board(aktion="rahmen", titel="Gehäuse Variante B", x=500, y=100, w=400, h=300, striche=[s1, 999], sticker=[st],
                       postits=[k])["rahmen_id"]
        self.board(aktion="strich", rahmen=r, punkte=[[560, 150], [580, 170]])   # im Rahmen begonnen
        p = self.board(aktion="pfeil", a={"rahmen": r, "rx": 1, "ry": .5}, b={"x": 1000, "y": 250})["pfeil_id"]
        rr = tafel.lesen(self.con, self.pid)["objekte"]["rahmen"][0]
        self.assertEqual((rr["titel"], rr["striche"], rr["sticker"], rr["postits"]), ("Gehäuse Variante B", [s1, 3], [st], [k]))
        # verschieben: Striche, Sticker und Post-it gehen mit, der Strich draussen nicht
        self.board(aktion="rahmen_bewegen", id=r, dx=50, dy=20, postits={k: [590, 240]})
        t = tafel.lesen(self.con, self.pid)
        striche = {s["id"]: s for s in t["striche"]}
        self.assertEqual(striche[s1]["punkte"][0][:2], [570, 140])
        self.assertEqual(striche[s2]["punkte"][0][:2], [900, 600])
        self.assertEqual((t["objekte"]["sticker"][0]["x"], t["positionen"][k]), (750, [590, 240]))
        self.assertEqual((t["objekte"]["rahmen"][0]["x"], t["objekte"]["rahmen"][0]["y"]), (550, 120))
        # offene Rahmen wandern mit auf die naechste Tafel (samt Strichen, Sticker, Post-it-Lage und Pfeil zum Rahmen)
        besprechung.aendern(self.con, self.pid, "lehrkraft", "gob", {"aktion": "abschliessen", "woche": self.woche})
        self.woche = "2026-11-09"
        termine_regel = self.con.execute("SELECT id FROM projektzeit").fetchone()[0]
        self.zeit = "2026-11-06T10:00:00"
        termine.buchen(self.con, self.pid, "team", "Team", termine_regel, "2026-11-10", "08:45")
        neu = tafel.lesen(self.con, self.pid)
        self.assertEqual(neu["woche"], "2026-11-09")
        self.assertEqual([x["titel"] for x in neu["objekte"]["rahmen"]], ["Gehäuse Variante B"])
        self.assertEqual(sorted(s["id"] for s in neu["striche"]), [s1, 3])
        self.assertEqual(len(neu["objekte"]["pfeile"]), 0)   # freies Ende ausserhalb: bleibt auf der alten Tafel
        # Rahmen wird Auftrag mit Bild; sein Post-it erscheint nicht doppelt
        e = self.board(aktion="rahmen_ergebnis", id=r, zone="auftraege", frist="2026-11-17", bild_name="ab" * 12)
        eintrag = self.con.execute("SELECT * FROM eintrag WHERE id = ?", (int(e["key"][1:]),)).fetchone()
        self.assertEqual((eintrag["art"], eintrag["text"], eintrag["bild"]), ("auftrag", "Gehäuse Variante B", "ab" * 12))
        neu = tafel.lesen(self.con, self.pid)
        self.assertEqual(neu["objekte"]["rahmen"][0]["ergebnis"]["art"], "auftrag")
        self.assertNotIn(e["key"], [z["key"] for z in neu["postits"]])
        with self.assertRaises(projekte.ProjektFehler):
            self.board(aktion="rahmen_ergebnis", id=r, zone="absprachen")
        # loesen: Inhalt bleibt, Pfeilenden am Rahmen werden zu festen Punkten
        p2 = self.board(aktion="pfeil", a={"rahmen": r, "rx": 0, "ry": 0}, b={"x": 10, "y": 10})["pfeil_id"]
        self.board(aktion="rahmen_weg", id=r)
        o = tafel.lesen(self.con, self.pid)["objekte"]
        self.assertEqual(o["rahmen"], [])
        self.assertEqual([x["a"] for x in o["pfeile"] if x["id"] == p2], [{"x": 550, "y": 120}])
        del p

    def test_pdf_der_besprechung(self):
        from app import pdf
        # kleinstes JPEG, das den SOF-Marker hat (mehr braucht das PDF nicht zu wissen)
        jpeg = b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x10\x00\x20\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01\xff\xd9"
        name = tafel.bild_speichern(self.ordner, base64.b64encode(jpeg).decode())
        self.board(aktion="postit", zone="auftraege", text="Datenblatt Lüfter suchen", frist="2026-11-10", x=1100, y=350)
        self.board(aktion="postit", zone="absprachen", text="24 V ist freigegeben", x=1100, y=60)
        b = besprechung._zeile(self.con, self.pid, self.woche)
        besprechung.aendern(self.con, self.pid, "lehrkraft", "gob", {"aktion": "abschliessen", "woche": self.woche, "bild_name": name})
        inhalt = pdf.besprechung_pdf(self.con, self.ordner, self.pid, b["id"])
        self.assertTrue(inhalt.startswith(b"%PDF-1.4") and inhalt.rstrip().endswith(b"%%EOF"))
        self.assertEqual(inhalt.count(b"/Type /Page "), 2)
        self.assertIn(b"/Subtype /Image /Width 32 /Height 16", inhalt)
        self.assertIn("Datenblatt Lüfter suchen".encode("cp1252"), inhalt)
        self.assertIn(b"bis 10.11.2026", inhalt)
        self.assertEqual(pdf.dateiname(self.con, self.pid, b["id"]), "Besprechung KW 45 - Klimaanlage.pdf")
        # Bild nachtragen geht nur, solange keins da ist
        self.assertEqual(pdf.tafelbild_setzen(self.con, self.pid, b["id"], "x" * 24), name)
        with self.assertRaises(projekte.ProjektFehler):
            pdf.besprechung_pdf(self.con, self.ordner, self.anderes, b["id"])

    def test_anwesenheit(self):
        tafel.melden(self.pid, "tafel")
        tafel.melden(self.pid, "g-1")
        tafel.melden(self.pid, "g-2")
        self.assertEqual(tafel.anwesend(self.pid), {"tafel": True, "geraete": 2})
        self.assertEqual(tafel.anwesend(self.anderes), {"tafel": False, "geraete": 0})


if __name__ == "__main__":
    unittest.main()
