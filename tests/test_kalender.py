"""Tests fuer Stufe C2: Kalender-Abos (ICS), Ferien aus dem Schulkalender, Cockpit, Kalender und Aktivitaeten."""
import datetime
import json
import shutil
import tempfile
import unittest
from unittest import mock

from app import cockpit, db, kalender, konten, projekte, server, sheet, termine

DIENST = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:Microsoft Exchange Server 2010
BEGIN:VTIMEZONE
TZID:W. Europe Standard Time
BEGIN:STANDARD
DTSTART:16010101T030000
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=-1SU;BYMONTH=10
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:16010101T020000
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=-1SU;BYMONTH=3
END:DAYLIGHT
END:VTIMEZONE
BEGIN:VEVENT
UID:aufsicht
SUMMARY:Aufsicht
DTSTART;TZID=W. Europe Standard Time:20261020T133000
DTEND;TZID=W. Europe Standard Time:20261020T135000
RRULE:FREQ=WEEKLY;BYDAY=TU
EXDATE;TZID=W. Europe Standard Time:20261110T133000
END:VEVENT
BEGIN:VEVENT
UID:konferenz
SUMMARY:Lehrerkonferenz
LOCATION:Aula
DTSTART:20261102T130000Z
DTEND:20261102T150000Z
END:VEVENT
BEGIN:VEVENT
UID:abgesagt
SUMMARY:Abgesagt
STATUS:CANCELLED
DTSTART;VALUE=DATE:20261104
DTEND;VALUE=DATE:20261105
END:VEVENT
BEGIN:VEVENT
UID:padtag
SUMMARY:P\xc3\xa4d. Tag
DTSTART;VALUE=DATE:20261113
DTEND;VALUE=DATE:20261114
END:VEVENT
END:VCALENDAR
""".replace(b"\n", b"\r\n")

SCHULE = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:herbst
SUMMARY:Herbstferien
DTSTART;VALUE=DATE:20261116
DTEND;VALUE=DATE:20261121
END:VEVENT
BEGIN:VEVENT
UID:eltern
SUMMARY:Elternsprechtag
DTSTART;VALUE=DATE:20261109
DTEND;VALUE=DATE:20261110
END:VEVENT
END:VCALENDAR
""".replace(b"\n", b"\r\n")


@unittest.skipIf(kalender.icalendar is None, "python3-icalendar / recurring-ical-events fehlen")
class Ics(unittest.TestCase):
    def test_outlook_serie_ausnahme_abgesagt_ganztags(self):
        liste = kalender.termine_aus_ics(DIENST, datetime.date(2026, 10, 26), datetime.date(2026, 11, 20))
        kurz = [(t["beginn"], t["ende"], t["titel"]) for t in liste]
        self.assertIn(("2026-10-27T13:30", "2026-10-27T13:50", "Aufsicht"), kurz)       # nach der Zeitumstellung gleiche Uhrzeit
        self.assertIn(("2026-11-02T14:00", "2026-11-02T16:00", "Lehrerkonferenz"), kurz)  # UTC -> Berlin
        self.assertIn(("2026-11-13", "2026-11-13", "Päd. Tag"), kurz)                    # Ende einschliesslich
        self.assertNotIn("2026-11-10T13:30", [t["beginn"] for t in liste])               # Ausnahme der Serie
        self.assertNotIn("Abgesagt", [t["titel"] for t in liste])
        self.assertEqual([t["ort"] for t in liste if t["titel"] == "Lehrerkonferenz"], ["Aula"])

    def test_ferien_aus_stichwoertern(self):
        liste = kalender.termine_aus_ics(SCHULE, datetime.date(2026, 10, 1), datetime.date(2027, 1, 1))
        self.assertEqual(kalender.ferien_aus(liste, kalender.STICHWOERTER), [("2026-11-16", "2026-11-20", "Herbstferien")])
        self.assertEqual(len(kalender.ferien_aus(liste, "ferien, sprechtag")), 2)

    def test_kein_kalender(self):
        with self.assertRaises(projekte.ProjektFehler):
            kalender.termine_aus_ics(b"<html>Anmeldung</html>", datetime.date(2026, 1, 1), datetime.date(2026, 2, 1))


class Adressen(unittest.TestCase):
    def test_url(self):
        self.assertEqual(kalender.url_pruefen(" webcal://outlook.office365.com/owa/calendar/x/calendar.ics "),
                         "https://outlook.office365.com/owa/calendar/x/calendar.ics")
        for falsch in ("http://example.org/a.ics", "ftp://x/y", "", "kalender.ics"):
            with self.assertRaises(projekte.ProjektFehler):
                kalender.url_pruefen(falsch)

    def test_nur_internet(self):
        for intern in ("https://127.0.0.1/a.ics", "https://192.168.2.1/a.ics", "https://localhost/a.ics", "https://[::1]/a.ics"):
            with self.assertRaises(projekte.ProjektFehler):
                kalender.herunterladen(intern)


