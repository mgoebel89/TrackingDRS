"""Anfragen als Vorgaenge mit Gespraechsverlauf (wie ein Ticket): Rueckfrage, Material ausleihen, Abnahme/Freigabe und
eingereichte Bestelllisten.

Ein Vorgang hat einen Stand (offen = "neu" in der Oberflaeche, in Bearbeitung, erledigt), optional eine zustaendige
Lehrkraft und einen Verlauf aus Nachrichten (Team und Lehrkraft), internen Notizen (nur Lehrkraefte) und Ereignissen
(Statuswechsel, Zuweisung, Sonderfenster, Pruefentscheidungen ...). Zuweisen (an eine Lehrkraft, die das Projekt
betreut) setzt "in Bearbeitung", Zustaendigkeit wegnehmen wieder "neu"; wer als erste antwortet, uebernimmt den
Vorgang, wenn noch niemand zustaendig ist. Schreibt das Team in einen erledigten Vorgang, ist er wieder in Bearbeitung
bei derselben Lehrkraft (ohne Zustaendige: neu). Ungelesenes zaehlt je Lehrkraft und fuer das Team (Tabelle gelesen);
wer zugewiesen wird, hat den Vorgang ungelesen.

Die Schritte je Art bleiben im Feld status: Ausleihe neu/bereitgelegt/ausgegeben/zurueck/abgelehnt, Abnahme
neu/freigegeben/nachbessern; ein abschliessender Schritt setzt den Vorgang auf erledigt. Eine Rueckfrage mit "in der
Besprechung klaeren" liegt zusaetzlich als Frage auf der Tafel und wird dort erledigt. Nichts wird geloescht.
"""
import datetime
import json

from . import besprechung, db
from .projekte import ProjektFehler

STATUS = {
    "rueckfrage": ("neu", "beantwortet", "zurueckgezogen"),
    "ausleihe": ("neu", "bereitgelegt", "ausgegeben", "zurueck", "abgelehnt", "zurueckgezogen"),
    "abnahme": ("neu", "freigegeben", "nachbessern", "zurueckgezogen"),
    "bestellung": ("neu",),
}
ABSCHLUSS = {"beantwortet", "zurueck", "abgelehnt", "freigegeben", "zurueckgezogen"}
STAENDE = ("offen", "bearbeitung", "erledigt")
NAMEN = {"rueckfrage": "Rückfrage", "ausleihe": "Ausleihe", "abnahme": "Abnahme", "bestellung": "Bestellliste"}
MAX_NACHRICHT = 4000


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
        raise ProjektFehler("Diese Tätigkeit gibt es nicht.")
    return a["id"]


def _holen(con, pid, aid):
    try:
        a = con.execute("SELECT * FROM anfrage WHERE id = ? AND projekt_id = ?", (int(aid), pid)).fetchone()
    except (TypeError, ValueError):
        a = None
    if a is None:
        raise ProjektFehler("Diese Anfrage gibt es nicht.")
    return a


def _dict(a, titel_aufgabe=None):
    return {"id": a["id"], "art": a["art"], "titel": a["titel"], "text": a["text"], "aufgabe_id": a["aufgabe_id"],
            "aufgabe": titel_aufgabe, "menge": a["menge"], "von": a["von"], "bis": a["bis"], "bild": a["bild"],
            "in_besprechung": bool(a["in_besprechung"]), "status": a["status"], "stand": a["stand"],
            "zustaendig_id": a["zustaendig_id"], "bestellliste_id": a["bestellliste_id"],
            "erstellt": a["erstellt"], "geaendert": a["geaendert"], "geaendert_von": a["geaendert_von"],
            "offen": a["stand"] != "erledigt",
            "ueberfaellig": a["art"] == "ausleihe" and a["status"] == "ausgegeben" and bool(a["bis"]) and a["bis"] < db.jetzt()[:10]}


def liste(con, pid):
    titel = {a["id"]: a["titel"] for a in con.execute("SELECT id, titel FROM aufgabe WHERE projekt_id = ?", (pid,))}
    zeilen = [_dict(a, titel.get(a["aufgabe_id"])) for a in con.execute("SELECT * FROM anfrage WHERE projekt_id = ? ORDER BY id DESC", (pid,))]
    zeilen.sort(key=lambda a: (not a["offen"], -a["id"]))
    return zeilen


