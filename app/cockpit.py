"""Cockpit (Startseite der Lehrkraft) und Aktivitaeten, ohne KI aus den Daten berechnet.

Cockpit: links der Handlungsbedarf (Heute: Besprechungen des Tages; Jetzt erledigen: was an der Einrichtung fehlt;
Im Blick behalten: Warnungen aller Teams), rechts die naechsten zwei Wochen und je Team eine Projektkarte (Ampel,
Verlauf, Fortschritt, naechster Meilenstein, Termin, "seit gestern"). Persoenlich: nur Projekte, die man betreut.
"""
import datetime
import json

from . import db, kalender, termine
from .projekte import montag

TAG = datetime.timedelta(days=1)
RANG = {"g": 1, "y": 2, "r": 3}
# Aenderungen am Tracking-Sheet (fuer "seit der letzten Besprechung")
SHEET = ("aufgabe_neu", "titel", "verantwortlich", "verworfen", "wiederhergestellt", "reihenfolge", "plan", "ende", "ampel",
         "erledigt", "nicht_erledigt", "meilenstein_neu", "meilenstein_geaendert", "meilenstein_verworfen", "meilenstein_zurueck")
WICHTIG = {"rote_ampel": 0, "termin_fehlt": 1, "nicht_aktualisiert": 2, "rueckgabe_ueberfaellig": 3, "anfrage_wartet": 4,
           "auftrag_ueberfaellig": 5, "listen_warten": 6, "endtermin": 7}
NAMEN = {"rueckfrage": "Rückfrage", "ausleihe": "Ausleihe", "abnahme": "Abnahme"}
VERLAUF_WOCHEN = 10


def gesamt_je_woche(con, pid):
    """Gesamtstatus je Woche wie im Sheet: die schlechteste Ampel aller nicht verworfenen Tätigkeiten."""
    gesamt = {}
    for z in con.execute("SELECT z.woche, z.ampel FROM zelle z JOIN aufgabe a ON a.id = z.aufgabe_id "
                         "WHERE a.projekt_id = ? AND a.verworfen = 0 AND z.ampel IS NOT NULL", (pid,)):
        if RANG[z["ampel"]] > RANG.get(gesamt.get(z["woche"]), 0):
            gesamt[z["woche"]] = z["ampel"]
    return gesamt


def _zahl(n, einzahl, mehrzahl):
    return "%d %s" % (n, einzahl if n == 1 else mehrzahl)


def karte(con, p, heute):
    pid = p["id"]
    diese = montag(heute)
    gesamt = gesamt_je_woche(con, pid)
    wochen = [(diese - 7 * i * TAG).isoformat() for i in reversed(range(VERLAUF_WOCHEN))]
    verlauf = [{"woche": w, "ampel": gesamt.get(w)} for w in wochen if w >= p["start"]]
    bisher = sorted(w for w in gesamt if w <= diese.isoformat())
    ampel = {"woche": bisher[-1], "ampel": gesamt[bisher[-1]]} if bisher else None
    anzahl, erledigt = con.execute("SELECT COUNT(*), COUNT(erledigt) FROM aufgabe WHERE projekt_id = ? AND verworfen = 0",
                                   (pid,)).fetchone()
    ms = con.execute("SELECT * FROM meilenstein WHERE projekt_id = ? AND verworfen = 0 AND woche >= ? ORDER BY woche, id LIMIT 1",
                     (pid, diese.isoformat())).fetchone()
    termin = con.execute("SELECT * FROM buchung WHERE projekt_id = ? AND aktiv = 1 AND datum >= ? ORDER BY datum, uhrzeit LIMIT 1",
                         (pid, heute.isoformat())).fetchone()
    seit = dict(con.execute("SELECT art, COUNT(*) FROM ereignis WHERE projekt_id = ? AND wer_art = 'team' AND zeit >= ? GROUP BY art",
                            (pid, (heute - TAG).isoformat())).fetchall())
    warnungen = sorted((w for w in termine.warnungen(con, pid) if w["stufe"] != "hinweis"),
                       key=lambda w: WICHTIG.get(w["art"], 9))
    return {
        "id": pid, "titel": p["titel"], "klasse": p["klasse"], "ampel": ampel, "verlauf": verlauf,
        "aufgaben": anzahl, "erledigt": erledigt,
        "meilenstein": {"titel": ms["titel"], "woche": ms["woche"]} if ms else None,
        "termin": {"datum": termin["datum"], "uhrzeit": termin["uhrzeit"]} if termin else None,
        "seit_gestern": sum(seit.values()), "warnungen": warnungen,
    }


