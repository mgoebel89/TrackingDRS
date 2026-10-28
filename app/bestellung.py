"""Bestelllisten: Das Team sammelt Positionen jederzeit und reicht die Liste einmal je Einreichfenster ein (sie wird mit
Uhrzeit eingefroren). Die Lehrkraft entscheidet je Position, woher der Artikel kommt: bestellen, SchulLager (Lagerort als
Text), Firma eines Schuelers (nur Vermerk), ersetzen (Ersatz eintragen oder mit Hinweis zurueck an das Team) oder
ablehnen (mit Kommentar). Nach dem Stichtag gibt es die Sammelbestellung je Lieferant ueber alle Teams.

Einreichfenster legt die Lehrkraft fest: von (Datum) bis Stichtag (Datum und Uhrzeit), fuer alle eigenen Projekte, eine
Klasse oder als Sonderfenster fuer ein einzelnes Team. Preise sind nur zur Information: keine Summen, kein Budget.
Eine nicht eingereichte Liste bleibt erhalten und gilt fuer das naechste Fenster. Nichts wird geloescht.
"""
import csv
import datetime
import io

from . import db
from .projekte import ProjektFehler

ENTSCHEIDUNGEN = ("bestellen", "lager", "firma", "ersetzen", "ablehnen")
STATUS_WEG = {"bestellen": ("bestellt", "geliefert", "ausgegeben"), "lager": ("ausgegeben",)}
FELDER = ("artikel", "bestellnr", "menge", "preis", "lieferant", "aufgabe_id", "begruendung")


def _text(wert, feld, laenge, pflicht=False):
    wert = str(wert or "").strip()
    if pflicht and not wert:
        raise ProjektFehler("Bitte %s angeben." % feld)
    if len(wert) > laenge:
        raise ProjektFehler("Der Text ist zu lang (höchstens %d Zeichen)." % laenge)
    return wert


def _menge(wert):
    try:
        n = int(wert)
    except (TypeError, ValueError):
        raise ProjektFehler("Bitte eine Menge (ganze Zahl) angeben.")
    if not 1 <= n <= 9999:
        raise ProjektFehler("Die Menge muss zwischen 1 und 9999 liegen.")
    return n


def _projekt(con, pid):
    p = con.execute("SELECT * FROM projekt WHERE id = ?", (pid,)).fetchone()
    if p is None:
        raise ProjektFehler("Dieses Projekt gibt es nicht.")
    return p


# --- Fenster ---

def _fenster(f):
    return {"id": f["id"], "lehrkraft_id": f["lehrkraft_id"], "klasse": f["klasse"], "projekt_id": f["projekt_id"],
            "von": f["von"], "bis": f["bis"], "aktiv": bool(f["aktiv"])}


def fenster_fuer(con, p):
    """Aktive Fenster, die fuer ein Projekt gelten: Sonderfenster des Projekts, oder ein Fenster einer betreuenden
    Lehrkraft fuer alle ihre Projekte bzw. fuer die Klasse des Projekts."""
    return [_fenster(f) for f in con.execute(
        "SELECT * FROM bestellfenster WHERE aktiv = 1 AND (projekt_id = ? OR (projekt_id IS NULL AND lehrkraft_id IN "
        "(SELECT lehrkraft_id FROM projekt_lehrkraft WHERE projekt_id = ?))) ORDER BY von, bis", (p["id"], p["id"]))
        if f["projekt_id"] == p["id"] or not f["klasse"] or f["klasse"].strip().lower() == p["klasse"].strip().lower()]


def lage(con, p):
    """Offenes Fenster (in dem das Projekt noch nicht eingereicht hat) und naechstes Fenster."""
    jetzt = db.jetzt()
    heute = jetzt[:10]
    eingereicht = {z[0] for z in con.execute("SELECT fenster_id FROM bestellliste WHERE projekt_id = ? AND fenster_id IS NOT NULL",
                                              (p["id"],))}
    offen = naechstes = None
    for f in fenster_fuer(con, p):
        if f["von"] <= heute and jetzt < f["bis"] and f["id"] not in eingereicht:
            if offen is None or f["bis"] < offen["bis"]:
                offen = f
        elif f["von"] > heute and (naechstes is None or f["von"] < naechstes["von"]):
            naechstes = f
    return {"offen": offen, "naechstes": naechstes}