# --- Verlauf schreiben (in der Transaktion des Aufrufers) ---

def notieren(con, aid, wer_art, wer, art="ereignis", text="", bild=None, **daten):
    """Einen Eintrag an den Verlauf haengen: Nachricht, interne Notiz oder Ereignis (daten: was = Art des Ereignisses)."""
    jetzt = db.jetzt()
    nid = con.execute("INSERT INTO nachricht (anfrage_id, art, text, bild, daten, zeit, wer_art, wer) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (aid, art, text, bild, json.dumps(daten, ensure_ascii=False), jetzt, wer_art, wer)).lastrowid
    con.execute("UPDATE anfrage SET geaendert = ?, geaendert_von = ? WHERE id = ?", (jetzt, wer, aid))
    return nid


def _stand(con, a, neu, wer_art, wer):
    if a["stand"] != neu:
        con.execute("UPDATE anfrage SET stand = ? WHERE id = ?", (neu, a["id"]))
        notieren(con, a["id"], wer_art, wer, was="stand", stand=neu, alt=a["stand"])


def _uebernehmen(con, a, konto, wer_art="lehrkraft", von=None):
    """konto wird zustaendig. von: die Lehrkraft, die zuweist (sonst uebernimmt konto selbst)."""
    fremd = von is not None and von["id"] != konto["id"]
    con.execute("UPDATE anfrage SET zustaendig_id = ? WHERE id = ?", (konto["id"], a["id"]))
    notieren(con, a["id"], wer_art, (von if fremd else konto)["kuerzel"], was="zustaendig", kuerzel=konto["kuerzel"].upper(),
             name=konto["name"], von=von["kuerzel"].upper() if fremd else None)
    if fremd:   # fuer die Zugewiesene ungelesen
        con.execute("DELETE FROM gelesen WHERE anfrage_id = ? AND leser = ?", (a["id"], "l%d" % konto["id"]))


def betreuer(con, pid):
    """Lehrkraefte, die das Projekt betreuen (fuer die Auswahl "Zustaendig")."""
    return [{"id": z["id"], "kuerzel": z["kuerzel"].upper(), "name": z["name"]} for z in con.execute(
        "SELECT l.id, l.kuerzel, l.name FROM lehrkraft l JOIN projekt_lehrkraft pl ON pl.lehrkraft_id = l.id "
        "WHERE pl.projekt_id = ? AND l.gesperrt = 0 ORDER BY l.name", (pid,))]


# --- Team ---

def anlegen(con, pid, d, bild=None):
    """Neuer Vorgang des Teams. bild: Dateiname eines schon gespeicherten Fotos (Abnahme)."""
    art = d.get("art")
    if art not in STATUS or art == "bestellung":
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
                          "status, erstellt, geaendert, geaendert_von) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'neu', ?, ?, 'Team')",
                          (pid, art, titel, text, aufgabe_id, menge, von, bis, bild, 1 if in_besprechung else 0, jetzt, jetzt)).lastrowid
        db.ereignis(con, pid, "team", "Team", "anfrage_neu", anfrage_id=aid, anfrageart=art, titel=titel, aufgabe_id=aufgabe_id)
    if in_besprechung:   # als Frage auf die Tafel der naechsten Besprechung
        eid = besprechung.aendern(con, pid, "team", "Team", {"aktion": "eintrag_neu", "art": "frage", "text": titel})["eintrag_id"]
        con.execute("UPDATE eintrag SET anfrage_id = ? WHERE id = ?", (aid, eid))
        with db.transaktion(con):
            notieren(con, aid, "team", "Team", was="tafel")
    return aid