def _seit_letzter_besprechung(con, pid, heute):
    """Kurztext fuer "Heute": Aenderungen am Sheet seit der letzten Besprechung (oder seit Projektbeginn)."""
    letzte = con.execute("SELECT datum, uhrzeit FROM buchung WHERE projekt_id = ? AND aktiv = 1 AND datum < ? "
                         "ORDER BY datum DESC, uhrzeit DESC LIMIT 1", (pid, heute.isoformat())).fetchone()
    seit = letzte["datum"] + "T" + letzte["uhrzeit"] if letzte else "0000"
    n = con.execute("SELECT COUNT(*) FROM ereignis WHERE projekt_id = ? AND wer_art = 'team' AND zeit >= ? AND art IN (%s)"
                    % ",".join("?" * len(SHEET)), [pid, seit] + list(SHEET)).fetchone()[0]
    wann = "seit der letzten Besprechung" if letzte else "bisher"
    return ("Raster %s nicht geändert" % wann) if n == 0 else "%s %s" % (_zahl(n, "Änderung", "Änderungen"), wann)


def cockpit(con, konto, klasse=None):
    jetzt = db.jetzt()
    heute = datetime.date.fromisoformat(jetzt[:10])
    alle = kalender.meine_projekte(con, konto)
    projekte = [p for p in alle if not klasse or p["klasse"].strip().lower() == klasse.strip().lower()]
    karten, heute_liste, erledigen, blick = [], [], [], []
    ohne_regel = set()
    for p in projekte:
        k = karte(con, p, heute)
        karten.append(k)
        if k["termin"] and k["termin"]["datum"] == heute.isoformat():
            heute_liste.append({"uhrzeit": k["termin"]["uhrzeit"], "projekt_id": p["id"], "titel": p["titel"],
                                "text": _seit_letzter_besprechung(con, p["id"], heute),
                                "warnungen": len(k["warnungen"])})
        for w in k["warnungen"]:
            blick.append({"projekt_id": p["id"], "titel": p["titel"], "art": w["art"], "text": w["text"]})
        from . import anfragen   # hier, weil anfragen ueber besprechung wieder cockpit braucht
        for a in con.execute("SELECT * FROM anfrage WHERE projekt_id = ? AND stand != 'erledigt' ORDER BY id", (p["id"],)).fetchall():
            neu = anfragen._ungelesen(con, a, "l%d" % konto["id"], konto["kuerzel"])
            if (a["stand"] == "offen" and a["art"] != "bestellung") or (neu and a["stand"] != "offen"):
                erledigen.append({"projekt_id": p["id"], "titel": p["titel"], "art": "anfrage", "anfrage_id": a["id"],
                                  "text": "%s: %s%s" % (anfragen.NAMEN[a["art"]], a["titel"], " · neue Nachricht" if a["stand"] != "offen" else "")})
        for l in con.execute("SELECT l.* FROM bestellliste l WHERE l.projekt_id = ? AND l.eingereicht IS NOT NULL AND l.geprueft IS NULL",
                             (p["id"],)):
            erledigen.append({"projekt_id": p["id"], "titel": p["titel"], "art": "liste", "liste_id": l["id"],
                              "text": "Bestellliste prüfen (eingereicht %s)" % l["eingereicht"][8:10] + "." + l["eingereicht"][5:7] + "."})
        if not con.execute("SELECT 1 FROM mitglied WHERE projekt_id = ? AND aktiv = 1", (p["id"],)).fetchone():
            erledigen.append({"projekt_id": p["id"], "titel": p["titel"], "art": "mitglieder", "text": "Teammitglieder eintragen"})
        if not termine.projekt_regeln(con, p):
            ohne_regel.add(p["klasse"].strip())
        elif (not con.execute("SELECT 1 FROM version WHERE projekt_id = ? AND art = 'basisplan'", (p["id"],)).fetchone()
              and p["start"] <= (heute - 14 * TAG).isoformat()
              and con.execute("SELECT 1 FROM zelle z JOIN aufgabe a ON a.id = z.aufgabe_id WHERE a.projekt_id = ? AND z.plan = 1",
                              (p["id"],)).fetchone()):
            erledigen.append({"projekt_id": p["id"], "titel": p["titel"], "art": "basisplan",
                              "text": "Basisplan festlegen (das Team plant schon)"})
    for kl in sorted(ohne_regel):
        erledigen.insert(0, {"projekt_id": None, "titel": kl, "art": "projektzeit",
                             "text": "Keine Projektzeit für diese Klasse: es gibt keine Besprechungstermine"})
    heute_liste.sort(key=lambda h: h["uhrzeit"])
    blick.sort(key=lambda b: (WICHTIG.get(b["art"], 9), b["titel"]))
    # vorne, wer am dringendsten Handlungsbedarf hat (rote Ampel vor fehlendem Termin ...), dann wer mehr hat
    karten.sort(key=lambda k: (min([WICHTIG.get(w["art"], 9) for w in k["warnungen"]] or [99]), -len(k["warnungen"]),
                               k["klasse"], k["titel"]))
    von = montag(heute)
    return {
        "jetzt": jetzt, "heute": heute_liste, "erledigen": erledigen, "blick": blick, "karten": karten,
        "kalender": kalender.eintraege(con, konto, von, von + 13 * TAG, klasse), "von": von.isoformat(),
        "klassen": sorted({p["klasse"] for p in alle}), "dienst": kalender.abo_status(con, "dienst", konto["id"]),
    }