def fenster_anlegen(con, konto, d):
    von = _datum(d.get("von"), "den Beginn")
    bis = _zeitpunkt(d.get("bis"))
    if bis[:10] < von:
        raise ProjektFehler("Der Stichtag liegt vor dem Beginn.")
    projekt_id = d.get("projekt_id") or None
    klasse = _text(d.get("klasse"), "eine Klasse", 30)
    if projekt_id is not None:
        if not con.execute("SELECT 1 FROM projekt_lehrkraft WHERE projekt_id = ? AND lehrkraft_id = ?",
                           (int(projekt_id), konto["id"])).fetchone() and konto["rolle"] != "admin":
            raise ProjektFehler("Dieses Projekt betreust du nicht.")
        klasse = ""
    with db.transaktion(con):
        fid = con.execute("INSERT INTO bestellfenster (lehrkraft_id, klasse, projekt_id, von, bis, erstellt) VALUES (?, ?, ?, ?, ?, ?)",
                          (konto["id"], klasse, projekt_id, von, bis, db.jetzt())).lastrowid
        if projekt_id is not None:   # Sonderfenster: steht im Verlauf des Projekts
            db.ereignis(con, int(projekt_id), "lehrkraft", konto["kuerzel"], "sonderfenster", fenster_id=fid, von=von, bis=bis)
    return fid


def fenster_aendern(con, konto, fid, d):
    f = con.execute("SELECT * FROM bestellfenster WHERE id = ?", (fid,)).fetchone()
    if f is None or (f["lehrkraft_id"] != konto["id"] and konto["rolle"] != "admin"):
        raise ProjektFehler("Dieses Fenster gibt es nicht.")
    with db.transaktion(con):
        if d.get("aktiv") is False:
            con.execute("UPDATE bestellfenster SET aktiv = 0 WHERE id = ?", (fid,))
        else:
            bis = _zeitpunkt(d.get("bis") or f["bis"])
            von = _datum(d.get("von") or f["von"], "den Beginn")
            if bis[:10] < von:
                raise ProjektFehler("Der Stichtag liegt vor dem Beginn.")
            con.execute("UPDATE bestellfenster SET von = ?, bis = ? WHERE id = ?", (von, bis, fid))


def _datum(wert, feld):
    try:
        return datetime.date.fromisoformat(str(wert or "")[:10]).isoformat()
    except ValueError:
        raise ProjektFehler("Bitte %s angeben." % feld)


def _zeitpunkt(wert):
    """Stichtag als 'YYYY-MM-DDTHH:MM:00' (ohne Uhrzeit: 23:59)."""
    text = str(wert or "").strip().replace(" ", "T")
    try:
        if len(text) == 10:
            return datetime.datetime.fromisoformat(text + "T23:59").isoformat()
        return datetime.datetime.fromisoformat(text[:16]).replace(second=0).isoformat()
    except ValueError:
        raise ProjektFehler("Bitte einen Stichtag (Datum und Uhrzeit) angeben.")


# --- Listen und Positionen ---

def _position(z, aufgaben=None):
    weg = z["entscheidung"]
    if weg == "ersetzen":
        weg = z["ersatz_weg"] if z["ersatz_artikel"] else "ersatz_gesucht"
    return {"id": z["id"], "artikel": z["artikel"], "bestellnr": z["bestellnr"], "menge": z["menge"], "preis": z["preis"],
            "lieferant": z["lieferant"], "aufgabe_id": z["aufgabe_id"], "aufgabe": (aufgaben or {}).get(z["aufgabe_id"]),
            "begruendung": z["begruendung"], "gestrichen": bool(z["gestrichen"]), "entscheidung": z["entscheidung"],
            "menge_genehmigt": z["menge_genehmigt"], "kommentar": z["kommentar"], "ersatz_artikel": z["ersatz_artikel"],
            "ersatz_bestellnr": z["ersatz_bestellnr"], "ersatz_lieferant": z["ersatz_lieferant"], "ersatz_weg": z["ersatz_weg"],
            "weg": weg, "status": z["status"], "aus_position": z["aus_position"]}


def _aufgaben(con, pid):
    return {a["id"]: a["titel"] for a in con.execute("SELECT id, titel FROM aufgabe WHERE projekt_id = ?", (pid,))}


