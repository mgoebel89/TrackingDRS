"""Besprechungstafel (Smartboard): Post-its in drei Zonen und Striche vom Stift, je Besprechung.

Die Tafel ist 1600 x 900 Einheiten gross (der Browser skaliert). Zonen: "Seit letztem Mal" links (die
Kurzzusammenfassung als Post-its), "Skizzen & Ideen" in der Mitte (auch live von den Geraeten des Teams) und "Ergebnis"
rechts mit Absprachen, Auftraegen und Meilensteinen. Ein Post-it, das in eine Ergebnis-Zone gezogen wird, wird sofort
zu diesem Ergebnis. Beim Abschliessen (besprechung.py) wird die Tafel eingefroren und steht im Protokoll.
Lehrernotizen und Warnungen zu anderen Teams erscheinen nie auf der Tafel.

Post-its haben einen Schluessel: "e<id>" fuer Eintraege, "p..."/"a..." fuer Probleme und Aenderungen aus der
Kurzzusammenfassung (nur Anzeige). Fotos liegen als Datei im Ordner bilder/ des Datenordners.
"""
import base64
import binascii
import hashlib
import json
import os
import secrets
import threading
import time

from . import besprechung, db
from .projekte import ProjektFehler

BREITE, HOEHE = 1600, 900
GRENZE_IDEEN, GRENZE_ERGEBNIS = 450, 1060
ERGEBNIS_ZONEN = {"absprachen": "absprache", "auftraege": "auftrag", "meilensteine": "meilenstein"}
MAX_STRICHE = 1500
MAX_PUNKTE = 3000
MAX_BILD = 1400 * 1024   # Base64 + JSON muss unter MAX_BODY des Servers (2 MB) bleiben
FARBEN = ("#1d2433", "#00639C", "#D4005E", "#3d8b00", "#e07b00")

# Wer gerade da ist (nur im Speicher): Tafel offen (Lehrkraft) und Geraete des Teams, je Projekt mit Zeitpunkt
_ANWESEND = {}
_SPERRE = threading.Lock()


def zone_bei(x, y):
    if x < GRENZE_IDEEN:
        return "seit"
    if x < GRENZE_ERGEBNIS:
        return "ideen"
    return "absprachen" if y < HOEHE / 3 else "auftraege" if y < 2 * HOEHE / 3 else "meilensteine"


def _schluessel(praefix, text):
    return praefix + hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def melden(pid, wer):
    """Anwesenheit: wer = 'tafel' (Lehrkraft hat die Tafel offen) oder eine Geraete-Kennung des Teams."""
    with _SPERRE:
        _ANWESEND.setdefault(pid, {})[str(wer)[:40]] = time.monotonic()


def anwesend(pid, sekunden=12):
    jetzt = time.monotonic()
    with _SPERRE:
        da = {k: t for k, t in _ANWESEND.get(pid, {}).items() if jetzt - t < sekunden}
        _ANWESEND[pid] = da
    return {"tafel": "tafel" in da, "geraete": len([k for k in da if k != "tafel"])}


# --- Lesen ---

def _tafel(con, bid):
    t = con.execute("SELECT * FROM tafel WHERE besprechung_id = ?", (bid,)).fetchone() if bid else None
    if t is None:
        return {"striche": [], "positionen": {}, "stand": 0}
    return {"striche": json.loads(t["striche"]), "positionen": json.loads(t["positionen"]), "stand": t["stand"]}


def _zettel(schluessel, art, zone, text, **mehr):
    z = {"key": schluessel, "art": art, "zone": zone, "text": text}
    z.update(mehr)
    return z


