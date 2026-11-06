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
    def setUp(self):
        super().setUp()
        with db.transaktion(self.con):   # Teamteaching: Herr Schu betreut die Klimaanlage mit
            self.con.execute("INSERT INTO projekt_lehrkraft (projekt_id, lehrkraft_id) VALUES (?, ?)", (self.klima, self.scu["id"]))

    def eingang(self, konto, filter_="aktiv"):
        return {v["id"]: v for v in anfragen.vorgaenge_lehrkraft(self.con, konto, filter_)}

    def team_liste(self):
        return {v["id"]: v for v in anfragen.vorgaenge_team(self.con, self.klima)}

    def lk(self, aid, konto=None, **d):
        anfragen.bearbeiten(self.con, self.klima, konto or self.gob, dict(d, anfrage_id=aid))

    def test_gespraech_status_zustaendig_ungelesen(self):
        aid = anfragen.anlegen(self.con, self.klima, {"art": "rueckfrage", "titel": "Dürfen wir 24 V nehmen?", "text": "Lüfter gibt es nur in 24 V."})
        e = self.eingang(self.gob)[aid]
        self.assertEqual((e["stand"], e["ungelesen"], e["zustaendig"]), ("offen", True, None))
        self.assertFalse(self.team_liste()[aid]["ungelesen"])
        anfragen.vorgang(self.con, self.klima, aid, self.gob)   # gelesen
        self.assertFalse(self.eingang(self.gob)[aid]["ungelesen"])
        self.assertTrue(self.eingang(self.scu)[aid]["ungelesen"])
        # interne Notiz: nur fuer Lehrkraefte, aendert nichts am Status
        anfragen.nachricht(self.con, self.klima, aid, "lehrkraft", {"text": "Netzteil reicht?", "intern": True}, self.gob)
        self.assertEqual(self.eingang(self.gob)[aid]["stand"], "offen")
        self.assertFalse(self.team_liste()[aid]["ungelesen"])
        self.assertNotIn("Netzteil reicht?", str(anfragen.vorgang(self.con, self.klima, aid)))
        self.assertIn("Netzteil reicht?", str(anfragen.vorgang(self.con, self.klima, aid, self.scu)))
        # Antwort: in Bearbeitung, wer antwortet, uebernimmt
        anfragen.nachricht(self.con, self.klima, aid, "lehrkraft", {"text": "Ja, aber mit Sicherung."}, self.gob)
        e = self.eingang(self.gob)[aid]
        self.assertEqual((e["stand"], e["zustaendig"]), ("bearbeitung", "GOB"))
        self.assertTrue(self.team_liste()[aid]["ungelesen"])
        self.assertEqual(list(self.eingang(self.gob, "meine")), [aid])
        self.assertEqual(list(self.eingang(self.scu, "meine")), [])
        anfragen.vorgang(self.con, self.klima, aid)   # das Team liest
        self.assertFalse(self.team_liste()[aid]["ungelesen"])
        anfragen.nachricht(self.con, self.klima, aid, "team", {"text": "Welche Sicherung?"})
        self.assertTrue(self.eingang(self.gob)[aid]["ungelesen"])
        # erledigt, dann schreibt das Team wieder: in Bearbeitung bei derselben Lehrkraft
        self.lk(aid, aktion="stand", stand="erledigt")
        self.assertNotIn(aid, self.eingang(self.gob))
        self.assertIn(aid, self.eingang(self.gob, "erledigt"))
        anfragen.nachricht(self.con, self.klima, aid, "team", {"text": "Doch noch eine Frage."})
        e = self.eingang(self.gob)[aid]
        self.assertEqual((e["stand"], e["zustaendig"]), ("bearbeitung", "GOB"))
        was = [n["daten"].get("was") for n in anfragen.vorgang(self.con, self.klima, aid, self.gob)["verlauf"] if n["art"] == "ereignis"]
        self.assertEqual(was, ["zustaendig", "stand", "stand", "stand"])
        # uebernehmen durch Herrn Schu
        self.lk(aid, self.scu, aktion="uebernehmen")
        self.assertEqual(self.eingang(self.scu, "meine")[aid]["zustaendig"], "SCU")
        with self.assertRaises(projekte.ProjektFehler):   # Team kann nur Offenes zurueckziehen
            anfragen.team_aendern(self.con, self.klima, {"aktion": "zurueckziehen", "anfrage_id": aid})

    def test_zuweisen_an_betreuende_lehrkraft(self):
        aid = anfragen.anlegen(self.con, self.klima, {"art": "rueckfrage", "titel": "Welcher Sensor?"})
        anfragen.vorgang(self.con, self.klima, aid, self.scu)   # Schu hat es schon gelesen
        self.lk(aid, aktion="zuweisen", lehrkraft_id=self.scu["id"])
        e = self.eingang(self.scu)[aid]
        self.assertEqual((e["stand"], e["zustaendig"], e["ungelesen"]), ("bearbeitung", "SCU", True))   # zugewiesen: ungelesen
        self.assertFalse(self.eingang(self.gob)[aid]["ungelesen"])
        v = anfragen.vorgang(self.con, self.klima, aid)   # Team sieht den Namen
        self.assertEqual(v["zustaendig"]["name"], self.scu["name"])
        self.assertEqual(self.team_liste()[aid]["zustaendig_name"], self.scu["name"])
        z = [n["daten"] for n in anfragen.vorgang(self.con, self.klima, aid, self.gob)["verlauf"] if n["daten"].get("was") == "zustaendig"][-1]
        self.assertEqual((z["kuerzel"], z["von"]), ("SCU", "GOB"))
        # nur Lehrkraefte, die das Projekt betreuen
        with db.transaktion(self.con):
            fremd = konten.anlegen(self.con, "fre", "Frau Fremd", "lehrkraft", "geheim123")
        with self.assertRaises(projekte.ProjektFehler):
            self.lk(aid, aktion="zuweisen", lehrkraft_id=fremd["id"])
        # Zustaendigkeit wegnehmen: wieder neu
        self.lk(aid, aktion="zuweisen", lehrkraft_id=None)
        e = self.eingang(self.gob)[aid]
        self.assertEqual((e["stand"], e["zustaendig"]), ("offen", None))
        # Filter: Knoepfe je Stand und "nur meine", dazu Zahlen und Betreuer
        self.lk(aid, aktion="zuweisen", lehrkraft_id=self.gob["id"])
        r = anfragen.eingang(self.con, self.gob, staende=["offen"])
        self.assertEqual(([v["id"] for v in r["vorgaenge"]], r["zahlen"]), ([], {"offen": 0, "bearbeitung": 1}))
        r = anfragen.eingang(self.con, self.gob, staende=["offen", "bearbeitung"], meine=True)
        self.assertEqual([v["id"] for v in r["vorgaenge"]], [aid])
        self.assertEqual(anfragen.eingang(self.con, self.scu, staende=["bearbeitung"], meine=True)["vorgaenge"], [])
        self.assertEqual({b["kuerzel"] for b in r["betreuer"][str(self.klima)]}, {"GOB", "SCU"})

    def test_zaehler_zum_melden(self):
        aid = anfragen.anlegen(self.con, self.klima, {"art": "rueckfrage", "titel": "Kabelquerschnitt?", "text": "Reichen 0,75 mm²?"})
        z = anfragen.zaehler(self.con, self.gob)
        self.assertEqual((z["ungelesen"], z["offen"]), (1, 1))
        self.assertEqual((z["neu"][0]["id"], z["neu"][0]["projekt"], z["neu"][0]["text"]), (aid, "Klimaanlage", "Reichen 0,75 mm²?"))
        nid = z["neu"][0]["nid"]
        anfragen.nachricht(self.con, self.klima, aid, "team", {"text": "Oder lieber 1,5?"})
        z = anfragen.zaehler(self.con, self.gob)
        self.assertGreater(z["neu"][0]["nid"], nid)   # neuer Eintrag: wird wieder gemeldet
        self.assertEqual(z["neu"][0]["text"], "Oder lieber 1,5?")
        self.assertEqual(anfragen.team_zaehler(self.con, self.klima), {"ungelesen": 0, "neu": [], "bestellung": 0})
        # interne Notiz meldet das Team nicht, die Antwort schon
        anfragen.nachricht(self.con, self.klima, aid, "lehrkraft", {"text": "Frag mal Schu", "intern": True}, self.gob)
        self.assertEqual(anfragen.team_zaehler(self.con, self.klima)["ungelesen"], 0)
        anfragen.nachricht(self.con, self.klima, aid, "lehrkraft", {"text": "1,5 mm²."}, self.gob)
        t = anfragen.team_zaehler(self.con, self.klima)
        self.assertEqual((t["ungelesen"], t["neu"][0]["text"]), (1, "1,5 mm²."))
        self.assertEqual(anfragen.zaehler(self.con, self.gob)["ungelesen"], 0)   # eigene Antwort ist gelesen

    def test_rueckfrage_ueber_die_tafel_geklaert(self):
        aid = anfragen.anlegen(self.con, self.klima, {"art": "rueckfrage", "titel": "Dürfen wir 24 V nehmen?", "in_besprechung": True})
        frage = [z for z in tafel.lesen(self.con, self.klima)["postits"] if z["text"] == "Dürfen wir 24 V nehmen?"][0]
        tafel.aendern(self.con, self.klima, "gob", {"aktion": "erledigt", "key": frage["key"]})
        v = anfragen.vorgang(self.con, self.klima, aid, self.gob)
        self.assertEqual((v["stand"], v["status"]), ("erledigt", "beantwortet"))
        self.assertIn("geklaert", [n["daten"].get("was") for n in v["verlauf"]])

    def test_ausleihe_rueckgabe_ueberfaellig(self):
        aid = anfragen.anlegen(self.con, self.klima, {"art": "ausleihe", "titel": "Anemometer", "menge": "1", "von": "2026-11-03", "bis": "2026-11-10"})
        with self.assertRaises(projekte.ProjektFehler):
            anfragen.anlegen(self.con, self.klima, {"art": "ausleihe", "titel": "x", "von": "2026-11-10", "bis": "2026-11-03"})
        self.lk(aid, aktion="status", status="bereitgelegt")
        self.assertEqual(self.eingang(self.gob)[aid]["stand"], "bearbeitung")
        self.lk(aid, aktion="status", status="ausgegeben")
        self.zeit = "2026-11-11T09:00:00"
        self.assertIn("rueckgabe_ueberfaellig", [w["art"] for w in termine.warnungen(self.con, self.klima)])
        self.lk(aid, aktion="status", status="zurueck")
        self.assertNotIn("rueckgabe_ueberfaellig", [w["art"] for w in termine.warnungen(self.con, self.klima)])
        self.assertEqual(anfragen.vorgang(self.con, self.klima, aid, self.gob)["stand"], "erledigt")

    def test_abnahme_im_verlauf_der_aufgabe(self):
        ph = sheet.lesen(self.con, self.klima)["phasen"][2]["id"]
        auf = sheet.aendern(self.con, self.klima, "team", "Team", {"aktion": "aufgabe_neu", "phase_id": ph, "titel": "Verdrahten"})["aufgabe_id"]
        aid = anfragen.anlegen(self.con, self.klima, {"art": "abnahme", "titel": "Netzteil prüfen", "aufgabe_id": auf})
        with self.assertRaises(projekte.ProjektFehler):   # nachbessern braucht einen Hinweis
            self.lk(aid, aktion="status", status="nachbessern")
        self.lk(aid, aktion="status", status="nachbessern", text="PE fehlt")
        anfragen.team_aendern(self.con, self.klima, {"aktion": "erneut", "anfrage_id": aid})
        self.assertEqual(self.eingang(self.gob)[aid]["stand"], "offen")
        self.lk(aid, aktion="status", status="freigegeben")
        arten = [(e["art"], e["daten"].get("status")) for e in sheet.aufgabe_verlauf(self.con, self.klima, auf)]
        self.assertIn(("anfrage_status", "freigegeben"), arten)
        v = anfragen.vorgang(self.con, self.klima, aid)
        self.assertEqual(v["stand"], "erledigt")
        self.assertIn("PE fehlt", [n["text"] for n in v["verlauf"]])

    def test_anfrage_wartet_nur_fuer_lehrkraft(self):
        aid = anfragen.anlegen(self.con, self.klima, {"art": "rueckfrage", "titel": "Welcher Servo?"})
        self.zeit = "2026-11-03T18:00:00"
        self.assertNotIn("anfrage_wartet", [w["art"] for w in termine.warnungen(self.con, self.klima)])
        self.zeit = "2026-11-04T08:00:00"   # zwei Schultage spaeter
        self.assertIn("anfrage_wartet", [w["art"] for w in termine.warnungen(self.con, self.klima)])
        self.assertNotIn("anfrage_wartet", [w["art"] for w in server._team_termine(self.con, self.klima)["warnungen"]])
        self.assertIn("anfrage", [e["art"] for e in cockpit.cockpit(self.con, self.gob)["erledigen"]])
        anfragen.nachricht(self.con, self.klima, aid, "lehrkraft", {"text": "MG996R"}, self.gob)
        self.assertNotIn("anfrage_wartet", [w["art"] for w in termine.warnungen(self.con, self.klima)])


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
        # Einreichen legt keine Anfrage mehr an (J1); das Team sieht am Reiter, dass geprueft wurde, bis es hineinschaut
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM anfrage WHERE art = 'bestellung'").fetchone()[0], 0)
        self.assertEqual(anfragen.team_zaehler(self.con, self.klima)["bestellung"], 1)
        self.assertTrue(bestellung.team_sicht(self.con, self.klima)["eingereicht"][0]["neu"])
        bestellung.team_gesehen(self.con, self.klima)
        self.assertEqual(anfragen.team_zaehler(self.con, self.klima)["bestellung"], 1)   # die Firma-Frage zu p4 wartet noch
        self.assertEqual(bestellung.projekt_listen(self.con, self.klima)["eingereicht"][0]["verlauf"], [])
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

    def test_firma_frage_an_das_team(self):
        p = self.pos(self.klima, artikel="Aluprofil", bestellnr="", lieferant="Mechanikshop")
        q = self.pos(self.klima, artikel="Kabelbinder")
        bestellung.fenster_anlegen(self.con, self.gob, {"von": "2026-11-02", "bis": "2026-11-05T12:00", "klasse": "BSMT 22b"})
        bestellung.team_aendern(self.con, self.klima, {"aktion": "einreichen"})
        lena = self.con.execute("SELECT id FROM mitglied WHERE projekt_id = ?", (self.klima,)).fetchone()[0]
        with self.assertRaises(projekte.ProjektFehler):   # noch nicht ueber Firma
            bestellung.team_aendern(self.con, self.klima, {"aktion": "firma_antwort", "position_id": p, "ja": True, "mitglied_id": lena})
        self.entscheiden(self.klima, p, entscheidung="firma")
        self.entscheiden(self.klima, q, entscheidung="firma")
        pos = lambda: {x["id"]: x for x in bestellung.team_sicht(self.con, self.klima)["eingereicht"][0]["positionen"]}
        self.assertEqual(pos()[p]["firma_stand"], "gefragt")
        with self.assertRaises(projekte.ProjektFehler):   # erst zusagen
            bestellung.team_aendern(self.con, self.klima, {"aktion": "firma_besorgt", "position_id": p})
        with self.assertRaises(projekte.ProjektFehler):   # Ja nur mit einem Teammitglied
            bestellung.team_aendern(self.con, self.klima, {"aktion": "firma_antwort", "position_id": p, "ja": True})
        bestellung.team_aendern(self.con, self.klima, {"aktion": "firma_antwort", "position_id": p, "ja": True, "mitglied_id": lena})
        self.assertEqual((pos()[p]["firma_stand"], pos()[p]["firma_wer"]), ("zugesagt", "Lena Schmitt"))
        bestellung.team_aendern(self.con, self.klima, {"aktion": "firma_besorgt", "position_id": p, "besorgt": True})
        self.assertEqual(pos()[p]["firma_stand"], "besorgt")
        # Nein: offen zurueck an die Lehrkraft, Liste nicht mehr fertig geprueft
        bestellung.team_aendern(self.con, self.klima, {"aktion": "firma_antwort", "position_id": q, "ja": False})
        self.assertEqual((pos()[q]["entscheidung"], pos()[q]["firma_stand"]), (None, "nein"))
        self.assertIsNone(self.con.execute("SELECT geprueft FROM bestellliste").fetchone()[0])
        self.assertEqual([x for x in anfragen.vorgaenge_lehrkraft(self.con, self.gob, "alle")], [])
        # neue Entscheidung: der Firma-Vermerk verschwindet
        self.entscheiden(self.klima, q, entscheidung="bestellen")
        self.assertIsNone(pos()[q]["firma_stand"])

    def test_alte_bestell_anfrage(self):
        """Listen von vor J1 haben einen Vorgang: er erscheint nicht mehr bei den Anfragen, sein Verlauf bei der Liste."""
        p = self.pos(self.klima)
        bestellung.fenster_anlegen(self.con, self.gob, {"von": "2026-11-02", "bis": "2026-11-05T12:00", "klasse": "BSMT 22b"})
        bestellung.team_aendern(self.con, self.klima, {"aktion": "einreichen"})
        lid = self.con.execute("SELECT id FROM bestellliste").fetchone()[0]
        with db.transaktion(self.con):
            aid = self.con.execute("INSERT INTO anfrage (projekt_id, art, titel, status, erstellt, geaendert, stand, bestellliste_id) "
                                   "VALUES (?, 'bestellung', 'Liste', 'neu', ?, ?, 'offen', ?)", (self.klima, self.zeit, self.zeit, lid)).lastrowid
            anfragen.notieren(self.con, aid, "lehrkraft", "gob", art="intern", text="nur intern")
            anfragen.notieren(self.con, aid, "lehrkraft", "gob", art="nachricht", text="Bitte Datenblatt nachreichen")
        self.entscheiden(self.klima, p, entscheidung="bestellen")
        self.assertEqual(anfragen.vorgaenge_team(self.con, self.klima), [])
        self.assertEqual(anfragen.zaehler(self.con, self.gob)["ungelesen"], 0)
        team = bestellung.team_sicht(self.con, self.klima)["eingereicht"][0]["verlauf"]
        self.assertEqual([n["text"] for n in team if n["art"] != "ereignis"], ["Bitte Datenblatt nachreichen"])
        lk = bestellung.liste_lesen(self.con, self.gob, lid)["verlauf"]
        self.assertIn("nur intern", [n["text"] for n in lk])
        self.assertEqual(self.con.execute("SELECT stand FROM anfrage WHERE id = ?", (aid,)).fetchone()[0], "offen")

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