def _liste(con, l, aufgaben):
    f = con.execute("SELECT * FROM bestellfenster WHERE id = ?", (l["fenster_id"],)).fetchone() if l["fenster_id"] else None
    return {"id": l["id"], "eingereicht": l["eingereicht"], "geprueft": l["geprueft"], "geprueft_von": l["geprueft_von"],
            "fenster": _fenster(f) if f else None,
            "positionen": [_position(z, aufgaben) for z in con.execute("SELECT * FROM position WHERE liste_id = ? ORDER BY id", (l["id"],))]}


def _sammelliste(con, pid, anlegen=False):
    l = con.execute("SELECT * FROM bestellliste WHERE projekt_id = ? AND eingereicht IS NULL ORDER BY id LIMIT 1", (pid,)).fetchone()
    if l is None and anlegen:
        con.execute("INSERT INTO bestellliste (projekt_id) VALUES (?)", (pid,))
        l = _sammelliste(con, pid)
    return l


def team_sicht(con, pid):
    p = _projekt(con, pid)
    aufgaben = _aufgaben(con, pid)
    sammel = _sammelliste(con, pid)
    return {"sammel": _liste(con, sammel, aufgaben) if sammel else {"id": None, "positionen": []},
            "lage": lage(con, p),
            "eingereicht": [_liste(con, l, aufgaben) for l in con.execute(
                "SELECT * FROM bestellliste WHERE projekt_id = ? AND eingereicht IS NOT NULL ORDER BY eingereicht DESC", (pid,))],
            "aufgaben": [{"id": i, "titel": t} for i, t in aufgaben.items()]}


def _felder(con, pid, d, alt=None):
    w = {k: (alt[k] if alt is not None else None) for k in FELDER}
    if "artikel" in d or alt is None:
        w["artikel"] = _text(d.get("artikel"), "einen Artikel", 200, pflicht=True)
    for k, laenge in (("bestellnr", 80), ("preis", 30), ("lieferant", 300), ("begruendung", 500)):
        if k in d or alt is None:
            w[k] = _text(d.get(k), k, laenge)
    if "menge" in d or alt is None:
        w["menge"] = _menge(d.get("menge", 1))
    if "aufgabe_id" in d or alt is None:
        aid = d.get("aufgabe_id") or None
        if aid is not None and not con.execute("SELECT 1 FROM aufgabe WHERE id = ? AND projekt_id = ?", (aid, pid)).fetchone():
            raise ProjektFehler("Diese Aufgabe gibt es nicht.")
        w["aufgabe_id"] = aid
    return w


def _pos_holen(con, pid, posid):
    try:
        z = con.execute("SELECT po.*, l.projekt_id, l.eingereicht, l.fenster_id FROM position po JOIN bestellliste l ON l.id = po.liste_id "
                        "WHERE po.id = ? AND l.projekt_id = ?", (int(posid), pid)).fetchone()
    except (TypeError, ValueError):
        z = None
    if z is None:
        raise ProjektFehler("Diese Position gibt es nicht.")
    return z


