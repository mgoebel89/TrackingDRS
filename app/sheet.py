"""Tracking-Sheet: Aufgaben je Phase, Wochenraster mit Plan (b), Endtermin (e) und Ampel (g/y/r), Haekchen "erledigt",
Probleme, Meilensteine, Versionen (Basisplan, Stand zum Buchungsschluss).

Alle Aenderungen laufen ueber aendern(): eine Aktion, eine Transaktion, ein Ereignis. Team und Lehrkraft nutzen
dieselben Aktionen; Unterschiede: nur Lehrkraefte duerfen Vorgabe-Aufgaben umbenennen/verwerfen und den Basisplan setzen.
"""
import datetime
import json

from . import db
from .projekte import ProjektFehler, montag

AMPELN = ("g", "y", "r")
MAX_TITEL = 120
MAX_TEXT = 500


def wochen(start, ende):
    """Montage aller Projektwochen als ISO-Text."""
    tag, letzter = datetime.date.fromisoformat(start), datetime.date.fromisoformat(ende)
    liste = []
    while tag <= letzter:
        liste.append(tag.isoformat())
        tag += datetime.timedelta(days=7)
    return liste


def diese_woche():
    return montag(db.heute()).isoformat()


def _text(wert, feld, laenge):
    wert = (wert or "").strip()
    if not wert:
        raise ProjektFehler("Bitte %s angeben." % feld)
    if len(wert) > laenge:
        raise ProjektFehler("Der Text ist zu lang (höchstens %d Zeichen)." % laenge)
    return wert


def _projekt(con, pid):
    p = con.execute("SELECT * FROM projekt WHERE id = ?", (pid,)).fetchone()
    if p is None:
        raise ProjektFehler("Dieses Projekt gibt es nicht.")
    return p


def _aufgabe(con, pid, aid):
    try:
        aid = int(aid)
    except (TypeError, ValueError):
        raise ProjektFehler("Ungültige Aufgabe.")
    a = con.execute("SELECT * FROM aufgabe WHERE id = ? AND projekt_id = ?", (aid, pid)).fetchone()
    if a is None:
        raise ProjektFehler("Diese Aufgabe gibt es nicht.")
    return a


def _mitglied(con, pid, mid, pflicht=True):
    if mid in (None, ""):
        if pflicht:
            raise ProjektFehler("Bitte einen Verantwortlichen aus dem Team wählen.")
        return None
    try:
        mid = int(mid)
    except (TypeError, ValueError):
        raise ProjektFehler("Ungültiges Teammitglied.")
    m = con.execute("SELECT * FROM mitglied WHERE id = ? AND projekt_id = ? AND aktiv = 1", (mid, pid)).fetchone()
    if m is None:
        raise ProjektFehler("Dieses Teammitglied gibt es nicht (mehr).")
    return m


def _woche(p, woche):
    if woche not in wochen(p["start"], p["ende"]):
        raise ProjektFehler("Diese Woche liegt nicht im Projektzeitraum.")
    return woche


# --- Lesen ---

def _zellen(con, pid):
    plan, ampel = {}, {}
    for z in con.execute("SELECT z.* FROM zelle z JOIN aufgabe a ON a.id = z.aufgabe_id WHERE a.projekt_id = ?", (pid,)):
        if z["plan"]:
            plan.setdefault(z["aufgabe_id"], []).append(z["woche"])
        if z["ampel"]:
            ampel.setdefault(z["aufgabe_id"], {})[z["woche"]] = z["ampel"]
    return plan, ampel


def stand(con, pid):
    """Nummer des letzten Ereignisses: aendert sich bei jeder Aenderung (fuer das Nachladen im Browser)."""
    zeile = con.execute("SELECT MAX(id) FROM ereignis WHERE projekt_id = ?", (pid,)).fetchone()
    return zeile[0] or 0


