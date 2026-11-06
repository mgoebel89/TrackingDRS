"""Hilfe-Knopf (Stufe J4): Ein Team ruft mit einem Tipp "Wir brauchen Hilfe", auf Wunsch mit dem Namen, wer fragt.
Die betreuenden Lehrkraefte sehen eine Reihe nach Eingang, das Team seine Nummer. "Ich komme" zeigt dem Team, wer
kommt, "Erledigt" nimmt die Meldung fuer alle heraus. Kein Text, kein Chat: Fragen mit Text bleiben die Anfragen.

Gerufen werden kann nur an einem Projekttag waehrend der Projektzeit (sonst ist niemand da). Offene Meldungen gelten
nur fuer den Tag, an dem sie gerufen wurden: am naechsten Tag sind sie verfallen.
"""
from . import db, termine
from .projekte import ProjektFehler

MAX_NAME = 120


def _heute():
    return db.jetzt()[:10]


def projektzeit(con, pid):
    """Laeuft gerade die Projektzeit dieses Projekts? Rueckgabe: der Projekttag (von, bis) oder None."""
    p = termine._projekt(con, pid)
    jetzt = db.jetzt()
    tag = db.heute()
    for t in termine.projekt_tage(con, p, tag, tag):
        if t["von"] <= jetzt[11:16] <= t["bis"]:
            return {"datum": t["datum"], "von": t["von"], "bis": t["bis"]}
    return None


def _offen_sql():
    return "erledigt IS NULL AND zurueckgezogen = 0 AND substr(erstellt, 1, 10) = ?"


def _offene(con, pid):
    return con.execute("SELECT * FROM hilfe WHERE projekt_id = ? AND " + _offen_sql() + " ORDER BY id DESC LIMIT 1",
                       (pid, _heute())).fetchone()


def _nummer(con, h):
    """Platz in der Reihe: unter den offenen Meldungen aller Projekte, die eine Lehrkraft mit diesem Projekt teilen."""
    ids = [z[0] for z in con.execute(
        "SELECT DISTINCT pl2.projekt_id FROM projekt_lehrkraft pl1 JOIN projekt_lehrkraft pl2 ON pl2.lehrkraft_id = pl1.lehrkraft_id "
        "WHERE pl1.projekt_id = ?", (h["projekt_id"],))] or [h["projekt_id"]]
    return con.execute("SELECT COUNT(*) FROM hilfe WHERE projekt_id IN (%s) AND id <= ? AND %s"
                       % (",".join("?" * len(ids)), _offen_sql()), ids + [h["id"], _heute()]).fetchone()[0]


def _kommt(con, h):
    if not h["kommt_id"]:
        return None
    z = con.execute("SELECT name FROM lehrkraft WHERE id = ?", (h["kommt_id"],)).fetchone()
    return z[0] if z else None


def team_stand(con, pid):
    h = _offene(con, pid)
    zeit = projektzeit(con, pid)
    return {"projektzeit": zeit,
            "meldung": {"id": h["id"], "nr": _nummer(con, h), "wer": h["wer"], "erstellt": h["erstellt"], "kommt": _kommt(con, h)} if h else None,
            "mitglieder": [("%s %s" % (m["vorname"], m["nachname"])).strip() for m in con.execute(
                "SELECT vorname, nachname FROM mitglied WHERE projekt_id = ? AND aktiv = 1 ORDER BY vorname, nachname", (pid,))]}


def team_aendern(con, pid, d):
    aktion = d.get("aktion")
    with db.transaktion(con):
        h = _offene(con, pid)
        if aktion == "rufen":
            if h is not None:
                raise ProjektFehler("Ihr habt schon Hilfe gerufen.")
            if projektzeit(con, pid) is None:
                raise ProjektFehler("Heute ist gerade keine Projektzeit. Stellt eine Rückfrage im Reiter „Anfragen“.")
            wer = str(d.get("wer") or "").strip()[:MAX_NAME]
            hid = con.execute("INSERT INTO hilfe (projekt_id, wer, erstellt) VALUES (?, ?, ?)", (pid, wer, db.jetzt())).lastrowid
            db.ereignis(con, pid, "team", "Team", "hilfe_gerufen", hilfe_id=hid, name=wer)
        elif aktion == "zurueckziehen":
            if h is None:
                raise ProjektFehler("Es ist keine Hilfe-Meldung offen.")
            con.execute("UPDATE hilfe SET zurueckgezogen = 1 WHERE id = ?", (h["id"],))
            db.ereignis(con, pid, "team", "Team", "hilfe_zurueck", hilfe_id=h["id"])
        else:
            raise ProjektFehler("Unbekannte Aktion.")
    return team_stand(con, pid)


def reihe(con, konto):
    """Offene Meldungen von heute aus den Projekten, die die Lehrkraft betreut, nach Eingang."""
    liste = []
    for i, h in enumerate(con.execute(
            "SELECT h.*, p.titel, p.klasse FROM hilfe h JOIN projekt p ON p.id = h.projekt_id "
            "JOIN projekt_lehrkraft pl ON pl.projekt_id = h.projekt_id WHERE pl.lehrkraft_id = ? AND p.archiviert = 0 AND "
            "h.erledigt IS NULL AND h.zurueckgezogen = 0 AND substr(h.erstellt, 1, 10) = ? ORDER BY h.id", (konto["id"], _heute())), 1):
        liste.append({"id": h["id"], "nr": i, "projekt_id": h["projekt_id"], "projekt": h["titel"], "klasse": h["klasse"], "wer": h["wer"],
                      "erstellt": h["erstellt"], "kommt": _kommt(con, h), "kommt_ich": h["kommt_id"] == konto["id"]})
    return liste


def lehrkraft_aendern(con, konto, hid, d):
    h = con.execute("SELECT h.* FROM hilfe h JOIN projekt_lehrkraft pl ON pl.projekt_id = h.projekt_id "
                    "WHERE h.id = ? AND (pl.lehrkraft_id = ? OR ?)", (hid, konto["id"], konto["rolle"] == "admin")).fetchone()
    if h is None or h["erledigt"] or h["zurueckgezogen"] or h["erstellt"][:10] != _heute():
        raise ProjektFehler("Diese Meldung ist nicht mehr offen.")
    aktion = d.get("aktion")
    with db.transaktion(con):
        if aktion == "kommen":   # umschalten: ich komme / doch nicht
            neu = None if h["kommt_id"] == konto["id"] else konto["id"]
            con.execute("UPDATE hilfe SET kommt_id = ?, kommt_zeit = ? WHERE id = ?", (neu, db.jetzt() if neu else None, hid))
        elif aktion == "erledigt":
            con.execute("UPDATE hilfe SET erledigt = ?, erledigt_von = ? WHERE id = ?", (db.jetzt(), konto["kuerzel"], hid))
            db.ereignis(con, h["projekt_id"], "lehrkraft", konto["kuerzel"], "hilfe_erledigt", hilfe_id=hid, name=h["wer"])
        else:
            raise ProjektFehler("Unbekannte Aktion.")
    return reihe(con, konto)