def postits(con, pid, woche):
    """Alle Post-its der Tafel einer (offenen) Besprechung, mit ihrer Zone."""
    z = besprechung._zeile(con, pid, woche)
    bid = z["id"] if z else None
    zus = besprechung.zusammenfassung(con, pid, woche)
    liste = []
    for e in zus["auftraege"]:
        if e["besprechung_id"] != bid:
            liste.append(_zettel("e%d" % e["id"], "auftrag", "seit", e["text"], eintrag_id=e["id"], frist=e["frist"],
                                 erledigt=e["erledigt"], ueberfaellig=e["ueberfaellig"], verantwortlich=e["verantwortlich"]))
    for p in zus["probleme"]:
        liste.append(_zettel(_schluessel("p", p["aufgabe"] + p["problem"]), "problem", "seit", p["problem"],
                             aufgabe=p["aufgabe"], ampel=p["ampel"], massnahme=p["massnahme"], seit=p["seit"]))
    termin = besprechung._termin(con, pid, woche)
    for e in zus["fragen"]:
        # was am Besprechungstag (live von den Geraeten) kommt, gehoert in die Mitte; Vorbereitetes nach links
        live = e["besprechung_id"] == bid and (e["art"] == "idee" or (termin and e["erstellt"][:10] == termin["datum"]))
        zone = "ideen" if live else "seit"
        liste.append(_zettel("e%d" % e["id"], e["art"], zone, e["text"], eintrag_id=e["id"], wer_art=e["wer_art"],
                             erstellt=e["erstellt"], bild=e.get("bild")))
    for e in con.execute("SELECT * FROM eintrag WHERE projekt_id = ? AND art IN ('frage', 'thema', 'idee') AND verworfen = 0 "
                         "AND erledigt > ? ORDER BY id", (pid, zus["seit"])):
        liste.append(_zettel("e%d" % e["id"], e["art"], "seit", e["text"], eintrag_id=e["id"], erledigt=e["erledigt"],
                             bild=e["bild"]))
    for a in zus["aenderungen"]:
        liste.append(_zettel(_schluessel("a", a["text"]), "aenderung", "seit", a["text"]))
    if bid:
        kuerzel = besprechung._kuerzel(con, pid)
        for e in con.execute("SELECT * FROM eintrag WHERE besprechung_id = ? AND art IN ('absprache', 'auftrag', 'meilenstein') "
                             "AND verworfen = 0 ORDER BY id", (bid,)):
            zone = {"absprache": "absprachen", "auftrag": "auftraege", "meilenstein": "meilensteine"}[e["art"]]
            liste.append(_zettel("e%d" % e["id"], e["art"], zone, e["text"], eintrag_id=e["id"], frist=e["frist"],
                                 erledigt=e["erledigt"], verantwortlich=kuerzel.get(e["verantwortlich_id"])))
    return liste


def stand(con, pid, bid):
    letzte = con.execute("SELECT MAX(id) FROM ereignis WHERE projekt_id = ?", (pid,)).fetchone()[0] or 0
    return "%d.%d" % (_tafel(con, bid)["stand"], letzte)


def lesen(con, pid):
    """Die Tafel der aktuellen Besprechung (fuer die Lehrkraft am Board)."""
    woche = besprechung.aktuelle_woche(con, pid)
    z = besprechung._zeile(con, pid, woche)
    bid = z["id"] if z else None
    t = _tafel(con, bid)
    p = con.execute("SELECT titel, klasse FROM projekt WHERE id = ?", (pid,)).fetchone()
    return {"projekt": {"id": pid, "titel": p["titel"], "klasse": p["klasse"]}, "woche": woche,
            "termin": besprechung._termin(con, pid, woche), "postits": postits(con, pid, woche), "striche": t["striche"],
            "positionen": t["positionen"], "stand": stand(con, pid, bid), "anwesend": anwesend(pid),
            "mitglieder": [{"id": m["id"], "name": m["vorname"] + " " + m["nachname"]}
                           for m in con.execute("SELECT * FROM mitglied WHERE projekt_id = ? AND aktiv = 1 ORDER BY nachname", (pid,))]}


def momentaufnahme(con, pid, woche):
    """Was beim Abschliessen eingefroren wird (vor dem Setzen von 'abgeschlossen' aufrufen)."""
    z = besprechung._zeile(con, pid, woche)
    t = _tafel(con, z["id"] if z else None)
    return {"postits": postits(con, pid, woche), "striche": t["striche"], "positionen": t["positionen"]}