def lesen(con, pid):
    from . import termine   # hier, weil termine seinerseits sheet braucht
    p = _projekt(con, pid)
    plan, ampel = _zellen(con, pid)
    probleme = {}
    for pr in con.execute("SELECT pr.* FROM problem pr JOIN aufgabe a ON a.id = pr.aufgabe_id WHERE a.projekt_id = ? "
                          "ORDER BY pr.id DESC", (pid,)):
        probleme.setdefault(pr["aufgabe_id"], []).append({
            "woche": pr["woche"], "ampel": pr["ampel"], "problem": pr["problem"], "massnahme": pr["massnahme"],
            "verantwortlich_id": pr["verantwortlich_id"], "zeit": pr["zeit"], "wer": pr["wer"]})
    phasen = []
    for ph in con.execute("SELECT * FROM phase WHERE projekt_id = ? ORDER BY pos", (pid,)).fetchall():
        aufgaben = []
        for a in con.execute("SELECT * FROM aufgabe WHERE phase_id = ? ORDER BY pos, id", (ph["id"],)).fetchall():
            aufgaben.append({
                "id": a["id"], "titel": a["titel"], "aus_vorlage": bool(a["aus_vorlage"]),
                "verantwortlich_id": a["verantwortlich_id"], "verworfen": bool(a["verworfen"]),
                "ende": a["ende"], "ende_ursprung": a["ende_ursprung"], "erledigt": a["erledigt"],
                "plan": sorted(plan.get(a["id"], [])), "ampel": ampel.get(a["id"], {}),
                "probleme": probleme.get(a["id"], [])})
        phasen.append({"id": ph["id"], "name": ph["name"], "aufgaben": aufgaben})
    return {
        "projekt": {"id": p["id"], "titel": p["titel"], "klasse": p["klasse"], "start": p["start"], "ende": p["ende"],
                    "archiviert": bool(p["archiviert"])},
        "wochen": wochen(p["start"], p["ende"]),
        "projektwochen": termine.projektwochen(con, p),
        "jetzt": diese_woche(),
        "phasen": phasen,
        "mitglieder": [{"id": m["id"], "vorname": m["vorname"], "nachname": m["nachname"], "kuerzel": m["kuerzel"],
                        "aktiv": bool(m["aktiv"])}
                       for m in con.execute("SELECT * FROM mitglied WHERE projekt_id = ? ORDER BY nachname, vorname", (pid,))],
        "meilensteine": [{"id": m["id"], "woche": m["woche"], "titel": m["titel"], "verworfen": bool(m["verworfen"])}
                         for m in con.execute("SELECT * FROM meilenstein WHERE projekt_id = ? ORDER BY woche, id", (pid,))],
        "versionen": [{"id": v["id"], "art": v["art"], "name": v["name"], "zeit": v["zeit"], "aktiv": bool(v["aktiv"])}
                      for v in con.execute("SELECT id, art, name, zeit, aktiv FROM version WHERE projekt_id = ? "
                                           "ORDER BY id DESC", (pid,))],
        "stand": stand(con, pid),
    }


def momentaufnahme(con, pid):
    """Was eine Version festhaelt: Aufgaben mit Plan, Endtermin, Ampeln, Verantwortlichen; Meilensteine."""
    plan, ampel = _zellen(con, pid)
    aufgaben = {}
    for a in con.execute("SELECT * FROM aufgabe WHERE projekt_id = ?", (pid,)):
        aufgaben[str(a["id"])] = {"titel": a["titel"], "phase_id": a["phase_id"], "verantwortlich_id": a["verantwortlich_id"],
                                  "verworfen": bool(a["verworfen"]), "ende": a["ende"],
                                  "erledigt": a["erledigt"], "plan": sorted(plan.get(a["id"], [])), "ampel": ampel.get(a["id"], {})}
    meilensteine = {str(m["id"]): {"titel": m["titel"], "woche": m["woche"], "verworfen": bool(m["verworfen"])}
                    for m in con.execute("SELECT * FROM meilenstein WHERE projekt_id = ?", (pid,))}
    return {"aufgaben": aufgaben, "meilensteine": meilensteine}