def team_aendern(con, pid, d):
    p = _projekt(con, pid)
    if p["archiviert"]:
        raise ProjektFehler("Das Projekt ist archiviert.")
    aktion = d.get("aktion")
    jetzt = db.jetzt()
    with db.transaktion(con):
        def ereignis(art, **daten):
            db.ereignis(con, pid, "team", "Team", art, **daten)

        if aktion == "position_neu":
            w = _felder(con, pid, d)
            l = _sammelliste(con, pid, anlegen=True)
            posid = con.execute("INSERT INTO position (liste_id, %s, erstellt) VALUES (?, %s, ?)" % (", ".join(FELDER), ", ".join("?" * len(FELDER))),
                                [l["id"]] + [w[k] for k in FELDER] + [jetzt]).lastrowid
            ereignis("position_neu", position_id=posid, artikel=w["artikel"], menge=w["menge"])
            return {"position_id": posid}
        if aktion in ("position_aendern", "position_streichen"):
            z = _pos_holen(con, pid, d.get("position_id"))
            if z["eingereicht"]:
                raise ProjektFehler("Die Liste ist schon eingereicht und kann nicht mehr geändert werden.")
            if aktion == "position_streichen":
                gestrichen = bool(d.get("gestrichen", True))
                con.execute("UPDATE position SET gestrichen = ? WHERE id = ?", (1 if gestrichen else 0, z["id"]))
                ereignis("position_gestrichen" if gestrichen else "position_zurueck", position_id=z["id"], artikel=z["artikel"])
            else:
                w = _felder(con, pid, d, z)
                con.execute("UPDATE position SET %s WHERE id = ?" % ", ".join("%s = ?" % k for k in FELDER), [w[k] for k in FELDER] + [z["id"]])
                ereignis("position_geaendert", position_id=z["id"], artikel=w["artikel"], menge=w["menge"])
            return {}
        if aktion == "uebernehmen":   # abgelehnt oder "Ersatz gesucht": in die naechste Liste
            z = _pos_holen(con, pid, d.get("position_id"))
            if not (z["entscheidung"] == "ablehnen" or (z["entscheidung"] == "ersetzen" and not z["ersatz_artikel"])):
                raise ProjektFehler("Nur abgelehnte Positionen oder solche mit „Ersatz gesucht“ lassen sich übernehmen.")
            l = _sammelliste(con, pid, anlegen=True)
            if con.execute("SELECT 1 FROM position WHERE liste_id = ? AND aus_position = ? AND gestrichen = 0", (l["id"], z["id"])).fetchone():
                raise ProjektFehler("Diese Position steht schon in der nächsten Liste.")
            posid = con.execute("INSERT INTO position (liste_id, %s, aus_position, erstellt) VALUES (?, %s, ?, ?)"
                                % (", ".join(FELDER), ", ".join("?" * len(FELDER))),
                                [l["id"]] + [z[k] for k in FELDER] + [z["id"], jetzt]).lastrowid
            ereignis("position_neu", position_id=posid, artikel=z["artikel"], menge=z["menge"], uebernommen=True)
            return {"position_id": posid}
        if aktion == "einreichen":
            offen = lage(con, p)["offen"]
            if offen is None:
                raise ProjektFehler("Gerade ist kein Einreichfenster offen.")
            l = _sammelliste(con, pid)
            n = con.execute("SELECT COUNT(*) FROM position WHERE liste_id = ? AND gestrichen = 0", (l["id"],)).fetchone()[0] if l else 0
            if not n:
                raise ProjektFehler("Die Liste ist leer.")
            con.execute("UPDATE bestellliste SET fenster_id = ?, eingereicht = ? WHERE id = ?", (offen["id"], jetzt, l["id"]))
            ereignis("liste_eingereicht", liste_id=l["id"], positionen=n, fenster_id=offen["id"])
            return {}
        raise ProjektFehler("Unbekannte Aktion.")


def pruefen(con, pid, wer, d):
    """Lehrkraft: Entscheidung je Position und Status (bestellt, geliefert, ausgegeben)."""
    aktion = d.get("aktion")
    with db.transaktion(con):
        z = _pos_holen(con, pid, d.get("position_id"))
        if not z["eingereicht"]:
            raise ProjektFehler("Die Liste ist noch nicht eingereicht.")
        if aktion == "entscheiden":
            e = d.get("entscheidung")
            if e not in ENTSCHEIDUNGEN:
                raise ProjektFehler("Unbekannte Entscheidung.")
            kommentar = _text(d.get("kommentar"), "einen Kommentar", 500)
            if e == "ablehnen" and not kommentar:
                raise ProjektFehler("Bitte kurz begründen, warum die Position abgelehnt wird.")
            menge = _menge(d["menge_genehmigt"]) if d.get("menge_genehmigt") not in (None, "") else None
            ersatz = (None, None, None, None)
            if e == "ersetzen":
                artikel = _text(d.get("ersatz_artikel"), "den Ersatzartikel", 200)
                if artikel:
                    weg = d.get("ersatz_weg") if d.get("ersatz_weg") in ("bestellen", "lager") else "bestellen"
                    ersatz = (artikel, _text(d.get("ersatz_bestellnr"), "", 80), _text(d.get("ersatz_lieferant"), "", 300), weg)
                elif not kommentar:
                    raise ProjektFehler("Bitte einen Ersatz eintragen oder dem Team einen Hinweis geben.")
            con.execute("UPDATE position SET entscheidung = ?, menge_genehmigt = ?, kommentar = ?, ersatz_artikel = ?, ersatz_bestellnr = ?, "
                        "ersatz_lieferant = ?, ersatz_weg = ?, status = NULL WHERE id = ?", (e, menge, kommentar) + ersatz + (z["id"],))
            db.ereignis(con, pid, "lehrkraft", wer, "position_entschieden", position_id=z["id"], artikel=z["artikel"], entscheidung=e,
                        kommentar=kommentar, ersatz=ersatz[0])
            offen = con.execute("SELECT COUNT(*) FROM position WHERE liste_id = ? AND gestrichen = 0 AND entscheidung IS NULL",
                                (z["liste_id"],)).fetchone()[0]
            con.execute("UPDATE bestellliste SET geprueft = ?, geprueft_von = ? WHERE id = ?",
                        (db.jetzt() if offen == 0 else None, wer if offen == 0 else None, z["liste_id"]))
        elif aktion == "status":
            weg = _position(z)["weg"]
            status = d.get("status") or None
            if status is not None and status not in STATUS_WEG.get(weg, ()):
                raise ProjektFehler("Diesen Status gibt es für diese Position nicht.")
            con.execute("UPDATE position SET status = ? WHERE id = ?", (status, z["id"]))
            db.ereignis(con, pid, "lehrkraft", wer, "position_status", position_id=z["id"], artikel=z["artikel"], status=status)
        else:
            raise ProjektFehler("Unbekannte Aktion.")


