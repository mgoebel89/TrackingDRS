"""Anfragen als Vorgaenge mit Gespraechsverlauf (wie ein Ticket): Rueckfrage, Material ausleihen, Abnahme/Freigabe und
eingereichte Bestelllisten.

Ein Vorgang hat einen Status (offen, in Bearbeitung, erledigt), optional eine zustaendige Lehrkraft und einen Verlauf aus
Nachrichten (Team und Lehrkraft), internen Notizen (nur Lehrkraefte) und Ereignissen (Statuswechsel, Uebernahme,
Sonderfenster, Pruefentscheidungen ...). Uebernimmt eine Lehrkraft oder antwortet sie, ist der Vorgang in Bearbeitung;
wer als erste antwortet, uebernimmt ihn, wenn noch niemand zustaendig ist. Schreibt das Team in einen erledigten
Vorgang, ist er wieder offen. Ungelesenes zaehlt je Lehrkraft und fuer das Team (Tabelle gelesen).

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
        raise ProjektFehler("Diese Aufgabe gibt es nicht.")
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


def _uebernehmen(con, a, konto, wer_art="lehrkraft"):
    con.execute("UPDATE anfrage SET zustaendig_id = ? WHERE id = ?", (konto["id"], a["id"]))
    notieren(con, a["id"], wer_art, konto["kuerzel"], was="zustaendig", kuerzel=konto["kuerzel"].upper(), name=konto["name"])


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
            elif a["stand"] == "erledigt":
                _stand(con, a, "offen", wer_art, wer)
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
        elif aktion == "abgeben":
            con.execute("UPDATE anfrage SET zustaendig_id = NULL WHERE id = ?", (a["id"],))
            notieren(con, a["id"], "lehrkraft", wer, was="zustaendig", kuerzel=None)
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

def bestellung_vorgang(con, pid, liste_id, positionen):
    jetzt = db.jetzt()
    aid = con.execute("INSERT INTO anfrage (projekt_id, art, titel, status, erstellt, geaendert, geaendert_von, bestellliste_id) "
                      "VALUES (?, 'bestellung', ?, 'neu', ?, ?, 'Team', ?)",
                      (pid, "Bestellliste vom %s (%d Positionen)" % (datetime.date.fromisoformat(jetzt[:10]).strftime("%d.%m."), positionen),
                       jetzt, jetzt, liste_id)).lastrowid
    return aid


def bestellung_notieren(con, liste_id, wer_art, wer, **daten):
    a = con.execute("SELECT * FROM anfrage WHERE bestellliste_id = ?", (liste_id,)).fetchone()
    if a is None:
        return
    notieren(con, a["id"], wer_art, wer, **daten)
    if wer_art == "lehrkraft" and a["stand"] == "offen":
        _stand(con, a, "bearbeitung", wer_art, wer)


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
    if g is None and a["stand"] == "offen":
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


def vorgaenge_lehrkraft(con, konto, filter_="aktiv", projekt_id=None, art=None):
    """Eingang der Lehrkraft. filter_: aktiv (offen + in Bearbeitung), offen, bearbeitung, meine, erledigt, alle."""
    projekte = _meine_projekte(con, konto)
    if projekt_id is not None:
        projekte = {k: v for k, v in projekte.items() if k == projekt_id}
    if not projekte:
        return []
    kuerzel = {z["id"]: z["kuerzel"].upper() for z in con.execute("SELECT id, kuerzel FROM lehrkraft")}
    sql = "SELECT * FROM anfrage WHERE projekt_id IN (%s)" % ",".join("?" * len(projekte))
    werte = list(projekte)
    if art in STATUS:
        sql += " AND art = ?"
        werte.append(art)
    if filter_ in STAENDE:
        sql += " AND stand = ?"
        werte.append(filter_)
    elif filter_ == "meine":
        sql += " AND zustaendig_id = ? AND stand != 'erledigt'"
        werte.append(konto["id"])
    elif filter_ != "alle":
        sql += " AND stand != 'erledigt'"
    if filter_ in ("erledigt", "alle"):
        sql += " ORDER BY geaendert DESC LIMIT 200"
    liste_ = []
    for a in con.execute(sql, werte).fetchall():
        d = _dict(a)
        p = projekte[a["projekt_id"]]
        d.update({"projekt_id": p["id"], "projekt": p["titel"], "klasse": p["klasse"], "zustaendig": kuerzel.get(a["zustaendig_id"]),
                  "ungelesen": _ungelesen(con, a, "l%d" % konto["id"], konto["kuerzel"]), "letzte": _letzte(con, a["id"], True)})
        liste_.append(d)
    return sorted(liste_, key=lambda d: (not d["ungelesen"], -_zeitwert(d["geaendert"])))   # Ungelesenes oben, dann das Neueste


def _zeitwert(zeit):
    return datetime.datetime.fromisoformat(zeit).timestamp()


def vorgaenge_team(con, pid):
    liste_ = []
    for a in con.execute("SELECT * FROM anfrage WHERE projekt_id = ? ORDER BY geaendert DESC", (pid,)).fetchall():
        d = _dict(a)
        d.update({"ungelesen": _ungelesen(con, a, "team"), "letzte": _letzte(con, a["id"], False)})
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
        d["zustaendig"] = {"kuerzel": z["kuerzel"].upper(), "name": z["name"]}
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
    return [{"id": d["id"], "titel": d["titel"], "projekt": d.get("projekt"), "nid": con.execute(sql, (d["id"],)).fetchone()[0] or 0,
             "text": d["letzte"]["text"] if d["letzte"] else d["text"]} for d in liste_ if d["ungelesen"]][:10]


def zaehler(con, konto):
    """Fuer das Menue: ungelesene Vorgaenge und offene (noch niemand dran), dazu die ungelesenen zum Melden."""
    liste_ = vorgaenge_lehrkraft(con, konto)
    return {"ungelesen": sum(1 for d in liste_ if d["ungelesen"]), "offen": sum(1 for d in liste_ if d["stand"] == "offen"),
            "neu": _neu(con, liste_, True)}


def team_zaehler(con, pid):
    """Fuer die Reiter des Teams: Vorgaenge mit neuer Antwort einer Lehrkraft."""
    liste_ = vorgaenge_team(con, pid)
    return {"ungelesen": sum(1 for d in liste_ if d["ungelesen"]), "neu": _neu(con, liste_, False)}


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
