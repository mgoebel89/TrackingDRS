"""Lehrernotizen als gemeinsamer Zeitstrahl (Stufe J5): eine Sammlung fuer alle Lehrkraefte, neueste oben. Jede Notiz
hat eine Ueberschrift, einen Text, die Dringlichkeit normal oder dringend und auf Wunsch ein Projekt. Das Team sieht
Lehrernotizen nie (im Bericht nur, wenn die Lehrkraft "mit Lehrernotizen" waehlt).

Aendern und verwerfen darf nur, wer die Notiz geschrieben hat; verworfen statt geloescht, wie ueberall. Die Notizen
aus der Lehreransicht einer Besprechung erscheinen als eigene Karte im Zeitstrahl, bearbeitet werden sie dort.
Dringende Notizen, die eine Lehrkraft noch nicht aufgeklappt hat, zaehlen fuer die rote Zahl am Menuepunkt.
"""
import datetime

from . import db
from .projekte import ProjektFehler

MAX_UEBERSCHRIFT = 120
MAX_TEXT = 10000


def _text(wert, feld, laenge, pflicht=False):
    wert = str(wert or "").strip()
    if pflicht and not wert:
        raise ProjektFehler("Bitte %s angeben." % feld)
    if len(wert) > laenge:
        raise ProjektFehler("Der Text ist zu lang (höchstens %d Zeichen)." % laenge)
    return wert


def ueberschrift_aus(text):
    """Erste Zeile als Ueberschrift (fuer alte Notizen ohne Ueberschrift)."""
    zeile = (text or "").strip().splitlines()[0] if (text or "").strip() else "Notiz"
    return zeile if len(zeile) <= 80 else zeile[:77].rstrip() + " …"


def _projekt_id(con, wert):
    if wert in (None, ""):
        return None
    try:
        pid = int(wert)
    except (TypeError, ValueError):
        pid = None
    if pid is None or not con.execute("SELECT 1 FROM projekt WHERE id = ?", (pid,)).fetchone():
        raise ProjektFehler("Dieses Projekt gibt es nicht.")
    return pid


def anlegen(con, konto, d):
    ue = _text(d.get("ueberschrift"), "eine Überschrift", MAX_UEBERSCHRIFT, pflicht=True)
    text = _text(d.get("text"), "einen Text", MAX_TEXT)
    pid = _projekt_id(con, d.get("projekt_id"))
    with db.transaktion(con):
        nid = con.execute("INSERT INTO lehrernotiz (ueberschrift, text, dringend, projekt_id, lehrkraft_id, wer, erstellt) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?)", (ue, text, 1 if d.get("dringend") else 0, pid, konto["id"], konto["kuerzel"],
                                                        db.jetzt())).lastrowid
        _gelesen(con, nid, konto["id"])   # die eigene Notiz ist gelesen
    return nid


def _holen(con, nid):
    try:
        n = con.execute("SELECT * FROM lehrernotiz WHERE id = ? AND verworfen = 0", (int(nid),)).fetchone()
    except (TypeError, ValueError):
        n = None
    if n is None:
        raise ProjektFehler("Diese Notiz gibt es nicht.")
    return n


def _gelesen(con, nid, lehrkraft_id):
    con.execute("INSERT OR IGNORE INTO lehrernotiz_gelesen (notiz_id, lehrkraft_id) VALUES (?, ?)", (nid, lehrkraft_id))


def aendern(con, konto, nid, d):
    n = _holen(con, nid)
    aktion = d.get("aktion")
    with db.transaktion(con):
        if aktion == "gelesen":
            _gelesen(con, n["id"], konto["id"])
            return
        if n["lehrkraft_id"] != konto["id"]:
            raise ProjektFehler("Ändern kann nur, wer die Notiz geschrieben hat.")
        if aktion == "verwerfen":
            con.execute("UPDATE lehrernotiz SET verworfen = 1 WHERE id = ?", (n["id"],))
        elif aktion == "aendern":
            con.execute("UPDATE lehrernotiz SET ueberschrift = ?, text = ?, dringend = ?, projekt_id = ?, geaendert = ? WHERE id = ?",
                        (_text(d.get("ueberschrift"), "eine Überschrift", MAX_UEBERSCHRIFT, pflicht=True),
                         _text(d.get("text"), "einen Text", MAX_TEXT), 1 if d.get("dringend") else 0,
                         _projekt_id(con, d.get("projekt_id")), db.jetzt(), n["id"]))
        else:
            raise ProjektFehler("Unbekannte Aktion.")