# --- Aktivitaeten: je Team zusammengefasst ---

BEREICHE = {
    "raster": SHEET + ("version",),
    "besprechung": ("termin_gebucht", "termin_storniert", "termin_entfallen", "vorbereitung", "eintrag_neu", "eintrag_erledigt",
                    "eintrag_offen", "eintrag_verworfen", "eintrag_umgewandelt", "besprechung_abgeschlossen"),
    "anfragen": ("anfrage_neu", "anfrage_status", "anfrage_nachricht", "sonderfenster", "position_neu", "position_geaendert",
                 "position_gestrichen", "position_zurueck", "liste_eingereicht", "position_entschieden", "position_status"),
}
STANDARD_BEREICHE = ("raster", "anfragen")
ZUSAMMEN = datetime.timedelta(minutes=15)   # gleiche Aenderung an derselben Tätigkeit innerhalb dieser Zeit: eine Zeile
RANG_HINWEIS = {"ampel_r": 0, "nachricht": 1, "anfrage": 2, "ampel_y": 3, "verschoben": 4, "liste": 5, "entfallen": 6, "meilenstein": 7}


def bereich(art):
    for name, arten in BEREICHE.items():
        if art in arten:
            return name
    return "sonstiges"


def aktivitaeten_seit(con, konto, zeitraum):
    """Beginn des Zeitraums. 'besuch' = seit dem letzten Besuch: Ein Besuch zaehlt als neu, wenn der vorige mehr als
    30 Minuten her ist (so zeigt Neuladen nicht ploetzlich nichts mehr an)."""
    jetzt = datetime.datetime.fromisoformat(db.jetzt())
    if zeitraum == "heute":
        return jetzt.replace(hour=0, minute=0, second=0).isoformat()
    if zeitraum == "woche":
        return datetime.datetime.combine(montag(jetzt.date()), datetime.time()).isoformat()
    if zeitraum == "30":
        return (jetzt - datetime.timedelta(days=30)).isoformat()
    zuletzt = db.einstellung(con, "akt_zuletzt:%d" % konto["id"])
    davor = db.einstellung(con, "akt_davor:%d" % konto["id"]) or (jetzt - datetime.timedelta(days=1)).isoformat()
    with db.transaktion(con):
        if zuletzt is not None and jetzt - datetime.datetime.fromisoformat(zuletzt) > datetime.timedelta(minutes=30):
            davor = zuletzt
            db.einstellung_setzen(con, "akt_davor:%d" % konto["id"], davor)
        elif zuletzt is None:
            db.einstellung_setzen(con, "akt_davor:%d" % konto["id"], davor)
        db.einstellung_setzen(con, "akt_zuletzt:%d" % konto["id"], jetzt.isoformat())
    return davor