def team_aendern(con, pid, d):
    a = _holen(con, pid, d.get("anfrage_id"))
    aktion = d.get("aktion")
    with db.transaktion(con):
        if aktion == "zurueckziehen":
            if a["stand"] != "offen" or a["art"] == "bestellung":
                raise ProjektFehler("Die Anfrage ist schon in Bearbeitung.")
            con.execute("UPDATE anfrage SET status = 'zurueckgezogen' WHERE id = ?", (a["id"],))
            notieren(con, a["id"], "team", "Team", was="status", status="zurueckgezogen")
            _stand(con, a, "erledigt", "team", "Team")
        elif aktion == "wieder_oeffnen":   # J7: erledigte Anfrage mit Grund wieder oeffnen, zurueck an dieselbe Lehrkraft
            if a["stand"] != "erledigt":
                raise ProjektFehler("Die Anfrage ist nicht erledigt.")
            grund = _text(d.get("text"), "kurz, was noch offen ist", MAX_NACHRICHT)
            zust = a["zustaendig_id"]
            if zust is not None and not con.execute("SELECT 1 FROM projekt_lehrkraft WHERE projekt_id = ? AND lehrkraft_id = ?",
                                                    (pid, zust)).fetchone():
                con.execute("UPDATE anfrage SET zustaendig_id = NULL WHERE id = ?", (a["id"],))   # betreut nicht mehr: wieder neu
                notieren(con, a["id"], "team", "Team", was="zustaendig", kuerzel=None)
                zust = None
            if a["status"] == "zurueckgezogen":
                con.execute("UPDATE anfrage SET status = 'neu' WHERE id = ?", (a["id"],))
            notieren(con, a["id"], "team", "Team", was="wieder_geoeffnet")
            nid = notieren(con, a["id"], "team", "Team", art="nachricht", text=grund)
            con.execute("UPDATE anfrage SET stand = ? WHERE id = ?", ("bearbeitung" if zust else "offen", a["id"]))
            _gelesen(con, a["id"], "team", nid)
            db.ereignis(con, pid, "team", "Team", "anfrage_wieder", anfrage_id=a["id"], anfrageart=a["art"], titel=a["titel"], text=grund[:200])
            return
        elif aktion == "erneut":   # nach "nachbessern": Abnahme erneut anfragen
            if a["art"] != "abnahme" or a["status"] != "nachbessern":
                raise ProjektFehler("Nur eine Abnahme mit „nachbessern“ lässt sich erneut anfragen.")
            con.execute("UPDATE anfrage SET status = 'neu' WHERE id = ?", (a["id"],))
            notieren(con, a["id"], "team", "Team", was="status", status="neu")
            _stand(con, a, "offen", "team", "Team")
        else:
            raise ProjektFehler("Unbekannte Aktion.")
        db.ereignis(con, pid, "team", "Team", "anfrage_status", anfrage_id=a["id"], anfrageart=a["art"], titel=a["titel"],
                    status="zurueckgezogen" if aktion == "zurueckziehen" else "neu", aufgabe_id=a["aufgabe_id"])


def nachricht(con, pid, aid, wer_art, d, konto=None):
    """Nachricht in den Verlauf. konto: die schreibende Lehrkraft (sonst schreibt das Team). Interne Notizen nur von
    Lehrkraeften. bild: Dateiname eines schon gespeicherten Fotos."""
    a = _holen(con, pid, aid)
    lehrkraft = wer_art == "lehrkraft"
    intern = lehrkraft and bool(d.get("intern"))
    text = _text(d.get("text"), "einen Text", MAX_NACHRICHT, pflicht=not d.get("bild"))
    wer = konto["kuerzel"] if lehrkraft else "Team"
    with db.transaktion(con):
        nid = notieren(con, a["id"], wer_art, wer, art="intern" if intern else "nachricht", text=text, bild=d.get("bild"))
        if not intern:
            if lehrkraft:
                if a["zustaendig_id"] is None:
                    _uebernehmen(con, a, konto)
                if a["stand"] == "offen":
                    _stand(con, a, "bearbeitung", wer_art, wer)
            elif a["stand"] == "erledigt":   # zurueck zu derselben Lehrkraft
                _stand(con, a, "bearbeitung" if a["zustaendig_id"] else "offen", wer_art, wer)
            db.ereignis(con, pid, wer_art, wer, "anfrage_nachricht", anfrage_id=a["id"], anfrageart=a["art"], titel=a["titel"],
                        text=text[:200])
        if lehrkraft:   # eigene Nachricht gilt als gelesen
            _gelesen(con, a["id"], "l%d" % konto["id"], nid)
        else:
            _gelesen(con, a["id"], "team", nid)
    return nid


# --- Lehrkraft ---

