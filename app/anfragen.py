"""Anfragen des Teams an die Lehrkraefte des Projekts: Rueckfrage, Material ausleihen, Abnahme/Freigabe.

Das Team sieht jederzeit den Stand; jeder Statuswechsel steht mit Uhrzeit und Kuerzel im Ereignisprotokoll. Eine
Rueckfrage mit "in der Besprechung klaeren" liegt zusaetzlich als Frage auf der Tafel; wird sie dort geklaert, gilt
sie als beantwortet. Die Freigabe einer Abnahme steht im Verlauf der Aufgabe. Nichts wird geloescht.
"""
import datetime

from . import besprechung, db
from .projekte import ProjektFehler

STATUS = {
    "rueckfrage": ("neu", "beantwortet", "zurueckgezogen"),
    "ausleihe": ("neu", "bereitgelegt", "ausgegeben", "zurueck", "abgelehnt", "zurueckgezogen"),
    "abnahme": ("neu", "freigegeben", "nachbessern", "zurueckgezogen"),
}
OFFEN = {"neu", "bereitgelegt", "ausgegeben"}
NAMEN = {"rueckfrage": "Rückfrage", "ausleihe": "Ausleihe", "abnahme": "Abnahme"}


def _text(wert, feld, laenge, pflicht=True):
    wert = (wert or "").strip()
    if pflicht and not wert:
        raise ProjektFehler("Bitte %s angeben." % feld)
    if len(wert) > laenge:
        raise ProjektFehler("Der Text ist zu lang (höchstens %d Zeichen)." % laenge)
    return wert


def _datum(wert, feld):
    try:
        return datetime.date.fromisoformat(str(wert or "")[:10]).isoformat()
    except ValueError:
        raise ProjektFehler("Bitte %s angeben." % feld)


def _aufgabe(con, pid, aid):
    if aid in (None, ""):
        return None
    try:
        a = con.execute("SELECT id FROM aufgabe WHERE id = ? AND projekt_id = ?", (int(aid), pid)).fetchone()
    except (TypeError, ValueError):
        a = None
    if a is None:
        raise ProjektFehler("Diese Aufgabe gibt es nicht.")
    return a["id"]


def _dict(a, titel_aufgabe=None):
    return {"id": a["id"], "art": a["art"], "titel": a["titel"], "text": a["text"], "aufgabe_id": a["aufgabe_id"],
            "aufgabe": titel_aufgabe, "menge": a["menge"], "von": a["von"], "bis": a["bis"], "bild": a["bild"],
            "in_besprechung": bool(a["in_besprechung"]), "status": a["status"], "antwort": a["antwort"],
            "erstellt": a["erstellt"], "geaendert": a["geaendert"], "geaendert_von": a["geaendert_von"],
            "offen": a["status"] in OFFEN,
            "ueberfaellig": a["art"] == "ausleihe" and a["status"] == "ausgegeben" and bool(a["bis"])
            and a["bis"] < db.jetzt()[:10]}


def _holen(con, pid, aid):
    try:
        a = con.execute("SELECT * FROM anfrage WHERE id = ? AND projekt_id = ?", (int(aid), pid)).fetchone()
    except (TypeError, ValueError):
        a = None
    if a is None:
        raise ProjektFehler("Diese Anfrage gibt es nicht.")
    return a


def liste(con, pid):
    titel = {a["id"]: a["titel"] for a in con.execute("SELECT id, titel FROM aufgabe WHERE projekt_id = ?", (pid,))}
    zeilen = con.execute("SELECT * FROM anfrage WHERE projekt_id = ? ORDER BY id DESC", (pid,)).fetchall()
    liste_ = [_dict(a, titel.get(a["aufgabe_id"])) for a in zeilen]
    liste_.sort(key=lambda a: (not a["offen"], -a["id"]))
    return liste_


# --- Team ---