# --- Uebersicht der Lehrkraft ---

def _meine_projekte(con, konto):
    return con.execute("SELECT p.* FROM projekt p JOIN projekt_lehrkraft pl ON pl.projekt_id = p.id WHERE pl.lehrkraft_id = ? "
                       "AND p.archiviert = 0 ORDER BY p.klasse, p.titel", (konto["id"],)).fetchall()


def uebersicht(con, konto):
    """Eigene Fenster (laufende, kommende, die letzten 60 Tage) mit dem Stand je Team, dazu die Listen in Pruefung."""
    jetzt = db.jetzt()
    grenze = (datetime.date.fromisoformat(jetzt[:10]) - datetime.timedelta(days=60)).isoformat()
    projekte = _meine_projekte(con, konto)
    fenster = []
    for f in con.execute("SELECT * FROM bestellfenster WHERE lehrkraft_id = ? AND aktiv = 1 AND bis >= ? ORDER BY von DESC",
                         (konto["id"], grenze)):
        f = _fenster(f)
        teams = []
        for p in projekte:
            if f["projekt_id"] not in (None, p["id"]) or (f["projekt_id"] is None and f["klasse"]
                                                          and f["klasse"].strip().lower() != p["klasse"].strip().lower()):
                continue
            l = con.execute("SELECT * FROM bestellliste WHERE projekt_id = ? AND fenster_id = ?", (p["id"], f["id"])).fetchone()
            if l is not None:
                offen = con.execute("SELECT COUNT(*) FROM position WHERE liste_id = ? AND gestrichen = 0 AND entscheidung IS NULL",
                                    (l["id"],)).fetchone()[0]
                n = con.execute("SELECT COUNT(*) FROM position WHERE liste_id = ? AND gestrichen = 0", (l["id"],)).fetchone()[0]
                teams.append({"projekt_id": p["id"], "titel": p["titel"], "stand": "geprueft" if l["geprueft"] else "eingereicht",
                              "liste_id": l["id"], "eingereicht": l["eingereicht"], "positionen": n, "offen": offen})
            else:
                s = _sammelliste(con, p["id"])
                n = con.execute("SELECT COUNT(*) FROM position WHERE liste_id = ? AND gestrichen = 0", (s["id"],)).fetchone()[0] if s else 0
                teams.append({"projekt_id": p["id"], "titel": p["titel"], "stand": "sammelt" if n else "leer", "positionen": n})
        f["teams"] = teams
        f["laeuft"] = f["von"] <= jetzt[:10] and jetzt < f["bis"]
        f["vorbei"] = jetzt >= f["bis"]
        if f["projekt_id"]:
            f["projekt"] = next((p["titel"] for p in projekte if p["id"] == f["projekt_id"]), "?")
        fenster.append(f)
    return {"fenster": fenster, "klassen": sorted({p["klasse"] for p in projekte}),
            "projekte": [{"id": p["id"], "titel": p["titel"], "klasse": p["klasse"]} for p in projekte]}


def liste_lesen(con, konto, liste_id):
    l = con.execute("SELECT l.* FROM bestellliste l JOIN projekt_lehrkraft pl ON pl.projekt_id = l.projekt_id "
                    "WHERE l.id = ? AND (pl.lehrkraft_id = ? OR ?)", (liste_id, konto["id"], konto["rolle"] == "admin")).fetchone()
    if l is None:
        raise ProjektFehler("Diese Liste gibt es nicht.")
    d = _liste(con, l, _aufgaben(con, l["projekt_id"]))
    d["projekt_id"] = l["projekt_id"]
    d["titel"] = _projekt(con, l["projekt_id"])["titel"]
    return d


