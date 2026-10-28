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
WICHTIG = {"rote_ampel": 0, "termin_fehlt": 1, "nicht_aktualisiert": 2, "auftrag_ueberfaellig": 3, "endtermin": 4}
VERLAUF_WOCHEN = 10


def gesamt_je_woche(con, pid):
    """Gesamtstatus je Woche wie im Sheet: die schlechteste Ampel aller nicht verworfenen Aufgaben."""
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


def aktivitaeten(con, konto, projekt_id=None, wer_art=None, vor=None, anzahl=100):
    """Chronik aller Ereignisse in den betreuten, laufenden Projekten, neueste zuerst, seitenweise (vor = Ereignis-Id)."""
    projekte = {p["id"]: p["titel"] for p in kalender.meine_projekte(con, konto)}
    ids = [projekt_id] if projekt_id in projekte else list(projekte)
    if not ids:
        return {"ereignisse": [], "projekte": [], "weiter": None}
    sql = "SELECT * FROM ereignis WHERE projekt_id IN (%s)" % ",".join("?" * len(ids))
    werte = list(ids)
    if wer_art in ("team", "lehrkraft", "system"):
        sql += " AND wer_art = ?"
        werte.append(wer_art)
    if vor:
        sql += " AND id < ?"
        werte.append(int(vor))
    zeilen = con.execute(sql + " ORDER BY id DESC LIMIT ?", werte + [anzahl + 1]).fetchall()
    return {
        "ereignisse": [{"id": e["id"], "zeit": e["zeit"], "projekt_id": e["projekt_id"], "projekt": projekte[e["projekt_id"]],
                        "wer_art": e["wer_art"], "wer": e["wer"], "art": e["art"], "daten": json.loads(e["daten"])}
                       for e in zeilen[:anzahl]],
        "projekte": [{"id": i, "titel": t} for i, t in sorted(projekte.items(), key=lambda x: x[1])],
        "weiter": zeilen[anzahl - 1]["id"] if len(zeilen) > anzahl else None,
    }