def eingefroren(con, pid, bid):
    z = con.execute("SELECT * FROM besprechung WHERE id = ? AND projekt_id = ? AND abgeschlossen IS NOT NULL", (bid, pid)).fetchone()
    if z is None:
        raise ProjektFehler("Diese Tafel gibt es nicht.")
    proto = json.loads(z["protokoll"] or "{}")
    tafel = proto.get("tafel") or {"postits": [], "striche": [], "positionen": {}}
    tafel.update({"woche": z["woche"], "termin": proto.get("termin"), "abgeschlossen": z["abgeschlossen"]})
    return tafel


# --- Aendern ---

def _tafel_zeile(con, pid, woche):
    b = besprechung._anlegen(con, pid, woche)
    if b["abgeschlossen"]:
        raise ProjektFehler("Diese Besprechung ist schon abgeschlossen.")
    con.execute("INSERT OR IGNORE INTO tafel (besprechung_id) VALUES (?)", (b["id"],))
    return b, con.execute("SELECT * FROM tafel WHERE besprechung_id = ?", (b["id"],)).fetchone()


def _speichern(con, bid, **werte):
    werte["aktualisiert"] = db.jetzt()
    con.execute("UPDATE tafel SET %s, stand = stand + 1 WHERE besprechung_id = ?" % ", ".join("%s = ?" % k for k in werte),
                list(werte.values()) + [bid])


def _zahl(wert, kleinst, groesst):
    try:
        return max(kleinst, min(groesst, int(round(float(wert)))))
    except (TypeError, ValueError):
        raise ProjektFehler("Ungültige Position.")


def _eintrag_id(schluessel):
    if isinstance(schluessel, str) and schluessel.startswith("e") and schluessel[1:].isdigit():
        return int(schluessel[1:])
    return None