def bearbeiten(con, pid, konto, d):
    """Lehrkraft: Status setzen (aktion stand: offen/bearbeitung/erledigt; aktion status: Schritt der Ausleihe/Abnahme;
    aktion uebernehmen/abgeben). Zu 'nachbessern' und 'abgelehnt' gehoert eine Nachricht."""
    a = _holen(con, pid, d.get("anfrage_id"))
    aktion = d.get("aktion") or "status"
    wer = konto["kuerzel"]
    with db.transaktion(con):
        if aktion == "uebernehmen":
            _uebernehmen(con, a, konto)
            if a["stand"] == "offen":
                _stand(con, a, "bearbeitung", "lehrkraft", wer)
        elif aktion == "abgeben" or (aktion == "zuweisen" and d.get("lehrkraft_id") in (None, "")):
            if a["zustaendig_id"] is not None:
                con.execute("UPDATE anfrage SET zustaendig_id = NULL WHERE id = ?", (a["id"],))
                notieren(con, a["id"], "lehrkraft", wer, was="zustaendig", kuerzel=None)
            if a["stand"] == "bearbeitung":
                _stand(con, a, "offen", "lehrkraft", wer)
        elif aktion == "zuweisen":   # an eine Lehrkraft, die das Projekt betreut (auch an sich selbst)
            try:
                ziel = int(d.get("lehrkraft_id"))
            except (TypeError, ValueError):
                ziel = None
            if not any(b["id"] == ziel for b in betreuer(con, pid)):
                raise ProjektFehler("Zuweisen geht nur an Lehrkräfte, die das Projekt betreuen.")
            if a["zustaendig_id"] != ziel:
                _uebernehmen(con, a, con.execute("SELECT * FROM lehrkraft WHERE id = ?", (ziel,)).fetchone(), von=konto)
            if a["stand"] == "offen":
                _stand(con, a, "bearbeitung", "lehrkraft", wer)
        elif aktion == "stand":
            stand = d.get("stand")
            if stand not in STAENDE:
                raise ProjektFehler("Unbekannter Status.")
            if a["zustaendig_id"] is None and stand != "offen":
                _uebernehmen(con, a, konto)
            _stand(con, a, stand, "lehrkraft", wer)
        elif aktion == "status":
            status = d.get("status")
            if status not in STATUS[a["art"]] or status in ("neu", "zurueckgezogen"):
                raise ProjektFehler("Diesen Schritt gibt es für diese Anfrage nicht.")
            text = _text(d.get("text"), "einen Hinweis für das Team", MAX_NACHRICHT, pflicht=status in ("nachbessern", "abgelehnt"))
            con.execute("UPDATE anfrage SET status = ? WHERE id = ?", (status, a["id"]))
            notieren(con, a["id"], "lehrkraft", wer, was="status", status=status)
            if text:
                notieren(con, a["id"], "lehrkraft", wer, art="nachricht", text=text)
            if a["zustaendig_id"] is None:
                _uebernehmen(con, a, konto)
            _stand(con, a, "erledigt" if status in ABSCHLUSS else "bearbeitung", "lehrkraft", wer)
            db.ereignis(con, pid, "lehrkraft", wer, "anfrage_status", anfrage_id=a["id"], anfrageart=a["art"], titel=a["titel"],
                        status=status, antwort=text, aufgabe_id=a["aufgabe_id"])
        else:
            raise ProjektFehler("Unbekannte Aktion.")


def in_besprechung_geklaert(con, anfrage_id, wer):
    """Hook aus der Besprechung: die zugehoerige Frage wurde an der Tafel geklaert (in deren Transaktion)."""
    a = con.execute("SELECT * FROM anfrage WHERE id = ?", (anfrage_id,)).fetchone()
    if a is None or a["stand"] == "erledigt":
        return
    con.execute("UPDATE anfrage SET status = 'beantwortet' WHERE id = ?", (a["id"],))
    notieren(con, a["id"], "lehrkraft", wer, was="geklaert", datum=db.jetzt()[:10])
    _stand(con, a, "erledigt", "lehrkraft", wer)
    db.ereignis(con, a["projekt_id"], "lehrkraft", wer, "anfrage_status", anfrage_id=a["id"], anfrageart=a["art"],
                titel=a["titel"], status="beantwortet", antwort="In der Besprechung geklärt.", aufgabe_id=a["aufgabe_id"])


# --- Bestelllisten als Vorgang (Aufrufe aus bestellung.py, in dessen Transaktion) ---

