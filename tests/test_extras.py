"""Tests fuer Stufe F: Fotos, Mindmap, Lehrernotizen, Vorlagen, Excel-Export, Bericht, Archiv, Loeschen, Sicherung."""
import base64
import io
import os
import shutil
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from unittest import mock

from app import anfragen, besprechung, bestellung, db, export, extras, konten, projekte, server, sheet, tafel, termine

JPEG = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 300).decode()
PDF = base64.b64encode(b"%PDF-1.4\n%\xe2\xe3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF").decode()


class Extras(unittest.TestCase):
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
        self.andere = projekte.anlegen(self.con, "gob", "Hubtisch", "BSMT 22b", "2026-10-26", "2027-01-04", [self.gob["id"]], leute)
        self.planen = sheet.lesen(self.con, self.pid)["phasen"][1]["id"]

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def test_fotos(self):
        team = extras.foto_neu(self.con, self.pid, self.ordner, "team", "Team", {"bild": JPEG, "titel": "Gehäuse, 1. Druck"})
        lk = extras.foto_neu(self.con, self.pid, self.ordner, "lehrkraft", "gob", {"bild": JPEG})
        with self.assertRaises(projekte.ProjektFehler):   # kein PDF als Foto
            extras.foto_neu(self.con, self.pid, self.ordner, "team", "Team", {"bild": PDF})
        with self.assertRaises(projekte.ProjektFehler):   # das Team entfernt nur eigene
            extras.foto_verwerfen(self.con, self.pid, "team", "Team", lk)
        extras.foto_verwerfen(self.con, self.pid, "team", "Team", team)
        self.assertEqual([f["id"] for f in extras.fotos(self.con, self.pid)], [lk])
        name = extras.fotos(self.con, self.pid)[0]["name"]
        self.assertEqual(tafel.bild_pfad(self.con, self.ordner, self.pid, name)[1], "image/jpeg")
        self.assertEqual(tafel.bild_pfad(self.con, self.ordner, self.andere, name), (None, None))

    def test_mindmap_pdf_und_ersetzen(self):
        extras.mindmap_setzen(self.con, self.pid, self.ordner, "gob", {"inhalt": JPEG})
        extras.mindmap_setzen(self.con, self.pid, self.ordner, "gob", {"inhalt": PDF, "titel": "Mindmap v2"})
        m = extras.mindmap(self.con, self.pid)
        self.assertEqual((m["titel"], m["typ"]), ("Mindmap v2", "application/pdf"))
        self.assertTrue(tafel.bild_pfad(self.con, self.ordner, self.pid, m["name"])[0].endswith(".pdf"))
        with self.assertRaises(projekte.ProjektFehler):
            extras.mindmap_setzen(self.con, self.pid, self.ordner, "gob", {"inhalt": base64.b64encode(b"<html>").decode()})

    def test_lehrernotizen_nie_beim_team(self):
        nid = extras.notiz_neu(self.con, self.pid, "gob", "Lena fehlt oft.")
        extras.notiz_aendern(self.con, self.pid, "gob", nid, {"text": "Lena fehlt oft, Gespräch geführt."})
        besprechung.aendern(self.con, self.pid, "lehrkraft", "gob", {"aktion": "notizen", "text": "Notiz aus der Besprechung"})
        texte = [n["text"] for n in extras.notizen(self.con, self.pid)]
        self.assertIn("Lena fehlt oft, Gespräch geführt.", texte)
        self.assertIn("Notiz aus der Besprechung", texte)
        token = self.con.execute("SELECT link_token FROM projekt WHERE id = ?", (self.pid,)).fetchone()[0]

        class H:
            def antwort(self, status, inhalt, *rest, **mehr):
                self.inhalt = inhalt
        h = H()
        server.api_team_extras(h, self.con, {}, token)
        self.assertNotIn("Lena fehlt", str(h.inhalt))
        extras.notiz_aendern(self.con, self.pid, "gob", nid, {"verworfen": True})
        self.assertNotIn("Lena fehlt oft, Gespräch geführt.", [n["text"] for n in extras.notizen(self.con, self.pid)])
        self.assertFalse(self.con.execute("SELECT 1 FROM ereignis WHERE daten LIKE '%Lena fehlt%'").fetchone())

    def test_vorlagen(self):
        sheet.aendern(self.con, self.pid, "team", "Team", {"aktion": "aufgabe_neu", "phase_id": self.planen, "titel": "Lüfter auslegen"})
        nur = extras.vorlage_speichern(self.con, self.pid, "Klima-Vorlage")
        mit = extras.vorlage_speichern(self.con, self.pid, "Klima mit Team", mit_team=True)
        self.assertNotEqual(nur, mit)
        neu = projekte.anlegen(self.con, "gob", "Neu", "BSMT 23a", "2027-02-01", "2027-06-28", [self.gob["id"]], [], vorlage=mit)
        titel = [a["titel"] for ph in sheet.lesen(self.con, neu)["phasen"] for a in ph["aufgaben"]]
        self.assertIn("Lüfter auslegen", titel)
        neu2 = projekte.anlegen(self.con, "gob", "Neu2", "BSMT 23a", "2027-02-01", "2027-06-28", [self.gob["id"]], [], vorlage=nur)
        self.assertNotIn("Lüfter auslegen", [a["titel"] for ph in sheet.lesen(self.con, neu2)["phasen"] for a in ph["aufgaben"]])
        with self.assertRaises(projekte.ProjektFehler):
            extras.vorlage_entfernen(self.con, "standard")
        extras.vorlage_entfernen(self.con, nur)
        self.assertNotIn(nur, [v["schluessel"] for v in projekte.vorlagen(self.con)])

    def test_excel_export(self):
        aid = sheet.aendern(self.con, self.pid, "team", "Team", {"aktion": "aufgabe_neu", "phase_id": self.planen, "titel": "Lüfter <24 V> & Co"})["aufgabe_id"]
        lena = sheet.lesen(self.con, self.pid)["mitglieder"][0]["id"]
        sheet.aendern(self.con, self.pid, "team", "Team", {"aktion": "plan", "aufgabe_id": aid, "wochen": ["2026-10-26", "2026-11-02"], "wert": True})
        sheet.aendern(self.con, self.pid, "team", "Team", {"aktion": "ende", "aufgabe_id": aid, "woche": "2026-11-02"})
        sheet.aendern(self.con, self.pid, "team", "Team", {"aktion": "ampel", "aufgabe_id": aid, "woche": "2026-10-26", "ampel": "y",
                                                           "problem": "zu laut", "massnahme": "anderer", "verantwortlich_id": lena})
        daten = export.sheet_xlsx(self.con, self.pid)
        z = zipfile.ZipFile(io.BytesIO(daten))
        self.assertIn("xl/worksheets/sheet3.xml", z.namelist())
        for name in z.namelist():   # alles wohlgeformtes XML
            if name.endswith(".xml") or name.endswith(".rels"):
                ET.fromstring(z.read(name))
        blatt = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("Lüfter &lt;24 V&gt; &amp; Co", blatt)
        self.assertIn("<t xml:space=\"preserve\">y</t>", blatt)
        self.assertIn("<t xml:space=\"preserve\">e</t>", blatt)
        self.assertIn("zu laut", z.read("xl/worksheets/sheet2.xml").decode("utf-8"))
        self.assertEqual(export._spalte(0) + export._spalte(25) + export._spalte(26), "AZAA")

    def test_bericht(self):
        extras.notiz_neu(self.con, self.pid, "gob", "geheim")
        b = export.bericht(self.con, self.pid)
        self.assertIsNone(b["notizen"])
        self.assertEqual(b["projekt"]["titel"], "Klimaanlage")
        self.assertIn("phasen", b["sheet"])
        self.assertEqual(export.bericht(self.con, self.pid, mit_notizen=True)["notizen"][0]["text"], "geheim")

    def test_archiv_loeschen(self):
        extras.foto_neu(self.con, self.pid, self.ordner, "team", "Team", {"bild": JPEG})
        anfragen.anlegen(self.con, self.pid, {"art": "rueckfrage", "titel": "x", "in_besprechung": True})
        bestellung.fenster_anlegen(self.con, self.gob, {"von": "2026-11-02", "bis": "2026-11-03T12:00", "projekt_id": self.pid})
        bestellung.team_aendern(self.con, self.pid, {"aktion": "position_neu", "artikel": "Lüfter"})
        bestellung.team_aendern(self.con, self.pid, {"aktion": "einreichen"})
        regel = termine.regel_anlegen(self.con, self.gob, {
            "klasse": "BSMT 22b", "wochentag": 1, "rhythmus": "jede", "von": "08:00", "bis": "11:15", "fenster_von": "08:30",
            "fenster_bis": "10:00", "laenge": 15, "schluss_tage": 1, "schluss_zeit": "18:00",
            "gueltig_von": "2026-08-01", "gueltig_bis": "2027-07-31"})
        termine.buchen(self.con, self.pid, "team", "Team", regel, "2026-11-03", "08:30")
        tafel.aendern(self.con, self.pid, "gob", {"aktion": "strich", "punkte": [[1, 1], [2, 2]]})
        datei = os.path.join(self.ordner, "bilder", extras.fotos(self.con, self.pid)[0]["name"] + ".jpg")
        with self.assertRaises(projekte.ProjektFehler):   # nur archivierte
            extras.loeschen(self.con, self.pid, self.ordner, "gob", "Klimaanlage")
        self.assertEqual(projekte.archivieren_schuljahr(self.con, self.gob, "2026/27"), 2)
        with self.assertRaises(projekte.ProjektFehler):   # Titel muss stimmen
            extras.loeschen(self.con, self.pid, self.ordner, "gob", "klimaanlage")
        extras.loeschen(self.con, self.pid, self.ordner, "gob", "Klimaanlage")
        for tabelle in ("projekt", "ereignis", "eintrag", "anfrage", "bestellliste", "buchung", "datei", "besprechung"):
            self.assertFalse(self.con.execute("SELECT 1 FROM %s WHERE %s = ?" % (tabelle, "id" if tabelle == "projekt" else "projekt_id"),
                                              (self.pid,)).fetchone(), tabelle)
        self.assertFalse(self.con.execute("SELECT 1 FROM bestellfenster").fetchone())
        self.assertFalse(os.path.exists(datei))
        self.assertTrue(self.con.execute("SELECT 1 FROM projekt WHERE id = ?", (self.andere,)).fetchone())
        self.assertEqual(self.con.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_sicherung(self):
        extras.foto_neu(self.con, self.pid, self.ordner, "team", "Team", {"bild": JPEG})
        pfad = extras.sicherung(self.con, self.ordner)
        try:
            with zipfile.ZipFile(pfad) as z:
                namen = z.namelist()
                self.assertIn("trackingdrs.sqlite", namen)
                self.assertTrue(any(n.startswith("bilder/") for n in namen))
                self.assertFalse(any(n.startswith("tls") for n in namen))
                kopie = os.path.join(self.ordner, "kopie.sqlite")
                with open(kopie, "wb") as f:
                    f.write(z.read("trackingdrs.sqlite"))
            c = sqlite3.connect(kopie)
            self.assertEqual(c.execute("SELECT titel FROM projekt WHERE id = ?", (self.pid,)).fetchone()[0], "Klimaanlage")
            c.close()
        finally:
            os.remove(pfad)


if __name__ == "__main__":
    unittest.main()