def anlegen(con, pid, d, bild=None):
    """Neue Anfrage des Teams. bild: Dateiname eines schon gespeicherten Fotos (Abnahme)."""
    art = d.get("art")
    if art not in STATUS:
        raise ProjektFehler("Unbekannte Art der Anfrage.")
    titel = _text(d.get("titel"), {"rueckfrage": "die Frage", "ausleihe": "was ihr ausleihen wollt",
                                   "abnahme": "was geprüft werden soll"}[art], 200)
    text = _text(d.get("text"), "Details", 2000, pflicht=False)
    aufgabe_id = _aufgabe(con, pid, d.get("aufgabe_id"))
    menge, von, bis = "", None, None
    if art == "ausleihe":
        menge = _text(d.get("menge"), "wie viele", 40, pflicht=False) or "1"
        von, bis = _datum(d.get("von"), "ab wann"), _datum(d.get("bis"), "bis wann")
        if bis < von:
            raise ProjektFehler("Die Rückgabe liegt vor der Ausgabe.")
    in_besprechung = art == "rueckfrage" and bool(d.get("in_besprechung"))
    jetzt = db.jetzt()
    with db.transaktion(con):
        aid = con.execute("INSERT INTO anfrage (projekt_id, art, titel, text, aufgabe_id, menge, von, bis, bild, in_besprechung, "
                          "status, erstellt, geaendert) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'neu', ?, ?)",
                          (pid, art, titel, text, aufgabe_id, menge, von, bis, bild, 1 if in_besprechung else 0, jetzt, jetzt)).lastrowid
        db.ereignis(con, pid, "team", "Team", "anfrage_neu", anfrage_id=aid, anfrageart=art, titel=titel, aufgabe_id=aufgabe_id)
    if in_besprechung:   # als Frage auf die Tafel der naechsten Besprechung
        eid = besprechung.aendern(con, pid, "team", "Team", {"aktion": "eintrag_neu", "art": "frage", "text": titel})["eintrag_id"]
        con.execute("UPDATE eintrag SET anfrage_id = ? WHERE id = ?", (aid, eid))
    return aid


def team_aendern(con, pid, d):
    a = _holen(con, pid, d.get("anfrage_id"))
    aktion = d.get("aktion")
    with db.transaktion(con):
        if aktion == "zurueckziehen":
            if a["status"] != "neu":
                raise ProjektFehler("Die Anfrage ist schon in Bearbeitung.")
            status, antwort = "zurueckgezogen", a["antwort"]
        elif aktion == "erneut":   # nach "nachbessern": Abnahme erneut anfragen
            if a["art"] != "abnahme" or a["status"] != "nachbessern":
                raise ProjektFehler("Nur eine Abnahme mit „nachbessern“ lässt sich erneut anfragen.")
            status, antwort = "neu", a["antwort"]
        else:
            raise ProjektFehler("Unbekannte Aktion.")
        con.execute("UPDATE anfrage SET status = ?, antwort = ?, geaendert = ?, geaendert_von = 'Team' WHERE id = ?",
                    (status, antwort, db.jetzt(), a["id"]))
        db.ereignis(con, pid, "team", "Team", "anfrage_status", anfrage_id=a["id"], anfrageart=a["art"], titel=a["titel"],
                    status=status, aufgabe_id=a["aufgabe_id"])


# --- Lehrkraft ---

def bearbeiten(con, pid, wer, d):
    """Status setzen und antworten. Bei der Abnahme gehoert zu 'nachbessern' ein Hinweis."""
    a = _holen(con, pid, d.get("anfrage_id"))
    status = d.get("status") or a["status"]
    if status not in STATUS[a["art"]] or status == "zurueckgezogen":
        raise ProjektFehler("Diesen Status gibt es für diese Anfrage nicht.")
    antwort = _text(d.get("antwort", a["antwort"]), "eine Antwort", 2000, pflicht=False)
    if a["art"] == "rueckfrage" and status == "beantwortet" and not antwort:
        raise ProjektFehler("Bitte eine Antwort schreiben.")
    if status in ("nachbessern", "abgelehnt") and not antwort:
        raise ProjektFehler("Bitte kurz schreiben, was fehlt.")
    with db.transaktion(con):
        con.execute("UPDATE anfrage SET status = ?, antwort = ?, geaendert = ?, geaendert_von = ? WHERE id = ?",
                    (status, antwort, db.jetzt(), wer, a["id"]))
        db.ereignis(con, pid, "lehrkraft", wer, "anfrage_status", anfrage_id=a["id"], anfrageart=a["art"], titel=a["titel"],
                    status=status, antwort=antwort, aufgabe_id=a["aufgabe_id"])