def bestellung_notieren(con, liste_id, wer_art, wer, **daten):
    """Seit Stufe J1 legt Einreichen keine Anfrage mehr an. Listen aus der Zeit davor haben noch einen Vorgang: dessen
    Verlauf wird weitergeschrieben (er steht bei der Liste), der Stand aendert sich nicht mehr."""
    a = con.execute("SELECT * FROM anfrage WHERE bestellliste_id = ?", (liste_id,)).fetchone()
    if a is not None:
        notieren(con, a["id"], wer_art, wer, **daten)


def vorgang_notieren(con, aid, pid, wer_art, wer, **daten):
    """Ereignis an einen Vorgang des Projekts haengen (z. B. Sonderfenster aus einer Rueckfrage)."""
    a = con.execute("SELECT * FROM anfrage WHERE id = ? AND projekt_id = ?", (aid, pid)).fetchone()
    if a is not None:
        notieren(con, a["id"], wer_art, wer, **daten)


# --- Gelesen und Listen ---

def _gelesen(con, aid, leser, bis):
    con.execute("INSERT INTO gelesen (anfrage_id, leser, bis) VALUES (?, ?, ?) ON CONFLICT (anfrage_id, leser) "
                "DO UPDATE SET bis = MAX(bis, excluded.bis)", (aid, leser, bis))


def _ungelesen(con, a, leser, kuerzel=None):
    """Ungelesen fuer die Lehrkraft (leser 'l<id>'): Neues vom Team oder von anderen Lehrkraeften, oder ein offener
    Vorgang, den sie noch nie geoeffnet hat. Fuer das Team: Neues von Lehrkraeften (ohne interne Notizen)."""
    g = con.execute("SELECT bis FROM gelesen WHERE anfrage_id = ? AND leser = ?", (a["id"], leser)).fetchone()
    bis = g["bis"] if g else 0
    if leser == "team":
        sql = "SELECT 1 FROM nachricht WHERE anfrage_id = ? AND id > ? AND wer_art != 'team' AND art != 'intern' LIMIT 1"
        return bool(con.execute(sql, (a["id"], bis)).fetchone())
    if g is None and (a["stand"] == "offen" or "l%s" % a["zustaendig_id"] == leser):   # neu oder mir zugewiesen
        return True
    sql = ("SELECT 1 FROM nachricht WHERE anfrage_id = ? AND id > ? AND (wer_art = 'team' OR (wer_art = 'lehrkraft' AND wer != ? "
           "AND art != 'ereignis')) LIMIT 1")
    return bool(con.execute(sql, (a["id"], bis, kuerzel)).fetchone())


def _letzte(con, aid, mit_intern):
    z = con.execute("SELECT * FROM nachricht WHERE anfrage_id = ? AND art != 'ereignis'%s ORDER BY id DESC LIMIT 1"
                    % ("" if mit_intern else " AND art != 'intern'"), (aid,)).fetchone()
    return {"text": z["text"][:140], "wer_art": z["wer_art"], "wer": z["wer"], "zeit": z["zeit"], "intern": z["art"] == "intern"} if z else None


def _meine_projekte(con, konto):
    return {p["id"]: p for p in con.execute("SELECT p.* FROM projekt p JOIN projekt_lehrkraft pl ON pl.projekt_id = p.id "
                                            "WHERE pl.lehrkraft_id = ? AND p.archiviert = 0", (konto["id"],))}