def _verdichten(ereignisse):
    """Serien zusammenfassen: Planaenderungen derselben Tätigkeit (gleiche Richtung), Endtermin- und Ampel-Aenderungen
    derselben Tätigkeit kurz hintereinander werden eine Zeile. Erwartet aelteste zuerst."""
    liste = []
    for e in ereignisse:
        d = e["daten"]
        v = liste[-1] if liste else None
        gleich = (v is not None and v["art"] == e["art"] and d.get("aufgabe_id") and v["daten"].get("aufgabe_id") == d.get("aufgabe_id")
                  and v["wer_art"] == e["wer_art"]
                  and datetime.datetime.fromisoformat(e["zeit"]) - datetime.datetime.fromisoformat(v["zeit"]) <= ZUSAMMEN)
        if gleich and e["art"] == "plan" and v["daten"].get("wert") == d.get("wert"):
            v["daten"]["wochen"] = sorted(set(v["daten"]["wochen"]) | set(d["wochen"]))
        elif gleich and e["art"] == "ende":
            v["daten"]["woche"] = d.get("woche")      # erster alter Wert bleibt, letzter neuer Wert gilt
        elif gleich and e["art"] == "ampel" and v["daten"].get("woche") == d.get("woche"):
            v["daten"].update({k: d.get(k) for k in ("ampel", "problem", "massnahme")})
        else:
            liste.append(dict(e, daten=dict(d)))
            continue
        v["zeit"] = e["zeit"]
        v["anzahl"] = v.get("anzahl", 1) + 1
    return liste