def in_besprechung_geklaert(con, anfrage_id, wer):
    """Hook aus der Besprechung: die zugehoerige Frage wurde an der Tafel geklaert (in deren Transaktion)."""
    a = con.execute("SELECT * FROM anfrage WHERE id = ?", (anfrage_id,)).fetchone()
    if a is None or a["status"] != "neu":
        return
    antwort = "In der Besprechung am %s geklärt." % datetime.date.fromisoformat(db.jetzt()[:10]).strftime("%d.%m.")
    con.execute("UPDATE anfrage SET status = 'beantwortet', antwort = ?, geaendert = ?, geaendert_von = ? WHERE id = ?",
                (antwort, db.jetzt(), wer, a["id"]))
    db.ereignis(con, a["projekt_id"], "lehrkraft", wer, "anfrage_status", anfrage_id=a["id"], anfrageart=a["art"],
                titel=a["titel"], status="beantwortet", antwort=antwort, aufgabe_id=a["aufgabe_id"])


def uebersicht(con, konto):
    """Fuer die Lehrkraft: offene Anfragen aller betreuten Projekte und die der letzten 14 Tage."""
    grenze = (datetime.date.fromisoformat(db.jetzt()[:10]) - datetime.timedelta(days=14)).isoformat()
    liste_ = []
    for p in con.execute("SELECT p.* FROM projekt p JOIN projekt_lehrkraft pl ON pl.projekt_id = p.id WHERE pl.lehrkraft_id = ? "
                         "AND p.archiviert = 0", (konto["id"],)).fetchall():
        for a in liste(con, p["id"]):
            if a["offen"] or a["geaendert"] >= grenze:
                a.update({"projekt_id": p["id"], "projekt": p["titel"], "klasse": p["klasse"]})
                liste_.append(a)
    liste_.sort(key=lambda a: (not a["offen"], a["status"] != "neu", a["erstellt"]))
    return liste_


def _schultage_seit(zeit, heute):
    tag, n = datetime.date.fromisoformat(zeit[:10]), 0
    while tag < heute:
        tag += datetime.timedelta(days=1)
        if tag.weekday() < 5:
            n += 1
    return n


def warnungen(con, pid):
    heute = datetime.date.fromisoformat(db.jetzt()[:10])
    liste_ = []
    for a in con.execute("SELECT * FROM anfrage WHERE projekt_id = ? AND art = 'ausleihe' AND status = 'ausgegeben' AND bis < ?",
                         (pid, heute.isoformat())):
        liste_.append({"art": "rueckgabe_ueberfaellig", "stufe": "warnung", "anfrage_id": a["id"],
                       "text": "Rückgabe überfällig: „%s“ (bis %s)." % (a["titel"], datetime.date.fromisoformat(a["bis"]).strftime("%d.%m."))})
    for a in con.execute("SELECT * FROM anfrage WHERE projekt_id = ? AND status = 'neu'", (pid,)):
        if _schultage_seit(a["erstellt"], heute) >= 2:
            liste_.append({"art": "anfrage_wartet", "stufe": "intern", "anfrage_id": a["id"],
                           "text": "%s „%s“ wartet seit %s." % (NAMEN[a["art"]], a["titel"],
                                                               datetime.date.fromisoformat(a["erstellt"][:10]).strftime("%d.%m."))})
    return liste_