def version_lesen(con, pid, vid):
    v = con.execute("SELECT * FROM version WHERE id = ? AND projekt_id = ?", (vid, pid)).fetchone()
    if v is None:
        raise ProjektFehler("Diese Version gibt es nicht.")
    return {"id": v["id"], "art": v["art"], "name": v["name"], "zeit": v["zeit"], "daten": json.loads(v["daten"])}


def version_anlegen(con, pid, art, name, wer_art, wer, woche=None):
    """Friert den aktuellen Stand ein. Ein neuer Basisplan loest den bisherigen ab (der bleibt als Version erhalten).
    Zum Buchungsschluss gibt es je Woche nur eine Version: gibt es sie schon, kommt None zurueck."""
    with db.transaktion(con):
        if art == "buchungsschluss" and con.execute("SELECT 1 FROM version WHERE projekt_id = ? AND art = ? AND woche = ?",
                                                    (pid, art, woche)).fetchone():
            return None
        if art == "basisplan":
            con.execute("UPDATE version SET aktiv = 0 WHERE projekt_id = ? AND art = 'basisplan'", (pid,))
        vid = con.execute("INSERT INTO version (projekt_id, art, name, zeit, woche, daten) VALUES (?, ?, ?, ?, ?, ?)",
                          (pid, art, name, db.jetzt(), woche,
                           json.dumps(momentaufnahme(con, pid), ensure_ascii=False))).lastrowid
        db.ereignis(con, pid, wer_art, wer, "version", version_id=vid, versionsart=art, name=name)
    return vid


def aufgabe_verlauf(con, pid, aid, anzahl=40):
    _aufgabe(con, pid, aid)
    return [{"zeit": e["zeit"], "wer_art": e["wer_art"], "wer": e["wer"], "art": e["art"], "daten": json.loads(e["daten"])}
            for e in con.execute("SELECT * FROM ereignis WHERE projekt_id = ? AND json_extract(daten, '$.aufgabe_id') = ? "
                                 "ORDER BY id DESC LIMIT ?", (pid, int(aid), anzahl))]


# --- Aendern ---

def _zelle_setzen(con, aid, woche, **werte):
    con.execute("INSERT OR IGNORE INTO zelle (aufgabe_id, woche) VALUES (?, ?)", (aid, woche))
    for spalte, wert in werte.items():
        con.execute("UPDATE zelle SET %s = ? WHERE aufgabe_id = ? AND woche = ?" % spalte, (wert, aid, woche))
    con.execute("DELETE FROM zelle WHERE aufgabe_id = ? AND woche = ? AND plan = 0 AND ampel IS NULL", (aid, woche))