def vorgaenge_lehrkraft(con, konto, filter_="aktiv", projekt_id=None, art=None, staende=None, meine=False):
    """Eingang der Lehrkraft. staende: Liste aus offen, bearbeitung, erledigt (die Knoepfe im Eingang), dazu meine
    (nur mir zugewiesen). Ohne staende gilt filter_: aktiv (offen + in Bearbeitung), offen, bearbeitung, meine,
    erledigt, alle."""
    projekte = _meine_projekte(con, konto)
    if projekt_id is not None:
        projekte = {k: v for k, v in projekte.items() if k == projekt_id}
    if not projekte:
        return []
    kuerzel = {z["id"]: z["kuerzel"].upper() for z in con.execute("SELECT id, kuerzel FROM lehrkraft")}
    sql = "SELECT * FROM anfrage WHERE art != 'bestellung' AND projekt_id IN (%s)" % ",".join("?" * len(projekte))
    werte = list(projekte)
    if art in STATUS:
        sql += " AND art = ?"
        werte.append(art)
    if staende is not None:
        staende = [x for x in staende if x in STAENDE]
        sql += (" AND stand IN (%s)" % ",".join("?" * len(staende))) if staende else " AND 0"
        werte.extend(staende)
        if meine:
            sql += " AND zustaendig_id = ?"
            werte.append(konto["id"])
        if "erledigt" in staende:
            sql += " ORDER BY geaendert DESC LIMIT 200"
    elif filter_ in STAENDE:
        sql += " AND stand = ?"
        werte.append(filter_)
    elif filter_ == "meine":
        sql += " AND zustaendig_id = ? AND stand != 'erledigt'"
        werte.append(konto["id"])
    elif filter_ != "alle":
        sql += " AND stand != 'erledigt'"
    if staende is None and filter_ in ("erledigt", "alle"):
        sql += " ORDER BY geaendert DESC LIMIT 200"
    betreut = {(z["projekt_id"], z["lehrkraft_id"]) for z in con.execute("SELECT projekt_id, lehrkraft_id FROM projekt_lehrkraft")}
    liste_ = []
    for a in con.execute(sql, werte).fetchall():
        d = _dict(a)
        p = projekte[a["projekt_id"]]
        d.update({"projekt_id": p["id"], "projekt": p["titel"], "klasse": p["klasse"], "zustaendig": kuerzel.get(a["zustaendig_id"]),
                  "zustaendig_ehemalig": a["zustaendig_id"] is not None and (p["id"], a["zustaendig_id"]) not in betreut,
                  "ungelesen": _ungelesen(con, a, "l%d" % konto["id"], konto["kuerzel"]), "letzte": _letzte(con, a["id"], True)})
        liste_.append(d)
    return sorted(liste_, key=lambda d: (not d["ungelesen"], -_zeitwert(d["geaendert"])))   # Ungelesenes oben, dann das Neueste


def eingang(con, konto, projekt_id=None, art=None, staende=None, meine=False):
    """Alles fuer den Eingang: Liste, Zahlen je Stand (fuer die Knoepfe), Betreuer je Projekt (fuer "Zustaendig")."""
    liste_ = vorgaenge_lehrkraft(con, konto, projekt_id=projekt_id, art=art, staende=staende, meine=meine)
    aktiv = vorgaenge_lehrkraft(con, konto, projekt_id=projekt_id, art=art, staende=["offen", "bearbeitung"], meine=meine)
    projekte = list(_meine_projekte(con, konto)) if projekt_id is None else [projekt_id]
    return {"vorgaenge": liste_, "zahlen": {st: sum(1 for d in aktiv if d["stand"] == st) for st in ("offen", "bearbeitung")},
            "betreuer": {str(pid): betreuer(con, pid) for pid in projekte}}


def _zeitwert(zeit):
    return datetime.datetime.fromisoformat(zeit).timestamp()


def vorgaenge_team(con, pid):
    liste_ = []
    namen = {z["id"]: z["name"] for z in con.execute("SELECT id, name FROM lehrkraft")}
    for a in con.execute("SELECT * FROM anfrage WHERE projekt_id = ? AND art != 'bestellung' ORDER BY geaendert DESC", (pid,)).fetchall():
        d = _dict(a)
        d.update({"ungelesen": _ungelesen(con, a, "team"), "letzte": _letzte(con, a["id"], False),
                  "zustaendig_name": namen.get(a["zustaendig_id"])})
        liste_.append(d)
    return sorted(liste_, key=lambda d: (not d["offen"], not d["ungelesen"], -_zeitwert(d["geaendert"])))


