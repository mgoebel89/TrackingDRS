"""Tests fuer Stufe E: Anfragen (Rueckfrage, Ausleihe, Abnahme) und Bestelllisten (Fenster, Einreichen, Pruefen,
Sammelbestellung)."""
import shutil
import tempfile
import unittest
from unittest import mock

from app import anfragen, besprechung, bestellung, cockpit, db, konten, projekte, server, sheet, tafel, termine


class Basis(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        self.zeit = "2026-11-02T10:00:00"   # Montag
        uhr = mock.patch.object(db, "jetzt", side_effect=lambda: self.zeit)
        uhr.start()
        self.addCleanup(uhr.stop)
        with db.transaktion(self.con):
            self.gob = konten.anlegen(self.con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
            self.scu = konten.anlegen(self.con, "scu", "Herr Schu", "lehrkraft", "geheim123", vorlaeufig=False)
        leute = [{"vorname": "Lena", "nachname": "Schmitt"}]
        self.klima = projekte.anlegen(self.con, "gob", "Klimaanlage", "BSMT 22b", "2026-10-26", "2027-01-04", [self.gob["id"]], leute)
        self.hub = projekte.anlegen(self.con, "gob", "Hubtisch", "BSMT 22b", "2026-10-26", "2027-01-04", [self.gob["id"]], leute)
        self.greifer = projekte.anlegen(self.con, "gob", "Greifer", "BSMT 22a", "2026-10-26", "2027-01-04", [self.gob["id"]], leute)
        self.con.execute("UPDATE projekt SET erstellt = '2026-10-01T08:00:00'")

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)


class Anfragen(Basis):
    def test_rueckfrage_ueber_die_tafel_geklaert(self):
        aid = anfragen.anlegen(self.con, self.klima, {"art": "rueckfrage", "titel": "Dürfen wir 24 V nehmen?", "in_besprechung": True})
        frage = [z for z in tafel.lesen(self.con, self.klima)["postits"] if z["text"] == "Dürfen wir 24 V nehmen?"][0]
        tafel.aendern(self.con, self.klima, "gob", {"aktion": "erledigt", "key": frage["key"]})
        a = anfragen.liste(self.con, self.klima)[0]
        self.assertEqual((a["id"], a["status"]), (aid, "beantwortet"))
        self.assertIn("In der Besprechung", a["antwort"])

    def test_rueckfrage_antwort_pflicht_und_verlauf(self):
        anfragen.anlegen(self.con, self.klima, {"art": "rueckfrage", "titel": "Sonderfenster für Lüfter?"})
        aid = anfragen.liste(self.con, self.klima)[0]["id"]
        with self.assertRaises(projekte.ProjektFehler):
            anfragen.bearbeiten(self.con, self.klima, "gob", {"anfrage_id": aid, "status": "beantwortet"})
        anfragen.bearbeiten(self.con, self.klima, "gob", {"anfrage_id": aid, "status": "beantwortet", "antwort": "Ja, bis Do."})
        e = self.con.execute("SELECT wer, daten FROM ereignis WHERE art = 'anfrage_status'").fetchone()
        self.assertEqual(e["wer"], "gob")
        with self.assertRaises(projekte.ProjektFehler):   # schon in Bearbeitung
            anfragen.team_aendern(self.con, self.klima, {"aktion": "zurueckziehen", "anfrage_id": aid})

    def test_ausleihe_rueckgabe_ueberfaellig(self):
        aid = anfragen.anlegen(self.con, self.klima, {"art": "ausleihe", "titel": "Anemometer", "menge": "1", "von": "2026-11-03", "bis": "2026-11-10"})
        with self.assertRaises(projekte.ProjektFehler):
            anfragen.anlegen(self.con, self.klima, {"art": "ausleihe", "titel": "x", "von": "2026-11-10", "bis": "2026-11-03"})
        for status in ("bereitgelegt", "ausgegeben"):
            anfragen.bearbeiten(self.con, self.klima, "gob", {"anfrage_id": aid, "status": status})
        self.zeit = "2026-11-11T09:00:00"
        self.assertIn("rueckgabe_ueberfaellig", [w["art"] for w in termine.warnungen(self.con, self.klima)])
        self.assertTrue(anfragen.liste(self.con, self.klima)[0]["ueberfaellig"])
        anfragen.bearbeiten(self.con, self.klima, "gob", {"anfrage_id": aid, "status": "zurueck"})
        self.assertNotIn("rueckgabe_ueberfaellig", [w["art"] for w in termine.warnungen(self.con, self.klima)])

    def test_abnahme_im_verlauf_der_aufgabe(self):
        ph = sheet.lesen(self.con, self.klima)["phasen"][2]["id"]
        auf = sheet.aendern(self.con, self.klima, "team", "Team", {"aktion": "aufgabe_neu", "phase_id": ph, "titel": "Verdrahten"})["aufgabe_id"]
        aid = anfragen.anlegen(self.con, self.klima, {"art": "abnahme", "titel": "Netzteil prüfen", "aufgabe_id": auf})
        with self.assertRaises(projekte.ProjektFehler):   # nachbessern braucht einen Hinweis
            anfragen.bearbeiten(self.con, self.klima, "gob", {"anfrage_id": aid, "status": "nachbessern"})
        anfragen.bearbeiten(self.con, self.klima, "gob", {"anfrage_id": aid, "status": "nachbessern", "antwort": "PE fehlt"})
        anfragen.team_aendern(self.con, self.klima, {"aktion": "erneut", "anfrage_id": aid})
        anfragen.bearbeiten(self.con, self.klima, "gob", {"anfrage_id": aid, "status": "freigegeben"})
        arten = [(e["art"], e["daten"].get("status")) for e in sheet.aufgabe_verlauf(self.con, self.klima, auf)]
        self.assertIn(("anfrage_status", "freigegeben"), arten)

    def test_anfrage_wartet_nur_fuer_lehrkraft(self):
        anfragen.anlegen(self.con, self.klima, {"art": "rueckfrage", "titel": "Welcher Servo?"})
        self.zeit = "2026-11-03T18:00:00"
        self.assertNotIn("anfrage_wartet", [w["art"] for w in termine.warnungen(self.con, self.klima)])
        self.zeit = "2026-11-04T08:00:00"   # zwei Schultage spaeter
        self.assertIn("anfrage_wartet", [w["art"] for w in termine.warnungen(self.con, self.klima)])
        self.assertNotIn("anfrage_wartet", [w["art"] for w in server._team_termine(self.con, self.klima)["warnungen"]])
        self.assertIn("anfrage", [e["art"] for e in cockpit.cockpit(self.con, self.gob)["erledigen"]])


class Bestellung(Basis):
    def pos(self, pid, **d):
        daten = {"aktion": "position_neu", "artikel": "Axiallüfter 80 mm", "bestellnr": "FAN 8025-24", "menge": 2, "preis": "8,90 €",
                 "lieferant": "Elektronikversand"}
        daten.update(d)
        return bestellung.team_aendern(self.con, pid, daten)["position_id"]

    def entscheiden(self, pid, posid, **d):
        bestellung.pruefen(self.con, pid, "gob", dict(d, aktion="entscheiden", position_id=posid))

    def test_ablauf(self):
        p1 = self.pos(self.klima)
        p2 = self.pos(self.klima, artikel="Gitter 80 mm", bestellnr="GRILL 80")
        p3 = self.pos(self.klima, artikel="DS18B20", bestellnr="DS18B20-WP")
        p4 = self.pos(self.klima, artikel="Aluprofil", bestellnr="", lieferant="Mechanikshop")
        p5 = self.pos(self.klima, artikel="Gold", lieferant="Juwelier")
        bestellung.team_aendern(self.con, self.klima, {"aktion": "position_aendern", "position_id": p1, "menge": 3})
        p6 = self.pos(self.klima, artikel="doch nicht")
        bestellung.team_aendern(self.con, self.klima, {"aktion": "position_streichen", "position_id": p6})
        with self.assertRaises(projekte.ProjektFehler):   # kein Fenster offen
            bestellung.team_aendern(self.con, self.klima, {"aktion": "einreichen"})
        bestellung.fenster_anlegen(self.con, self.gob, {"von": "2026-11-09", "bis": "2026-11-12T12:00", "klasse": "BSMT 22b"})
        sicht = bestellung.team_sicht(self.con, self.klima)
        self.assertEqual(sicht["lage"]["naechstes"]["bis"], "2026-11-12T12:00:00")
        self.assertIsNone(bestellung.team_sicht(self.con, self.greifer)["lage"]["naechstes"])   # andere Klasse
        self.zeit = "2026-11-11T13:00:00"
        self.assertIn("bestellfenster_schliesst", [w["art"] for w in termine.warnungen(self.con, self.klima)])
        bestellung.team_aendern(self.con, self.klima, {"aktion": "einreichen"})
        with self.assertRaises(projekte.ProjektFehler):   # eingefroren
            bestellung.team_aendern(self.con, self.klima, {"aktion": "position_aendern", "position_id": p1, "menge": 9})
        with self.assertRaises(projekte.ProjektFehler):   # einmal je Fenster
            self.pos(self.klima, artikel="neu für nächstes Mal")
            bestellung.team_aendern(self.con, self.klima, {"aktion": "einreichen"})
        # Hubtisch bestellt denselben Luefter (bestellen) und noch etwas (bleibt ungeprueft)
        h1 = self.pos(self.hub, menge=1)
        self.pos(self.hub, artikel="Motor", bestellnr="M1")
        bestellung.team_aendern(self.con, self.hub, {"aktion": "einreichen"})
        self.entscheiden(self.hub, h1, entscheidung="bestellen")
        # Pruefen je Position
        with self.assertRaises(projekte.ProjektFehler):
            self.entscheiden(self.klima, p5, entscheidung="ablehnen")
        self.entscheiden(self.klima, p1, entscheidung="bestellen")
        self.entscheiden(self.klima, p2, entscheidung="lager", kommentar="Regal B3", menge_genehmigt=1)
        self.entscheiden(self.klima, p3, entscheidung="ersetzen", ersatz_artikel="DS18B20-Modul", ersatz_bestellnr="MOD-DS18B20",
                         ersatz_lieferant="Elektronikversand", ersatz_weg="bestellen")
        self.entscheiden(self.klima, p4, entscheidung="firma")
        self.assertIsNone(self.con.execute("SELECT geprueft FROM bestellliste WHERE id = (SELECT liste_id FROM position WHERE id = ?)",
                                           (p1,)).fetchone()[0])
        self.entscheiden(self.klima, p5, entscheidung="ablehnen", kommentar="kein Bedarf")
        self.assertIsNotNone(self.con.execute("SELECT geprueft FROM bestellliste WHERE id = (SELECT liste_id FROM position WHERE id = ?)",
                                              (p1,)).fetchone()[0])
        # Status: nur passend zum Weg
        bestellung.pruefen(self.con, self.klima, "gob", {"aktion": "status", "position_id": p1, "status": "bestellt"})
        with self.assertRaises(projekte.ProjektFehler):
            bestellung.pruefen(self.con, self.klima, "gob", {"aktion": "status", "position_id": p4, "status": "bestellt"})
        # Abgelehntes in die naechste Liste
        bestellung.team_aendern(self.con, self.klima, {"aktion": "uebernehmen", "position_id": p5})
        with self.assertRaises(projekte.ProjektFehler):
            bestellung.team_aendern(self.con, self.klima, {"aktion": "uebernehmen", "position_id": p5})
        with self.assertRaises(projekte.ProjektFehler):
            bestellung.team_aendern(self.con, self.klima, {"aktion": "uebernehmen", "position_id": p1})
        artikel = [p["artikel"] for p in bestellung.team_sicht(self.con, self.klima)["sammel"]["positionen"]]
        self.assertEqual(artikel, ["neu für nächstes Mal", "Gold"])
        # Sammelbestellung: je Lieferant, gleiche Bestellnummer zusammengefasst, Ersatz dabei, Lager/Firma/Abgelehnt nicht
        fid = self.con.execute("SELECT id FROM bestellfenster").fetchone()[0]
        s = bestellung.sammelbestellung(self.con, self.gob, fid)
        self.assertEqual([g["lieferant"] for g in s["lieferanten"]], ["Elektronikversand"])
        zeilen = {z["bestellnr"]: z for z in s["lieferanten"][0]["zeilen"]}
        self.assertEqual((zeilen["FAN 8025-24"]["menge"], zeilen["FAN 8025-24"]["teams"]), (4, ["Klimaanlage", "Hubtisch"]))
        self.assertEqual(sorted(zeilen), ["FAN 8025-24", "MOD-DS18B20"])
        csv = bestellung.sammelbestellung_csv(s).decode("utf-8")
        self.assertTrue(csv.startswith("﻿Lieferant;Artikel"))
        self.assertIn("Klimaanlage, Hubtisch", csv)
        # nach dem Stichtag: Hubtisch noch nicht geprueft
        self.zeit = "2026-11-12T13:00:00"
        self.assertIn("listen_warten", [w["art"] for w in termine.warnungen(self.con, self.hub)])
        with self.assertRaises(projekte.ProjektFehler):   # fremde Lehrkraft
            bestellung.sammelbestellung(self.con, self.scu, fid)

    def test_sonderfenster_nur_fuer_ein_team(self):
        self.pos(self.klima)
        self.pos(self.hub)
        bestellung.fenster_anlegen(self.con, self.gob, {"von": "2026-11-02", "bis": "2026-11-03T12:00", "projekt_id": self.klima})
        bestellung.team_aendern(self.con, self.klima, {"aktion": "einreichen"})
        with self.assertRaises(projekte.ProjektFehler):
            bestellung.team_aendern(self.con, self.hub, {"aktion": "einreichen"})
        self.assertIn("sonderfenster", [r[0] for r in self.con.execute("SELECT art FROM ereignis WHERE projekt_id = ?", (self.klima,))])
        u = bestellung.uebersicht(self.con, self.gob)
        self.assertEqual([t["titel"] for t in u["fenster"][0]["teams"]], ["Klimaanlage"])


if __name__ == "__main__":
    unittest.main()