class Migration9(unittest.TestCase):
    """Umbau der Tabelle anfrage mit vorhandenen Daten (so laeuft das Update im Container)."""

    def test_altdaten(self):
        ordner = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, ordner, True)
        with mock.patch.object(db, "MIGRATIONEN", db.MIGRATIONEN[:8]):
            con = db.oeffnen(ordner)
        with db.transaktion(con):
            k = konten.anlegen(con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
        pid = projekte.anlegen(con, "gob", "Klimaanlage", "BSMT 22b", "2026-10-26", "2027-01-04", [k["id"]], [])
        with db.transaktion(con):
            con.execute("INSERT INTO anfrage (projekt_id, art, titel, status, antwort, erstellt, geaendert, geaendert_von) "
                        "VALUES (?, 'rueckfrage', '24 V?', 'beantwortet', 'Ja.', '2026-10-27T09:00:00', '2026-10-27T10:00:00', 'gob')", (pid,))
            con.execute("INSERT INTO eintrag (projekt_id, art, text, erstellt, wer_art, wer, anfrage_id) VALUES (?, 'frage', '24 V?', "
                        "'2026-10-27T09:00:00', 'team', 'Team', 1)", (pid,))
            con.execute("INSERT INTO bestellliste (projekt_id, eingereicht) VALUES (?, '2026-10-28T10:00:00')", (pid,))
        con.close()
        con = db.oeffnen(ordner)
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], len(db.MIGRATIONEN))
        a = [tuple(z) for z in con.execute("SELECT art, stand, bestellliste_id FROM anfrage ORDER BY id")]
        self.assertEqual(a, [("rueckfrage", "erledigt", None), ("bestellung", "offen", 1)])
        self.assertEqual(con.execute("SELECT text, wer FROM nachricht").fetchone()[:], ("Ja.", "gob"))
        self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(con.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertIn("anfrage", [z[2] for z in con.execute("PRAGMA foreign_key_list(eintrag)")])
        con.close()


if __name__ == "__main__":
    unittest.main()