def vorgang(con, pid, aid, konto=None):
    """Ein Vorgang mit Verlauf. Mit konto (Lehrkraft) samt internen Notizen; das Oeffnen markiert alles als gelesen."""
    a = _holen(con, pid, aid)
    titel = con.execute("SELECT titel FROM aufgabe WHERE id = ?", (a["aufgabe_id"],)).fetchone() if a["aufgabe_id"] else None
    d = _dict(a, titel[0] if titel else None)
    p = con.execute("SELECT titel, klasse FROM projekt WHERE id = ?", (pid,)).fetchone()
    d.update({"projekt_id": pid, "projekt": p["titel"], "klasse": p["klasse"]})
    if a["zustaendig_id"]:
        z = con.execute("SELECT kuerzel, name FROM lehrkraft WHERE id = ?", (a["zustaendig_id"],)).fetchone()
        d["zustaendig"] = {"id": a["zustaendig_id"], "kuerzel": z["kuerzel"].upper(), "name": z["name"],
                           "ehemalig": not con.execute("SELECT 1 FROM projekt_lehrkraft WHERE projekt_id = ? AND lehrkraft_id = ?",
                                                       (pid, a["zustaendig_id"])).fetchone()}
    if konto:
        d["betreuer"] = betreuer(con, pid)
    sql = "SELECT * FROM nachricht WHERE anfrage_id = ?" + ("" if konto else " AND art != 'intern'") + " ORDER BY id"
    d["verlauf"] = [{"id": n["id"], "art": n["art"], "text": n["text"], "bild": n["bild"], "daten": json.loads(n["daten"]),
                     "zeit": n["zeit"], "wer_art": n["wer_art"], "wer": n["wer"]} for n in con.execute(sql, (a["id"],))]
    if a["bestellliste_id"]:
        d["positionen"] = con.execute("SELECT COUNT(*) FROM position WHERE liste_id = ? AND gestrichen = 0",
                                      (a["bestellliste_id"],)).fetchone()[0]
    letzte = d["verlauf"][-1]["id"] if d["verlauf"] else 0
    with db.transaktion(con):
        _gelesen(con, a["id"], "l%d" % konto["id"] if konto else "team", letzte)
    return d


def _neu(con, liste_, mit_intern):
    """Die ungelesenen Vorgaenge zum Melden (Einblendung, Benachrichtigung). nid = letzter Eintrag im Verlauf: aendert
    er sich, ist etwas Neues dazugekommen."""
    sql = "SELECT MAX(id) FROM nachricht WHERE anfrage_id = ?" + ("" if mit_intern else " AND art != 'intern'")
    return [{"id": d["id"], "titel": d["titel"], "projekt": d.get("projekt"), "projekt_id": d.get("projekt_id"),
             "nid": con.execute(sql, (d["id"],)).fetchone()[0] or 0, "text": d["letzte"]["text"] if d["letzte"] else d["text"]}
            for d in liste_ if d["ungelesen"]]


def zaehler(con, konto):
    """Fuer das Menue: ungelesene Vorgaenge und offene (noch niemand dran), dazu die ungelesenen zum Melden."""
    liste_ = vorgaenge_lehrkraft(con, konto)
    return {"ungelesen": sum(1 for d in liste_ if d["ungelesen"]), "offen": sum(1 for d in liste_ if d["stand"] == "offen"),
            "neu": _neu(con, liste_, True)}


def team_zaehler(con, pid):
    """Fuer die Reiter des Teams: Vorgaenge mit neuer Antwort einer Lehrkraft."""
    from . import bestellung   # hier, um einen Import-Kreis zu vermeiden
    liste_ = vorgaenge_team(con, pid)
    return {"ungelesen": sum(1 for d in liste_ if d["ungelesen"]), "neu": _neu(con, liste_, False),
            "bestellung": bestellung.team_neu(con, pid)}


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
    # wartet: das Letzte im Gespraech kam vom Team (oder es gibt nur die Anfrage) und ist zwei Schultage her
    for a in con.execute("SELECT * FROM anfrage WHERE projekt_id = ? AND stand != 'erledigt' AND art != 'bestellung'", (pid,)).fetchall():
        letzte = con.execute("SELECT wer_art, zeit FROM nachricht WHERE anfrage_id = ? AND art = 'nachricht' ORDER BY id DESC LIMIT 1",
                             (a["id"],)).fetchone()
        wer_art, zeit = (letzte["wer_art"], letzte["zeit"]) if letzte else ("team", a["erstellt"])
        if wer_art == "team" and _schultage_seit(zeit, heute) >= 2:
            liste_.append({"art": "anfrage_wartet", "stufe": "intern", "anfrage_id": a["id"],
                           "text": "%s „%s“ wartet seit %s auf eine Antwort." % (NAMEN[a["art"]], a["titel"],
                                                                               datetime.date.fromisoformat(zeit[:10]).strftime("%d.%m."))})
    return liste_