def aendern(con, pid, wer, d):
    """Aktionen der Lehrkraft an der Tafel. Ergebnisse laufen ueber besprechung.aendern (gleiche Regeln, gleiche Ereignisse)."""
    woche = d.get("woche") or besprechung.aktuelle_woche(con, pid)
    aktion = d.get("aktion")

    def bespr(**daten):
        return besprechung.aendern(con, pid, "lehrkraft", wer, dict(daten, woche=woche))

    if aktion in ("strich", "strich_weg", "position"):
        with db.transaktion(con):
            b, t = _tafel_zeile(con, pid, woche)
            if aktion == "strich":
                striche = json.loads(t["striche"])
                if len(striche) >= MAX_STRICHE:
                    raise ProjektFehler("Die Tafel ist voll. Bitte einige Striche wegradieren.")
                punkte = d.get("punkte")
                if not isinstance(punkte, list) or not punkte or len(punkte) > MAX_PUNKTE:
                    raise ProjektFehler("Ungültiger Strich.")
                strich = {"id": max([s["id"] for s in striche] or [0]) + 1,
                          "farbe": d.get("farbe") if d.get("farbe") in FARBEN else FARBEN[0],
                          "breite": _zahl(d.get("breite", 4), 1, 40),
                          "punkte": [[_zahl(p[0], 0, BREITE), _zahl(p[1], 0, HOEHE), round(min(max(float(p[2]) if len(p) > 2 else .5, 0), 1), 2)]
                                     for p in punkte if isinstance(p, list) and len(p) >= 2]}
                striche.append(strich)
                _speichern(con, b["id"], striche=json.dumps(striche, separators=(",", ":")))
                return {"strich_id": strich["id"]}
            if aktion == "strich_weg":
                ids = {int(i) for i in d.get("ids") or [] if str(i).isdigit()}
                striche = [s for s in json.loads(t["striche"]) if s["id"] not in ids]
                _speichern(con, b["id"], striche=json.dumps(striche, separators=(",", ":")))
                return {}
            positionen = json.loads(t["positionen"])
            schluessel = str(d.get("key") or "")[:20]
            if not schluessel:
                raise ProjektFehler("Ungültiges Post-it.")
            positionen[schluessel] = [_zahl(d.get("x"), 0, BREITE), _zahl(d.get("y"), 0, HOEHE)]
            _speichern(con, b["id"], positionen=json.dumps(positionen))
            return {}

    if aktion in ("erledigt", "verwerfen"):
        eid = _eintrag_id(d.get("key"))
        if eid is None:
            raise ProjektFehler("Dieses Post-it stammt aus der Zusammenfassung und lässt sich hier nicht ändern.")
        return bespr(aktion=aktion, eintrag_id=eid, erledigt=d.get("erledigt", True))

    if aktion in ("postit", "ablegen"):
        zone = d.get("zone") if d.get("zone") in ("seit", "ideen", "absprachen", "auftraege", "meilensteine") else "ideen"
        text = (d.get("text") or "").strip()
        eid = _eintrag_id(d.get("key")) if aktion == "ablegen" else None
        neu = None
        if zone == "meilensteine":
            if eid is not None:
                e = besprechung._eintrag_holen(con, pid, eid)
                if e["art"] == "meilenstein":
                    return {}
                text = text or e["text"]
            bespr(aktion="meilenstein", titel=text, meilenstein_woche=d.get("meilenstein_woche"))
            neu = con.execute("SELECT MAX(id) FROM eintrag WHERE projekt_id = ? AND art = 'meilenstein'", (pid,)).fetchone()[0]
            if eid is not None:   # die Vorlage ist damit erledigt
                bespr(aktion="erledigt" if e["art"] in ("frage", "thema", "auftrag") else "verwerfen", eintrag_id=eid)
        elif eid is not None:
            _umwandeln(con, pid, wer, woche, eid, zone, d)
            neu = eid
        elif aktion == "postit" or zone in ("absprachen", "auftraege"):
            # neues Post-it, oder eines aus der Zusammenfassung (Problem, Aenderung) wird zum Ergebnis
            art = ERGEBNIS_ZONEN.get(zone, "idee")
            neu = bespr(aktion="eintrag_neu", art=art, text=text, frist=d.get("frist"),
                        verantwortlich_id=d.get("verantwortlich_id"))["eintrag_id"]
        # sonst: Post-it aus der Zusammenfassung nur verschoben
        if neu is not None and d.get("x") is not None:
            aendern(con, pid, wer, {"aktion": "position", "woche": woche, "key": "e%d" % neu, "x": d["x"], "y": d["y"]})
        elif d.get("x") is not None and d.get("key"):
            aendern(con, pid, wer, {"aktion": "position", "woche": woche, "key": d["key"], "x": d["x"], "y": d["y"]})
        return {"key": "e%d" % neu if neu else d.get("key")}
    raise ProjektFehler("Unbekannte Aktion.")


def _umwandeln(con, pid, wer, woche, eid, zone, d):
    """Ein vorhandenes Post-it wird zur Absprache, zum Auftrag oder (zurueck in Seit/Ideen) wieder zur Idee."""
    e = besprechung._eintrag_holen(con, pid, eid)
    if e["verworfen"]:
        raise ProjektFehler("Dieses Post-it ist verworfen.")
    if e["art"] == "meilenstein":
        raise ProjektFehler("Meilensteine ändert man im Tracking-Sheet.")
    with db.transaktion(con):
        b = besprechung._anlegen(con, pid, woche)
        if b["abgeschlossen"]:
            raise ProjektFehler("Diese Besprechung ist schon abgeschlossen.")
        if zone in ("absprachen", "auftraege"):
            art = ERGEBNIS_ZONEN[zone]
            frist = besprechung._frist(d.get("frist")) if art == "auftrag" else None
            if art == "auftrag" and not frist:
                raise ProjektFehler("Ein Auftrag braucht eine Frist.")
            if e["art"] == art and e["besprechung_id"] == b["id"]:
                return
            con.execute("UPDATE eintrag SET art = ?, frist = ?, verantwortlich_id = ?, besprechung_id = ?, erledigt = NULL WHERE id = ?",
                        (art, frist, d.get("verantwortlich_id") or e["verantwortlich_id"], b["id"], eid))
        elif e["art"] in ("absprache", "auftrag") and e["besprechung_id"] == b["id"]:
            art = "idee"   # aus dem Ergebnis zurueckgezogen
            con.execute("UPDATE eintrag SET art = 'idee', frist = NULL WHERE id = ?", (eid,))
        else:
            return
        db.ereignis(con, pid, "lehrkraft", wer, "eintrag_umgewandelt", eintrag_id=eid, text=e["text"], alt=e["art"], eintragsart=art)