def liste(con, konto):
    """Alle Notizen und Besprechungsnotizen, neueste oben (fuer Filter und Suche im Browser)."""
    namen = {z["id"]: z["name"] for z in con.execute("SELECT id, name FROM lehrkraft")}
    gelesen = {z[0] for z in con.execute("SELECT notiz_id FROM lehrernotiz_gelesen WHERE lehrkraft_id = ?", (konto["id"],))}
    projekte = {z["id"]: z for z in con.execute("SELECT id, titel, klasse, archiviert FROM projekt")}
    eintraege = []
    for n in con.execute("SELECT * FROM lehrernotiz WHERE verworfen = 0 ORDER BY erstellt DESC, id DESC LIMIT 1000"):
        p = projekte.get(n["projekt_id"])
        eintraege.append({"id": n["id"], "art": "notiz", "ueberschrift": n["ueberschrift"], "text": n["text"], "dringend": bool(n["dringend"]),
                          "projekt_id": n["projekt_id"], "projekt": p["titel"] if p else None, "erstellt": n["erstellt"],
                          "geaendert": n["geaendert"], "wer": namen.get(n["lehrkraft_id"], n["wer"].upper()),
                          "eigen": n["lehrkraft_id"] == konto["id"], "gelesen": n["id"] in gelesen})
    for b in con.execute("SELECT b.id, b.projekt_id, b.woche, b.notizen, b.abgeschlossen FROM besprechung b WHERE b.notizen != '' "
                         "ORDER BY b.woche DESC LIMIT 300"):
        p = projekte.get(b["projekt_id"])
        if p is None:
            continue
        kw = datetime.date.fromisoformat(b["woche"]).isocalendar()[1]
        eintraege.append({"id": None, "art": "besprechung", "ueberschrift": "Notizen zur Besprechung %s, KW %d" % (p["titel"], kw),
                          "text": b["notizen"], "dringend": False, "projekt_id": p["id"], "projekt": p["titel"],
                          "erstellt": b["abgeschlossen"] or b["woche"] + "T00:00:00", "geaendert": None, "wer": "",
                          "eigen": False, "gelesen": True, "woche": b["woche"]})
    eintraege.sort(key=lambda e: e["erstellt"], reverse=True)
    return {"notizen": eintraege,
            "projekte": sorted([{"id": p["id"], "titel": p["titel"], "klasse": p["klasse"]} for p in projekte.values() if not p["archiviert"]],
                               key=lambda p: (p["klasse"], p["titel"])),
            "dringend_ungelesen": sum(1 for e in eintraege if e["dringend"] and not e["gelesen"])}


def zaehler(con, konto):
    """Dringende Notizen anderer Lehrkraefte, die diese Lehrkraft noch nicht aufgeklappt hat."""
    z = con.execute("SELECT n.id, n.ueberschrift FROM lehrernotiz n WHERE n.verworfen = 0 AND n.dringend = 1 AND NOT EXISTS "
                    "(SELECT 1 FROM lehrernotiz_gelesen g WHERE g.notiz_id = n.id AND g.lehrkraft_id = ?) ORDER BY n.id", (konto["id"],)).fetchall()
    return {"dringend_ungelesen": len(z), "neu": [{"id": r["id"], "ueberschrift": r["ueberschrift"]} for r in z]}


def fuer_projekt(con, pid):
    """Fuer den Bericht: Notizen eines Projekts samt Besprechungsnotizen (Form wie bisher extras.notizen)."""
    liste_ = [{"id": n["id"], "ueberschrift": n["ueberschrift"], "text": n["text"], "erstellt": n["erstellt"], "geaendert": n["geaendert"],
               "wer": n["wer"], "dringend": bool(n["dringend"]), "art": "notiz"}
              for n in con.execute("SELECT * FROM lehrernotiz WHERE projekt_id = ? AND verworfen = 0 ORDER BY erstellt DESC, id DESC", (pid,))]
    for b in con.execute("SELECT woche, notizen, abgeschlossen FROM besprechung WHERE projekt_id = ? AND notizen != '' ORDER BY woche DESC", (pid,)):
        liste_.append({"id": None, "text": b["notizen"], "erstellt": b["abgeschlossen"] or b["woche"] + "T00:00:00", "wer": "",
                       "art": "besprechung", "woche": b["woche"]})
    liste_.sort(key=lambda n: n["erstellt"], reverse=True)
    return liste_