def _hinweise(ereignisse):
    """Was in der Karte oben steht: rote/gelbe Ampeln, neue Anfragen, Nachrichten des Teams, verschobene Endtermine,
    Meilensteine, eingereichte Listen, entfallene Termine, abgeschlossene Besprechungen."""
    hinweise, nachrichten = [], {}
    for e in ereignisse:
        d, art = e["daten"], e["art"]
        if art == "ampel" and d.get("ampel") in ("y", "r"):
            hinweise.append({"art": "ampel_" + d["ampel"], "text": "%s in %s: %s%s" % ("Rot" if d["ampel"] == "r" else "Gelb",
                             termine.kw_text(d["woche"]), d["titel"], " – " + d["problem"] if d.get("problem") else ""),
                             "woche": d.get("woche")})
        elif art == "anfrage_neu":
            hinweise.append({"art": "anfrage", "text": "Neue Anfrage: " + d.get("titel", ""), "anfrage_id": d.get("anfrage_id")})
        elif art == "anfrage_nachricht" and e["wer_art"] == "team":
            n = nachrichten.setdefault(d.get("anfrage_id"), {"titel": d.get("titel", ""), "anzahl": 0})
            n["anzahl"] += 1
        elif art == "ende" and d.get("alt") and d.get("woche") and d["woche"] > d["alt"]:
            hinweise.append({"art": "verschoben", "text": "Endtermin verschoben: " + d["titel"], "alt": d["alt"], "neu": d["woche"]})
        elif art in ("meilenstein_neu", "meilenstein_geaendert"):
            hinweise.append({"art": "meilenstein", "text": "Meilenstein: " + d["titel"], "woche": d.get("woche")})
        elif art == "liste_eingereicht":
            hinweise.append({"art": "liste", "text": "Bestellliste eingereicht (%s Positionen)" % d.get("positionen")})
        elif art == "termin_entfallen":
            hinweise.append({"art": "entfallen", "text": "Termin entfällt: " + d.get("grund", "")})
        elif art == "besprechung_abgeschlossen":
            hinweise.append({"art": "besprechung", "text": "Besprechung abgeschlossen (%s Ergebnisse)" % d.get("ergebnisse")})
    for aid, n in nachrichten.items():
        hinweise.append({"art": "nachricht", "anfrage_id": aid,
                         "text": "%d %s vom Team: %s" % (n["anzahl"], "Nachricht" if n["anzahl"] == 1 else "Nachrichten", n["titel"])})
    hinweise.sort(key=lambda h: RANG_HINWEIS.get(h["art"], 9))
    return hinweise


def aktivitaeten(con, konto, zeitraum="besuch", bereiche=None, klasse=None):
    """Je betreutem Projekt: Hinweise (Wichtiges), Zahlen je Bereich und die verdichteten Einzelheiten (neueste zuerst)
    seit dem Beginn des Zeitraums. Projekte ohne sichtbare Aenderung kommen gesammelt in 'ruhig'."""
    seit = aktivitaeten_seit(con, konto, zeitraum)
    bereiche = [b for b in (bereiche or STANDARD_BEREICHE) if b in BEREICHE or b == "sonstiges"]
    diese = montag(datetime.date.fromisoformat(db.jetzt()[:10])).isoformat()
    karten, ruhig = [], []
    for p in kalender.meine_projekte(con, konto, klasse):
        alle = [{"id": e["id"], "zeit": e["zeit"], "wer_art": e["wer_art"], "wer": e["wer"], "art": e["art"], "daten": json.loads(e["daten"])}
                for e in con.execute("SELECT * FROM ereignis WHERE projekt_id = ? AND zeit > ? ORDER BY id", (p["id"], seit))]
        sichtbar = [e for e in alle if bereich(e["art"]) in bereiche]
        if not sichtbar:
            ruhig.append({"id": p["id"], "titel": p["titel"], "klasse": p["klasse"], "ausgeblendet": len(alle)})
            continue
        zahlen = {}
        for e in sichtbar:
            zahlen[bereich(e["art"])] = zahlen.get(bereich(e["art"]), 0) + 1
        gesamt = gesamt_je_woche(con, p["id"])
        bisher = sorted(w for w in gesamt if w <= diese)
        karten.append({"id": p["id"], "titel": p["titel"], "klasse": p["klasse"], "ampel": gesamt[bisher[-1]] if bisher else None,
                       "hinweise": _hinweise(sichtbar), "zahlen": zahlen,
                       "erledigt": sum(1 for e in sichtbar if e["art"] == "erledigt"),
                       "ereignisse": list(reversed(_verdichten(sichtbar))), "ausgeblendet": len(alle) - len(sichtbar)})
    karten.sort(key=lambda k: (min([RANG_HINWEIS.get(h["art"], 9) for h in k["hinweise"]] or [10]), -len(k["ereignisse"]), k["titel"]))
    return {"seit": seit, "zeitraum": zeitraum, "bereiche": bereiche, "karten": karten, "ruhig": ruhig,
            "klassen": sorted({p["klasse"] for p in kalender.meine_projekte(con, konto)})}