# --- Vom Team: Post-its und Fotos ---

def bild_speichern(daten_dir, inhalt_b64):
    """Foto vom Geraet des Teams (der Browser verkleinert vorher). Nur JPEG/PNG. Rueckgabe: Dateiname ohne Endung."""
    try:
        roh = base64.b64decode(inhalt_b64 or "", validate=True)
    except (binascii.Error, ValueError):
        raise ProjektFehler("Das Foto konnte nicht gelesen werden.")
    if len(roh) > MAX_BILD:
        raise ProjektFehler("Das Foto ist zu groß.")
    if not (roh.startswith(b"\xff\xd8\xff") or roh.startswith(b"\x89PNG\r\n\x1a\n")):
        raise ProjektFehler("Bitte ein Foto (JPEG oder PNG) schicken.")
    ordner = os.path.join(daten_dir, "bilder")
    os.makedirs(ordner, exist_ok=True)
    name = secrets.token_hex(12)
    with open(os.path.join(ordner, name + (".jpg" if roh[:2] == b"\xff\xd8" else ".png")), "wb") as f:
        f.write(roh)
    return name


def bild_pfad(con, daten_dir, pid, name):
    """Datei eines Fotos, nur wenn es zu diesem Projekt gehoert."""
    if not (isinstance(name, str) and len(name) == 24 and all(c in "0123456789abcdef" for c in name)):
        return None, None
    if not (con.execute("SELECT 1 FROM eintrag WHERE projekt_id = ? AND bild = ?", (pid, name)).fetchone()
            or con.execute("SELECT 1 FROM anfrage WHERE projekt_id = ? AND bild = ?", (pid, name)).fetchone()
            or con.execute("SELECT 1 FROM datei WHERE projekt_id = ? AND name = ?", (pid, name)).fetchone()
            or con.execute("SELECT 1 FROM nachricht n JOIN anfrage a ON a.id = n.anfrage_id WHERE a.projekt_id = ? AND n.bild = ?",
                           (pid, name)).fetchone()):
        return None, None
    for endung, typ in ((".jpg", "image/jpeg"), (".png", "image/png"), (".pdf", "application/pdf")):
        pfad = os.path.join(daten_dir, "bilder", name + endung)
        if os.path.exists(pfad):
            return pfad, typ
    return None, None


def team_senden(con, pid, daten_dir, d):
    """Post-it oder Foto vom Geraet des Teams, landet in "Skizzen & Ideen" der aktuellen Besprechung."""
    art = d.get("art") if d.get("art") in ("idee", "frage") else "idee"
    if d.get("bild"):
        name = bild_speichern(daten_dir, d["bild"])
        text = (d.get("text") or "").strip()[:200] or "Foto"
        ergebnis = besprechung.aendern(con, pid, "team", "Team", {"aktion": "eintrag_neu", "art": "idee", "text": text})
        con.execute("UPDATE eintrag SET bild = ? WHERE id = ?", (name, ergebnis["eintrag_id"]))
        return ergebnis
    return besprechung.aendern(con, pid, "team", "Team", {"aktion": "eintrag_neu", "art": art, "text": d.get("text")})