class MitProjekten(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        self.zeit = "2026-11-03T07:30:00"   # Dienstag, KW 45
        uhr = mock.patch.object(db, "jetzt", side_effect=lambda: self.zeit)
        uhr.start()
        self.addCleanup(uhr.stop)
        with db.transaktion(self.con):
            self.gob = konten.anlegen(self.con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
            self.scu = konten.anlegen(self.con, "scu", "Herr Schu", "lehrkraft", "geheim123", vorlaeufig=False)
        leute = [{"vorname": "Lena", "nachname": "Schmitt"}]
        self.klima = projekte.anlegen(self.con, "gob", "Klimaanlage", "BSMT 22b", "2026-09-28", "2027-01-04", [self.gob["id"]], leute)
        self.hub = projekte.anlegen(self.con, "gob", "Hubtisch", "BSMT 22b", "2026-09-28", "2027-01-04", [self.gob["id"]], [])
        self.fremd = projekte.anlegen(self.con, "scu", "Förderband", "BSMT 22a", "2026-09-28", "2027-01-04", [self.scu["id"]], leute)
        self.con.execute("UPDATE projekt SET erstellt = '2026-09-01T08:00:00'")
        self.regel = termine.regel_anlegen(self.con, self.gob, {
            "klasse": "BSMT 22b", "wochentag": 1, "rhythmus": "jede", "von": "08:00", "bis": "11:15", "fenster_von": "08:30",
            "fenster_bis": "10:00", "laenge": 15, "schluss_tage": 1, "schluss_zeit": "18:00",
            "gueltig_von": "2026-08-01", "gueltig_bis": "2027-07-31"})

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def team(self, pid, **d):
        return sheet.aendern(self.con, pid, "team", "Team", d)

    @unittest.skipIf(kalender.icalendar is None, "Pakete fehlen")
    def test_schulkalender_ferien_und_fehler(self):
        termine.buchen(self.con, self.klima, "lehrkraft", "gob", self.regel, "2026-11-17", "08:30")
        with mock.patch.object(kalender, "url_pruefen", side_effect=lambda u: u):
            with db.transaktion(self.con):
                self.con.execute("INSERT INTO kalender_abo (art, url) VALUES ('schule', 'https://schule.example/k.ics')")
        status = kalender.abrufen(self.con, "schule", laden=lambda url: SCHULE)
        self.assertEqual((status["anzahl"], status["fehler"]), (2, None))
        ferien = self.con.execute("SELECT von, bis, name, quelle FROM ferien WHERE aktiv = 1").fetchall()
        self.assertEqual([tuple(f) for f in ferien], [("2026-11-16", "2026-11-20", "Herbstferien", "abo")])
        # die Buchung in den Ferien entfaellt, vermerkt vom System
        e = self.con.execute("SELECT wer_art, daten FROM ereignis WHERE art = 'termin_entfallen'").fetchone()
        self.assertEqual((e["wer_art"], json.loads(e["daten"])["grund"]), ("system", "Herbstferien"))
        # Fehler beim naechsten Abruf: alte Termine bleiben, Fehler wird gemerkt
        status = kalender.abrufen(self.con, "schule", laden=lambda url: b"kaputt")
        self.assertIn("kein lesbarer Kalender", status["fehler"])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM kalender_termin").fetchone()[0], 2)
        # Ferien von Hand bleiben, wenn das Abo entfernt wird
        termine.ferien_anlegen(self.con, self.gob, {"von": "2026-12-21", "bis": "2027-01-02", "name": "Weihnachten"})
        kalender.abo_entfernen(self.con, "schule", None)
        self.assertEqual([z[0] for z in self.con.execute("SELECT name FROM ferien WHERE aktiv = 1")], ["Weihnachten"])

    @unittest.skipIf(kalender.icalendar is None, "Pakete fehlen")
    def test_dienstkalender_nur_fuer_die_eigene_lehrkraft(self):
        with db.transaktion(self.con):
            self.con.execute("INSERT INTO kalender_abo (art, lehrkraft_id, url) VALUES ('dienst', ?, 'https://o.example/x.ics')",
                             (self.gob["id"],))
        kalender.abrufen(self.con, "dienst", self.gob["id"], laden=lambda url: DIENST)
        von, bis = datetime.date(2026, 11, 2), datetime.date(2026, 11, 15)
        meins = kalender.eintraege(self.con, self.gob, von, bis)
        self.assertIn(("dienst", "2026-11-02", "14:00", "Lehrerkonferenz"),
                      [(e["art"], e["datum"], e.get("zeit"), e["titel"]) for e in meins])
        self.assertFalse([e for e in kalender.eintraege(self.con, self.scu, von, bis) if e["art"] == "dienst"])
        self.assertTrue(kalender.abo_status(self.con, "dienst", self.gob["id"])["adresse"].startswith("https://o.example/"))
        self.assertNotIn("x.ics", json.dumps(kalender.abo_status(self.con, "dienst", self.gob["id"])))   # Link bleibt geheim
        # faellig erst nach 30 Minuten
        self.assertEqual(kalender.faellige_abrufen(self.con, laden=lambda url: DIENST), 0)
        self.zeit = "2026-11-03T08:01:00"
        self.assertEqual(kalender.faellige_abrufen(self.con, laden=lambda url: DIENST), 1)

    def test_kalender_besprechung_meilenstein_projekttag(self):
        termine.buchen(self.con, self.klima, "lehrkraft", "gob", self.regel, "2026-11-10", "08:45")
        self.team(self.klima, aktion="meilenstein_neu", woche="2026-11-09", titel="Pflichtenheft")
        liste = kalender.eintraege(self.con, self.gob, datetime.date(2026, 11, 2), datetime.date(2026, 11, 15))
        kurz = [(e["art"], e["datum"], e["titel"]) for e in liste]
        self.assertIn(("besprechung", "2026-11-10", "Klimaanlage"), kurz)
        self.assertIn(("meilenstein", "2026-11-10", "Pflichtenheft"), kurz)   # am Projekttag der Woche
        tag = [e for e in liste if e["art"] == "projekttag" and e["datum"] == "2026-11-03"][0]
        self.assertEqual(tag["fehlen"], ["Hubtisch", "Klimaanlage"])           # Buchungsschluss war gestern
        self.assertEqual([e for e in liste if e["art"] == "projekttag" and e["datum"] == "2026-11-10"][0]["fehlen"], [])

    def test_cockpit(self):
        ph = sheet.lesen(self.con, self.klima)["phasen"][1]["id"]
        aid = self.team(self.klima, aktion="aufgabe_neu", phase_id=ph, titel="Lüfter auslegen")["aufgabe_id"]
        lena = sheet.lesen(self.con, self.klima)["mitglieder"][0]["id"]
        self.team(self.klima, aktion="plan", aufgabe_id=aid, wochen=["2026-10-26", "2026-11-02"], wert=True)
        self.team(self.klima, aktion="ampel", aufgabe_id=aid, woche="2026-10-26", ampel="g")
        self.team(self.klima, aktion="ampel", aufgabe_id=aid, woche="2026-11-02", ampel="r", problem="Lüfter zu laut",
                  massnahme="anderen Lüfter suchen", verantwortlich_id=lena)
        termine.buchen(self.con, self.klima, "lehrkraft", "gob", self.regel, "2026-11-03", "09:00")
        c = cockpit.cockpit(self.con, self.gob)
        self.assertEqual([h["titel"] for h in c["heute"]], ["Klimaanlage"])
        self.assertIn("Änderungen", c["heute"][0]["text"])
        self.assertEqual(c["blick"][0]["art"], "rote_ampel")
        self.assertIn("Lüfter zu laut", c["blick"][0]["text"])
        self.assertIn("termin_fehlt", [b["art"] for b in c["blick"] if b["titel"] == "Hubtisch"])
        self.assertIn(("Hubtisch", "mitglieder"), [(e["titel"], e["art"]) for e in c["erledigen"]])
        self.assertIn(("Klimaanlage", "basisplan"), [(e["titel"], e["art"]) for e in c["erledigen"]])
        k = {x["titel"]: x for x in c["karten"]}["Klimaanlage"]
        self.assertEqual(k["ampel"], {"woche": "2026-11-02", "ampel": "r"})
        self.assertEqual([v["ampel"] for v in k["verlauf"]][-2:], ["g", "r"])
        self.assertEqual((k["aufgaben"] >= 1, k["erledigt"]), (True, 0))
        self.assertEqual(k["termin"], {"datum": "2026-11-03", "uhrzeit": "09:00"})
        self.assertGreaterEqual(k["seit_gestern"], 4)
        self.assertEqual([x["titel"] for x in c["karten"]][0], "Klimaanlage")   # mit Handlungsbedarf vorne
        self.assertNotIn("Förderband", [x["titel"] for x in c["karten"]])      # fremdes Projekt
        self.assertEqual(cockpit.cockpit(self.con, self.gob, "bsmt 22a")["karten"], [])
        # die rote Ampel sieht nur die Lehrkraft
        team = server._team_termine(self.con, self.klima)["warnungen"]
        self.assertNotIn("rote_ampel", [w["art"] for w in team])

    def test_aktivitaeten_seitenweise(self):
        ph = sheet.lesen(self.con, self.klima)["phasen"][1]["id"]
        for i in range(5):
            self.team(self.klima, aktion="aufgabe_neu", phase_id=ph, titel="Aufgabe %d" % i)
        a = cockpit.aktivitaeten(self.con, self.gob, anzahl=3)
        self.assertEqual([e["daten"]["titel"] for e in a["ereignisse"]], ["Aufgabe 4", "Aufgabe 3", "Aufgabe 2"])
        b = cockpit.aktivitaeten(self.con, self.gob, vor=a["weiter"], anzahl=3)
        self.assertEqual(b["ereignisse"][0]["daten"]["titel"], "Aufgabe 1")
        nur_team = cockpit.aktivitaeten(self.con, self.gob, wer_art="team")["ereignisse"]
        self.assertTrue(nur_team and all(e["wer_art"] == "team" for e in nur_team))
        self.assertEqual(cockpit.aktivitaeten(self.con, self.scu, projekt_id=self.klima)["ereignisse"][0]["projekt"], "Förderband")


if __name__ == "__main__":
    unittest.main()
