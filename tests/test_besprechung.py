"""Tests fuer Stufe D1: Besprechung (Vorbereitung, Fragen, Kurzzusammenfassung, Ergebnis, Abschliessen, Auftraege)."""
import shutil
import tempfile
import unittest
from unittest import mock

from app import besprechung, cockpit, db, konten, projekte, server, sheet, termine


class Besprechung(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        self.zeit = "2026-11-02T10:00:00"   # Montag, KW 45
        uhr = mock.patch.object(db, "jetzt", side_effect=lambda: self.zeit)
        uhr.start()
        self.addCleanup(uhr.stop)
        with db.transaktion(self.con):
            self.gob = konten.anlegen(self.con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
        self.pid = projekte.anlegen(self.con, "gob", "Klimaanlage", "BSMT 22b", "2026-10-26", "2027-01-04", [self.gob["id"]],
                                    [{"vorname": "Lena", "nachname": "Schmitt"}, {"vorname": "Ben", "nachname": "Weber"}])
        self.con.execute("UPDATE projekt SET erstellt = '2026-10-01T08:00:00'")
        self.regel = termine.regel_anlegen(self.con, self.gob, {
            "klasse": "BSMT 22b", "wochentag": 1, "rhythmus": "jede", "von": "08:00", "bis": "11:15", "fenster_von": "08:30",
            "fenster_bis": "10:00", "laenge": 15, "schluss_tage": 1, "schluss_zeit": "18:00",
            "gueltig_von": "2026-08-01", "gueltig_bis": "2027-07-31"})
        termine.buchen(self.con, self.pid, "team", "Team", self.regel, "2026-11-03", "08:45")
        d = sheet.lesen(self.con, self.pid)
        self.planen = d["phasen"][1]["id"]
        self.lena = [m for m in d["mitglieder"] if m["vorname"] == "Lena"][0]["id"]

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def team(self, **d):
        return besprechung.aendern(self.con, self.pid, "team", "Team", d)

    def lk(self, **d):
        return besprechung.aendern(self.con, self.pid, "lehrkraft", "gob", d)

    def sh(self, **d):
        return sheet.aendern(self.con, self.pid, "team", "Team", d)

    def test_ablauf_vorbereiten_besprechen_abschliessen(self):
        self.assertEqual(besprechung.lesen(self.con, self.pid)["termin"], {"datum": "2026-11-03", "uhrzeit": "08:45"})
        self.team(aktion="vorbereitung", text="Gehäuse gedruckt, Lüfter fehlt noch.")
        frage = self.team(aktion="eintrag_neu", art="frage", text="Dürfen wir 24 V nehmen?")["eintrag_id"]
        with self.assertRaises(projekte.ProjektFehler):   # Auftraege vergibt nur die Lehrkraft
            self.team(aktion="eintrag_neu", art="auftrag", text="x", frist="2026-11-10")
        with self.assertRaises(projekte.ProjektFehler):
            self.team(aktion="notizen", text="geheim")
        # Besprechung am Dienstag
        self.zeit = "2026-11-03T08:50:00"
        self.lk(aktion="notizen", text="Team wirkt unsicher bei der Auslegung.")
        self.lk(aktion="erledigt", eintrag_id=frage)
        with self.assertRaises(projekte.ProjektFehler):   # Auftrag ohne Frist
            self.lk(aktion="eintrag_neu", art="auftrag", text="2 Lüfter vergleichen")
        auftrag = self.lk(aktion="eintrag_neu", art="auftrag", text="2 Lüfter vergleichen", frist="2026-11-10",
                          verantwortlich_id=self.lena)["eintrag_id"]
        self.lk(aktion="eintrag_neu", art="absprache", text="24 V ist freigegeben")
        self.lk(aktion="meilenstein", titel="Konstruktion fertig", meilenstein_woche="2026-11-23")
        d = besprechung.lesen(self.con, self.pid, lehrkraft=True)
        self.assertEqual([e["art"] for e in d["ergebnis"]], ["auftrag", "absprache", "meilenstein"])
        self.assertEqual(d["notizen"], "Team wirkt unsicher bei der Auslegung.")
        self.assertEqual(d["zusammenfassung"]["vorbereitung"], "Gehäuse gedruckt, Lüfter fehlt noch.")
        self.assertIn("Konstruktion fertig", [m["titel"] for m in sheet.lesen(self.con, self.pid)["meilensteine"]])
        self.lk(aktion="abschliessen", woche="2026-11-02")
        with self.assertRaises(projekte.ProjektFehler):   # doppelt (z. B. Doppelklick): nicht die naechste Woche schliessen
            self.lk(aktion="abschliessen", woche="2026-11-02")
        with self.assertRaises(projekte.ProjektFehler):
            self.team(aktion="eintrag_neu", art="frage", text="zu spät", woche="2026-11-02")
        # Protokoll: das Team sieht Ergebnis und geklaerte Fragen, aber nie die Lehrernotizen
        team = besprechung.lesen(self.con, self.pid)
        p = team["protokolle"][0]
        self.assertEqual([e["text"] for e in p["ergebnis"]], ["2 Lüfter vergleichen", "24 V ist freigegeben", "Konstruktion fertig"])
        self.assertEqual([e["text"] for e in p["geklaert"]], ["Dürfen wir 24 V nehmen?"])
        self.assertNotIn("notizen", p)
        self.assertNotIn("unsicher", str(team))
        self.assertIn("unsicher", str(besprechung.lesen(self.con, self.pid, lehrkraft=True)["protokolle"][0]))
        # danach ist die naechste Woche dran, der offene Auftrag wandert mit
        self.assertEqual(team["woche"], "2026-11-09")
        self.assertEqual([e["id"] for e in team["eintraege"] if e["art"] == "auftrag"], [auftrag])
        # Auftrag ueberfaellig: Warnung fuer Team und Lehrkraft, abhaken loest sie auf
        self.zeit = "2026-11-11T09:00:00"
        arten = [w["art"] for w in termine.warnungen(self.con, self.pid)]
        self.assertIn("auftrag_ueberfaellig", arten)
        self.assertIn("auftrag_ueberfaellig", [b["art"] for b in cockpit.cockpit(self.con, self.gob)["blick"]])
        self.team(aktion="erledigt", eintrag_id=auftrag)
        self.assertNotIn("auftrag_ueberfaellig", [w["art"] for w in termine.warnungen(self.con, self.pid)])

    def test_kurzzusammenfassung(self):
        aid = self.sh(aktion="aufgabe_neu", phase_id=self.planen, titel="Lüfter auslegen")["aufgabe_id"]
        self.sh(aktion="verantwortlich", aufgabe_id=aid, mitglied_id=self.lena)
        self.sh(aktion="plan", aufgabe_id=aid, wochen=["2026-10-26", "2026-11-02"], wert=True)
        self.sh(aktion="ende", aufgabe_id=aid, woche="2026-11-02")
        sheet.basisplan_setzen(self.con, self.pid, "gob")
        self.sh(aktion="ende", aufgabe_id=aid, woche="2026-11-16")
        self.sh(aktion="ampel", aufgabe_id=aid, woche="2026-10-26", ampel="y", problem="Volumenstrom zu gering",
                massnahme="größeren Lüfter", verantwortlich_id=self.lena)
        self.sh(aktion="ampel", aufgabe_id=aid, woche="2026-11-02", ampel="r", problem="Lüfter nicht lieferbar",
                massnahme="Alternative suchen", verantwortlich_id=self.lena)
        self.sh(aktion="meilenstein_neu", woche="2026-11-23", titel="Konstruktion fertig")
        z = besprechung.zusammenfassung(self.con, self.pid, "2026-11-02")
        texte = [a["text"] for a in z["aenderungen"]]
        self.assertIn("Neue Tätigkeit „Lüfter auslegen“", texte)
        self.assertIn("„Lüfter auslegen“: Ende keins → KW 47", texte)   # zusammengefasst: erster alter, letzter neuer Wert
        self.assertIn("„Lüfter auslegen“: KW 45 rot – Lüfter nicht lieferbar", texte)
        self.assertEqual(z["ampel"], {"woche": "2026-11-02", "ampel": "r"})
        pr = z["probleme"][0]
        self.assertEqual((pr["ampel"], pr["seit"], pr["problem"], pr["verantwortlich"]), ("r", "2026-10-26", "Lüfter nicht lieferbar", "LS"))
        self.assertEqual(z["ausblick"]["titel"], "Konstruktion fertig")
        self.assertEqual(z["ausblick"]["projektwochen"], 4)   # KW 45 bis KW 48, jede Woche Projekttag
        self.assertEqual(z["basisplan"], "1 Endtermin später")

    def test_team_darf_nur_eigenes_verwerfen(self):
        auftrag = self.lk(aktion="eintrag_neu", art="auftrag", text="Datenblatt suchen", frist="2026-11-05")["eintrag_id"]
        idee = self.team(aktion="eintrag_neu", art="idee", text="2 Lüfter parallel?")["eintrag_id"]
        with self.assertRaises(projekte.ProjektFehler):
            self.team(aktion="verwerfen", eintrag_id=auftrag)
        self.team(aktion="verwerfen", eintrag_id=idee)
        self.assertEqual([e["id"] for e in besprechung.lesen(self.con, self.pid)["eintraege"]], [auftrag])

    def test_team_api_ohne_notizen(self):
        self.lk(aktion="notizen", text="nur für mich")
        token = self.con.execute("SELECT link_token FROM projekt WHERE id = ?", (self.pid,)).fetchone()[0]

        class H:
            def antwort(self, status, inhalt):
                self.inhalt = inhalt
        h = H()
        server.api_team_besprechung(h, self.con, {}, token)
        self.assertNotIn("nur für mich", str(h.inhalt))
        self.assertNotIn("zusammenfassung", h.inhalt["besprechung"])


if __name__ == "__main__":
    unittest.main()