def aendern(con, pid, wer_art, wer, d):
    """Fuehrt eine Aktion aus (d['aktion']). wer_art: 'team' oder 'lehrkraft', wer: 'Team' bzw. Kuerzel."""
    p = _projekt(con, pid)
    if p["archiviert"]:
        raise ProjektFehler("Das Projekt ist archiviert und kann nicht mehr geändert werden.")
    lehrkraft = wer_art == "lehrkraft"
    aktion = d.get("aktion")
    with db.transaktion(con):
        def ereignis(art, **daten):
            db.ereignis(con, pid, wer_art, wer, art, **daten)

        if aktion == "aufgabe_neu":
            ph = con.execute("SELECT * FROM phase WHERE id = ? AND projekt_id = ?", (d.get("phase_id"), pid)).fetchone()
            if ph is None:
                raise ProjektFehler("Diese Phase gibt es nicht.")
            titel = _text(d.get("titel"), "einen Namen für die Aufgabe", MAX_TITEL)
            pos = con.execute("SELECT COALESCE(MAX(pos), -1) + 1 FROM aufgabe WHERE phase_id = ?", (ph["id"],)).fetchone()[0]
            aid = con.execute("INSERT INTO aufgabe (projekt_id, phase_id, pos, titel, erstellt) VALUES (?, ?, ?, ?, ?)",
                              (pid, ph["id"], pos, titel, db.jetzt())).lastrowid
            ereignis("aufgabe_neu", aufgabe_id=aid, titel=titel, phase=ph["name"])
            return {"aufgabe_id": aid}

        if aktion == "meilenstein_neu":
            woche = _woche(p, d.get("woche"))
            titel = _text(d.get("titel"), "einen Namen für den Meilenstein", MAX_TITEL)
            mid = con.execute("INSERT INTO meilenstein (projekt_id, woche, titel, erstellt) VALUES (?, ?, ?, ?)",
                              (pid, woche, titel, db.jetzt())).lastrowid
            ereignis("meilenstein_neu", meilenstein_id=mid, titel=titel, woche=woche)
            return {}

        if aktion in ("meilenstein_aendern", "meilenstein_verwerfen"):
            m = con.execute("SELECT * FROM meilenstein WHERE id = ? AND projekt_id = ?", (d.get("meilenstein_id"), pid)).fetchone()
            if m is None:
                raise ProjektFehler("Diesen Meilenstein gibt es nicht.")
            if aktion == "meilenstein_verwerfen":
                verworfen = bool(d.get("verworfen", True))
                con.execute("UPDATE meilenstein SET verworfen = ? WHERE id = ?", (1 if verworfen else 0, m["id"]))
                ereignis("meilenstein_verworfen" if verworfen else "meilenstein_zurueck", meilenstein_id=m["id"], titel=m["titel"])
                return {}
            woche = _woche(p, d.get("woche", m["woche"]))
            titel = _text(d.get("titel", m["titel"]), "einen Namen für den Meilenstein", MAX_TITEL)
            con.execute("UPDATE meilenstein SET woche = ?, titel = ? WHERE id = ?", (woche, titel, m["id"]))
            ereignis("meilenstein_geaendert", meilenstein_id=m["id"], titel=titel, woche=woche, woche_alt=m["woche"])
            return {}

        a = _aufgabe(con, pid, d.get("aufgabe_id"))
        aid = a["id"]
        if a["verworfen"] and aktion != "verwerfen":
            raise ProjektFehler("Diese Aufgabe ist verworfen. Stelle sie zuerst wieder her.")

        if aktion == "titel":
            if a["aus_vorlage"] and not lehrkraft:
                raise ProjektFehler("Vorgegebene Aufgaben kann nur die Lehrkraft umbenennen.")
            titel = _text(d.get("titel"), "einen Namen für die Aufgabe", MAX_TITEL)
            if titel != a["titel"]:
                con.execute("UPDATE aufgabe SET titel = ? WHERE id = ?", (titel, aid))
                ereignis("titel", aufgabe_id=aid, titel=titel, alt=a["titel"])
        elif aktion == "verantwortlich":
            m = _mitglied(con, pid, d.get("mitglied_id"))
            if m["id"] != a["verantwortlich_id"]:
                alt = con.execute("SELECT kuerzel FROM mitglied WHERE id = ?", (a["verantwortlich_id"],)).fetchone()
                con.execute("UPDATE aufgabe SET verantwortlich_id = ? WHERE id = ?", (m["id"], aid))
                ereignis("verantwortlich", aufgabe_id=aid, titel=a["titel"], kuerzel=m["kuerzel"],
                         name="%s %s" % (m["vorname"], m["nachname"]), alt=alt[0] if alt else None)
        elif aktion == "erledigt":
            erledigt = bool(d.get("erledigt", True))
            if erledigt != bool(a["erledigt"]):
                con.execute("UPDATE aufgabe SET erledigt = ? WHERE id = ?", (db.jetzt() if erledigt else None, aid))
                ereignis("erledigt" if erledigt else "nicht_erledigt", aufgabe_id=aid, titel=a["titel"])
        elif aktion == "verwerfen":
            if a["aus_vorlage"] and not lehrkraft:
                raise ProjektFehler("Vorgegebene Aufgaben kann nur die Lehrkraft verwerfen.")
            verworfen = bool(d.get("verworfen", True))
            con.execute("UPDATE aufgabe SET verworfen = ? WHERE id = ?", (1 if verworfen else 0, aid))
            ereignis("verworfen" if verworfen else "wiederhergestellt", aufgabe_id=aid, titel=a["titel"])
        elif aktion == "verschieben":
            richtung = -1 if d.get("richtung") == -1 else 1
            nachbar = con.execute(
                "SELECT * FROM aufgabe WHERE phase_id = ? AND pos %s ? ORDER BY pos %s LIMIT 1"
                % (("<", "DESC") if richtung < 0 else (">", "ASC")), (a["phase_id"], a["pos"])).fetchone()
            if nachbar is not None:
                con.execute("UPDATE aufgabe SET pos = ? WHERE id = ?", (nachbar["pos"], aid))
                con.execute("UPDATE aufgabe SET pos = ? WHERE id = ?", (a["pos"], nachbar["id"]))
                ereignis("reihenfolge", aufgabe_id=aid, titel=a["titel"])
        elif aktion == "plan":
            liste = d.get("wochen")
            if not isinstance(liste, list) or not liste or len(liste) > 80:
                raise ProjektFehler("Ungültige Wochen.")
            wert = 1 if d.get("wert", True) else 0
            geaendert = []
            for woche in liste:
                _woche(p, woche)
                bisher = con.execute("SELECT plan FROM zelle WHERE aufgabe_id = ? AND woche = ?", (aid, woche)).fetchone()
                if (bisher[0] if bisher else 0) != wert:
                    _zelle_setzen(con, aid, woche, plan=wert)
                    geaendert.append(woche)
            if geaendert:
                ereignis("plan", aufgabe_id=aid, titel=a["titel"], wochen=geaendert, wert=bool(wert))
        elif aktion == "ende":
            woche = d.get("woche")
            if woche is not None:
                _woche(p, woche)
            if woche != a["ende"]:
                ursprung = a["ende_ursprung"] or woche
                con.execute("UPDATE aufgabe SET ende = ?, ende_ursprung = ? WHERE id = ?", (woche, ursprung, aid))
                ereignis("ende", aufgabe_id=aid, titel=a["titel"], woche=woche, alt=a["ende"])
        elif aktion == "ampel":
            woche = _woche(p, d.get("woche"))
            if woche > diese_woche():
                raise ProjektFehler("Eine Ampel gibt es nur für die laufende und vergangene Wochen.")
            ampel = d.get("ampel")
            if ampel is not None and ampel not in AMPELN:
                raise ProjektFehler("Unbekannte Ampel.")
            bisher = con.execute("SELECT ampel FROM zelle WHERE aufgabe_id = ? AND woche = ?", (aid, woche)).fetchone()
            bisher = bisher[0] if bisher else None
            daten = {}
            if ampel in ("y", "r"):
                problem = _text(d.get("problem"), "das Problem", MAX_TEXT)
                massnahme = _text(d.get("massnahme"), "eine Korrekturmaßnahme", MAX_TEXT)
                m = _mitglied(con, pid, d.get("verantwortlich_id"))
                con.execute("INSERT INTO problem (aufgabe_id, woche, ampel, problem, massnahme, verantwortlich_id, zeit, wer_art, wer) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (aid, woche, ampel, problem, massnahme, m["id"], db.jetzt(), wer_art, wer))
                daten = {"problem": problem, "massnahme": massnahme, "verantwortlich": m["kuerzel"]}
            if ampel != bisher or daten:
                _zelle_setzen(con, aid, woche, ampel=ampel)
                ereignis("ampel", aufgabe_id=aid, titel=a["titel"], woche=woche, ampel=ampel, alt=bisher, **daten)
        else:
            raise ProjektFehler("Unbekannte Aktion.")
    return {}


def basisplan_setzen(con, pid, wer):
    name = "Basisplan vom %s" % datetime.date.fromisoformat(db.jetzt()[:10]).strftime("%d.%m.%Y")
    return version_anlegen(con, pid, "basisplan", name, "lehrkraft", wer)