def sammelbestellung(con, konto, fid):
    """Alle Positionen eines Fensters, die bestellt werden (auch Ersatzartikel), je Lieferant; gleiche Artikel
    (Bestellnummer, sonst Name) zusammengefasst."""
    f = con.execute("SELECT * FROM bestellfenster WHERE id = ?", (fid,)).fetchone()
    if f is None or (f["lehrkraft_id"] != konto["id"] and konto["rolle"] != "admin"):
        raise ProjektFehler("Dieses Fenster gibt es nicht.")
    gruppen = {}
    for z in con.execute("SELECT po.*, p.titel AS team FROM position po JOIN bestellliste l ON l.id = po.liste_id "
                         "JOIN projekt p ON p.id = l.projekt_id WHERE l.fenster_id = ? AND po.gestrichen = 0 ORDER BY po.id", (fid,)):
        pos = _position(z)
        if pos["weg"] != "bestellen":
            continue
        ersatz = z["entscheidung"] == "ersetzen"
        artikel = z["ersatz_artikel"] if ersatz else z["artikel"]
        nr = (z["ersatz_bestellnr"] if ersatz else z["bestellnr"]) or ""
        lieferant = ((z["ersatz_lieferant"] if ersatz else z["lieferant"]) or "").strip()
        menge = z["menge_genehmigt"] or z["menge"]
        g = gruppen.setdefault(lieferant.lower(), {"lieferant": lieferant, "zeilen": {}})
        schluessel = nr.strip().lower() or artikel.strip().lower()
        zeile = g["zeilen"].setdefault(schluessel, {"artikel": artikel, "bestellnr": nr, "menge": 0, "preis": z["preis"] if not ersatz else "",
                                                    "teams": [], "positionen": []})
        zeile["menge"] += menge
        if z["team"] not in zeile["teams"]:
            zeile["teams"].append(z["team"])
        zeile["positionen"].append(z["id"])
    ergebnis = []
    for g in sorted(gruppen.values(), key=lambda g: (not g["lieferant"], g["lieferant"].lower())):
        ergebnis.append({"lieferant": g["lieferant"], "zeilen": sorted(g["zeilen"].values(), key=lambda z: z["artikel"].lower())})
    return {"fenster": _fenster(f), "lieferanten": ergebnis}


def sammelbestellung_csv(daten):
    """CSV fuer Excel: Semikolon, UTF-8 mit BOM, damit Umlaute stimmen."""
    puffer = io.StringIO()
    w = csv.writer(puffer, delimiter=";")
    w.writerow(["Lieferant", "Artikel", "Bestellnummer", "Menge", "Preis (nur Info)", "Teams"])
    for g in daten["lieferanten"]:
        for z in g["zeilen"]:
            w.writerow([g["lieferant"] or "ohne Lieferant", z["artikel"], z["bestellnr"], z["menge"], z["preis"], ", ".join(z["teams"])])
    return ("﻿" + puffer.getvalue()).encode("utf-8")


def warnungen(con, pid):
    p = _projekt(con, pid)
    jetzt = db.jetzt()
    liste_ = []
    l = lage(con, p)
    s = _sammelliste(con, pid)
    if l["offen"] and s and con.execute("SELECT 1 FROM position WHERE liste_id = ? AND gestrichen = 0", (s["id"],)).fetchone():
        stichtag = datetime.datetime.fromisoformat(l["offen"]["bis"])
        if stichtag - datetime.datetime.fromisoformat(jetzt) <= datetime.timedelta(days=1):
            liste_.append({"art": "bestellfenster_schliesst", "stufe": "hinweis",
                           "text": "Die Bestellliste ist noch nicht eingereicht. Stichtag: %s." % stichtag.strftime("%d.%m., %H:%M")})
    for z in con.execute("SELECT l.id, l.eingereicht FROM bestellliste l JOIN bestellfenster f ON f.id = l.fenster_id "
                         "WHERE l.projekt_id = ? AND l.geprueft IS NULL AND f.bis <= ?", (pid, jetzt)):
        liste_.append({"art": "listen_warten", "stufe": "intern", "liste_id": z["id"],
                       "text": "Bestellliste vom %s ist noch nicht fertig geprüft." % datetime.date.fromisoformat(z["eingereicht"][:10]).strftime("%d.%m.")})
    return liste_
