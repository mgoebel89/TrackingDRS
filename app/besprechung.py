"""Besprechungen: Vorbereitung durch das Team, Kurzzusammenfassung (ohne KI aus den Daten), Lehrernotizen, Ergebnis
(Absprachen, Auftraege mit Frist, Meilensteine) und Abschliessen mit Protokoll.

Eine Besprechung gehoert zu einem Projekt und einer Woche. Aktuell ist die frueheste Woche mit gebuchtem Termin (ab vor
sechs Tagen), deren Besprechung noch nicht abgeschlossen ist; ohne Buchung die laufende Woche. Die Zeile entsteht beim
ersten Eintrag. Eintraege (Post-its) haengen am Projekt: offene Auftraege, Fragen und Ideen wandern so von selbst in die
naechste Besprechung. Lehrernotizen sieht das Team nie, auch nicht im Protokoll. Nichts wird geloescht, nur verworfen.
"""
import datetime
import json

from . import cockpit, db, sheet, termine
from .projekte import ProjektFehler, montag

TAG = datetime.timedelta(days=1)
MAX_TEXT = 500
MAX_LANG = 4000
TEAM_ARTEN = ("frage", "thema", "idee")
LEHRKRAFT_ARTEN = ("frage", "thema", "idee", "auftrag", "absprache")
AMPEL = {"g": "grün", "y": "gelb", "r": "rot"}


def _heute():
    return datetime.date.fromisoformat(db.jetzt()[:10])


def _projekt(con, pid):
    p = con.execute("SELECT * FROM projekt WHERE id = ?", (pid,)).fetchone()
    if p is None:
        raise ProjektFehler("Dieses Projekt gibt es nicht.")
    return p


def _text(wert, feld, laenge=MAX_TEXT, pflicht=True):
    wert = (wert or "").strip()
    if pflicht and not wert:
        raise ProjektFehler("Bitte %s angeben." % feld)
    if len(wert) > laenge:
        raise ProjektFehler("Der Text ist zu lang (höchstens %d Zeichen)." % laenge)
    return wert


def _zeile(con, pid, woche):
    return con.execute("SELECT * FROM besprechung WHERE projekt_id = ? AND woche = ?", (pid, woche)).fetchone()


def _anlegen(con, pid, woche):
    """Zeile der Besprechung holen oder anlegen (in der Transaktion des Aufrufers)."""
    con.execute("INSERT OR IGNORE INTO besprechung (projekt_id, woche) VALUES (?, ?)", (pid, woche))
    return _zeile(con, pid, woche)


def aktuelle_woche(con, pid):
    heute = _heute()
    for b in con.execute("SELECT woche FROM buchung WHERE projekt_id = ? AND aktiv = 1 AND datum >= ? ORDER BY datum, uhrzeit",
                         (pid, (heute - 6 * TAG).isoformat())).fetchall():
        z = _zeile(con, pid, b["woche"])
        if z is None or not z["abgeschlossen"]:
            return b["woche"]
    diese = montag(heute)
    z = _zeile(con, pid, diese.isoformat())
    return diese.isoformat() if z is None or not z["abgeschlossen"] else (diese + 7 * TAG).isoformat()


def _termin(con, pid, woche):
    b = con.execute("SELECT datum, uhrzeit FROM buchung WHERE projekt_id = ? AND woche = ? AND aktiv = 1", (pid, woche)).fetchone()
    return {"datum": b["datum"], "uhrzeit": b["uhrzeit"]} if b else None


def _kuerzel(con, pid):
    return {m["id"]: m["kuerzel"] for m in con.execute("SELECT id, kuerzel FROM mitglied WHERE projekt_id = ?", (pid,))}


def _eintrag(e, kuerzel):
    heute = _heute().isoformat()
    return {"id": e["id"], "art": e["art"], "text": e["text"], "frist": e["frist"], "erledigt": e["erledigt"],
            "verantwortlich": kuerzel.get(e["verantwortlich_id"]), "verantwortlich_id": e["verantwortlich_id"],
            "ueberfaellig": e["art"] == "auftrag" and not e["erledigt"] and bool(e["frist"]) and e["frist"] < heute,
            "erstellt": e["erstellt"], "wer_art": e["wer_art"], "wer": e["wer"], "besprechung_id": e["besprechung_id"],
            "bild": e["bild"]}


def _seit(con, pid, woche):
    """Zeitpunkt der letzten abgeschlossenen Besprechung vor dieser Woche (sonst Projektbeginn)."""
    z = con.execute("SELECT MAX(abgeschlossen) FROM besprechung WHERE projekt_id = ? AND abgeschlossen IS NOT NULL AND woche < ?",
                    (pid, woche)).fetchone()[0]
    return z or _projekt(con, pid)["erstellt"]


# --- Kurzzusammenfassung ---

def _aenderungen(con, pid, seit):
    """Was sich seit der letzten Besprechung am Tracking-Sheet getan hat, zusammengefasst je Aufgabe."""
    ende, ampel, liste = {}, {}, []
    planaenderungen = 0
    for e in con.execute("SELECT * FROM ereignis WHERE projekt_id = ? AND zeit > ? AND art IN (%s) ORDER BY id"
                         % ",".join("?" * len(cockpit.SHEET)), [pid, seit] + list(cockpit.SHEET)):
        d = json.loads(e["daten"])
        art = e["art"]
        if art == "aufgabe_neu":
            liste.append({"art": "neu", "text": "Neue Aufgabe „%s“" % d["titel"]})
        elif art == "ende":
            alt = ende.get(d["aufgabe_id"], {"alt": d.get("alt")})["alt"]
            ende[d["aufgabe_id"]] = {"alt": alt, "neu": d.get("woche"), "titel": d["titel"]}
        elif art == "ampel":
            ampel[(d["aufgabe_id"], d["woche"])] = d
        elif art in ("verworfen", "erledigt", "wiederhergestellt"):
            text = {"verworfen": "Verworfen", "erledigt": "Erledigt", "wiederhergestellt": "Wiederhergestellt"}[art]
            liste.append({"art": art, "text": "%s: „%s“" % (text, d["titel"])})
        elif art in ("meilenstein_neu", "meilenstein_geaendert"):
            liste.append({"art": "meilenstein", "text": "Meilenstein „%s“ in %s" % (d["titel"], termine.kw_text(d["woche"]))})
        elif art == "meilenstein_verworfen":
            liste.append({"art": "meilenstein", "text": "Meilenstein „%s“ verworfen" % d["titel"]})
        elif art == "plan":
            planaenderungen += 1
    for x in ende.values():
        if x["alt"] != x["neu"]:
            liste.append({"art": "ende", "text": "„%s“: Ende %s → %s" % (
                x["titel"], termine.kw_text(x["alt"]) if x["alt"] else "keins", termine.kw_text(x["neu"]) if x["neu"] else "keins")})
    for (_aid, woche), d in sorted(ampel.items(), key=lambda kv: kv[0][1]):
        if d.get("ampel") in ("y", "r"):
            liste.append({"art": "ampel", "text": "„%s“: %s %s%s" % (d["titel"], termine.kw_text(woche), AMPEL[d["ampel"]],
                                                                     " – " + d["problem"] if d.get("problem") else "")})
    if planaenderungen:
        liste.append({"art": "plan", "text": "%d Planänderung%s im Raster" % (planaenderungen, "" if planaenderungen == 1 else "en")})
    return liste


def _probleme(con, pid, diese, kuerzel):
    liste = []
    for a in con.execute("SELECT * FROM aufgabe WHERE projekt_id = ? AND verworfen = 0 AND erledigt IS NULL ORDER BY pos, id", (pid,)):
        z = con.execute("SELECT woche, ampel FROM zelle WHERE aufgabe_id = ? AND ampel IS NOT NULL AND woche <= ? ORDER BY woche DESC",
                        (a["id"], diese)).fetchall()
        if not z or z[0]["ampel"] not in ("y", "r"):
            continue
        seit = z[0]["woche"]
        for x in z[1:]:
            if x["ampel"] not in ("y", "r"):
                break
            seit = x["woche"]
        pr = con.execute("SELECT * FROM problem WHERE aufgabe_id = ? ORDER BY id DESC LIMIT 1", (a["id"],)).fetchone()
        liste.append({"aufgabe": a["titel"], "ampel": z[0]["ampel"], "seit": seit,
                      "problem": pr["problem"] if pr else "", "massnahme": pr["massnahme"] if pr else "",
                      "verantwortlich": kuerzel.get(pr["verantwortlich_id"]) if pr else None})
    return liste


def _basisplan(con, pid):
    v = con.execute("SELECT daten FROM version WHERE projekt_id = ? AND art = 'basisplan' AND aktiv = 1", (pid,)).fetchone()
    if v is None:
        return None
    basis, jetzt = json.loads(v["daten"])["aufgaben"], sheet.momentaufnahme(con, pid)["aufgaben"]
    spaeter = sum(1 for i, a in jetzt.items() if i in basis and a["ende"] and basis[i]["ende"] and a["ende"] > basis[i]["ende"])
    frueher = sum(1 for i, a in jetzt.items() if i in basis and a["ende"] and basis[i]["ende"] and a["ende"] < basis[i]["ende"])
    neu = sum(1 for i, a in jetzt.items() if i not in basis and not a["verworfen"])
    weg = sum(1 for i, a in jetzt.items() if a["verworfen"] and not (i in basis and basis[i]["verworfen"]))
    teile = []
    if spaeter:
        teile.append("%d Endtermin%s später" % (spaeter, "" if spaeter == 1 else "e"))
    if frueher:
        teile.append("%d Endtermin%s früher" % (frueher, "" if frueher == 1 else "e"))
    if neu:
        teile.append("%d Aufgabe%s neu" % (neu, "" if neu == 1 else "n"))
    if weg:
        teile.append("%d verworfen" % weg)
    return ", ".join(teile) if teile else "wie im Basisplan"


def zusammenfassung(con, pid, woche):
    """Die Kurzzusammenfassung fuer die Besprechung einer Woche, berechnet aus den Daten."""
    p = _projekt(con, pid)
    heute = _heute()
    diese = montag(heute).isoformat()
    seit = _seit(con, pid, woche)
    kuerzel = _kuerzel(con, pid)
    gesamt = cockpit.gesamt_je_woche(con, pid)
    bisher = sorted(w for w in gesamt if w <= diese)
    frueher = [z["woche"] for z in con.execute("SELECT woche FROM besprechung WHERE projekt_id = ? AND abgeschlossen IS NOT NULL "
                                              "AND woche < ? ORDER BY woche DESC LIMIT 4", (pid, woche))]
    z = _zeile(con, pid, woche)
    ms = con.execute("SELECT * FROM meilenstein WHERE projekt_id = ? AND verworfen = 0 AND woche >= ? ORDER BY woche, id LIMIT 1",
                     (pid, diese)).fetchone()
    ausblick = None
    if ms:
        wochen = termine.projektwochen(con, p)
        n = len([w for w in wochen if diese <= w <= ms["woche"]]) if wochen is not None else \
            (datetime.date.fromisoformat(ms["woche"]) - montag(heute)).days // 7 + 1
        ausblick = {"titel": ms["titel"], "woche": ms["woche"], "projektwochen": n}
    auftraege = [_eintrag(e, kuerzel) for e in con.execute(
        "SELECT * FROM eintrag WHERE projekt_id = ? AND art = 'auftrag' AND verworfen = 0 AND (erledigt IS NULL OR erledigt > ?) "
        "ORDER BY erledigt IS NOT NULL, frist, id", (pid, seit))]
    return {
        "seit": seit,
        "ampel": {"woche": bisher[-1], "ampel": gesamt[bisher[-1]]} if bisher else None,
        "verlauf": [{"woche": w, "ampel": gesamt.get(w)} for w in reversed(frueher)],
        "aenderungen": _aenderungen(con, pid, seit),
        "probleme": _probleme(con, pid, diese, kuerzel),
        "auftraege": auftraege,
        "vorbereitung": z["vorbereitung"] if z else "", "vorbereitet": z["vorbereitet"] if z else None,
        "fragen": [_eintrag(e, kuerzel) for e in con.execute(
            "SELECT * FROM eintrag WHERE projekt_id = ? AND art IN ('frage', 'thema', 'idee') AND verworfen = 0 AND erledigt IS NULL "
            "ORDER BY id", (pid,))],
        "ausblick": ausblick,
        "basisplan": _basisplan(con, pid),
    }


# --- Lesen ---

def _protokolle(con, pid, lehrkraft):
    liste = []
    for z in con.execute("SELECT * FROM besprechung WHERE projekt_id = ? AND abgeschlossen IS NOT NULL ORDER BY woche DESC", (pid,)):
        p = json.loads(z["protokoll"] or "{}")
        p.update({"id": z["id"], "woche": z["woche"], "abgeschlossen": z["abgeschlossen"], "von": z["abgeschlossen_von"],
                  "tafel": bool(p.get("tafel") and (p["tafel"]["striche"] or p["tafel"]["positionen"]))})   # Tafel einzeln laden
        if lehrkraft:
            p["notizen"] = z["notizen"]
        else:
            p.pop("zusammenfassung", None)
        liste.append(p)
    return liste


def lesen(con, pid, lehrkraft=False):
    """Aktuelle Besprechung mit offenen Eintraegen und den Protokollen. Die Lehrkraft bekommt dazu Kurzzusammenfassung,
    Lehrernotizen und die Ergebnisse dieser Besprechung."""
    woche = aktuelle_woche(con, pid)
    z = _zeile(con, pid, woche)
    kuerzel = _kuerzel(con, pid)
    seit = _seit(con, pid, woche)
    offen = [_eintrag(e, kuerzel) for e in con.execute(
        "SELECT * FROM eintrag WHERE projekt_id = ? AND verworfen = 0 AND art IN ('frage', 'thema', 'idee', 'auftrag') "
        "AND (erledigt IS NULL OR erledigt > ?) ORDER BY art, id", (pid, seit))]
    d = {
        "woche": woche, "termin": _termin(con, pid, woche),
        "vorbereitung": z["vorbereitung"] if z else "", "vorbereitet": z["vorbereitet"] if z else None,
        "eintraege": offen,
        "mitglieder": [{"id": m["id"], "kuerzel": m["kuerzel"], "name": m["vorname"] + " " + m["nachname"]}
                       for m in con.execute("SELECT * FROM mitglied WHERE projekt_id = ? AND aktiv = 1 ORDER BY nachname", (pid,))],
        "protokolle": _protokolle(con, pid, lehrkraft),
        "projektwochen": termine.projektwochen(con, _projekt(con, pid)),
    }
    if lehrkraft:
        d["zusammenfassung"] = zusammenfassung(con, pid, woche)
        d["notizen"] = z["notizen"] if z else ""
        d["ergebnis"] = [_eintrag(e, kuerzel) for e in con.execute(
            "SELECT * FROM eintrag WHERE besprechung_id = ? AND art IN ('absprache', 'auftrag', 'meilenstein') AND verworfen = 0 "
            "ORDER BY id", (z["id"],))] if z else []
    return d


# --- Aendern ---

def _eintrag_holen(con, pid, eid):
    try:
        e = con.execute("SELECT * FROM eintrag WHERE id = ? AND projekt_id = ?", (int(eid), pid)).fetchone()
    except (TypeError, ValueError):
        e = None
    if e is None:
        raise ProjektFehler("Diesen Eintrag gibt es nicht.")
    return e


def _frist(wert):
    if not wert:
        return None
    try:
        return datetime.date.fromisoformat(str(wert)[:10]).isoformat()
    except ValueError:
        raise ProjektFehler("Bitte eine gültige Frist angeben.")


def aendern(con, pid, wer_art, wer, d):
    """Eine Aktion (d['aktion']) auf der aktuellen Besprechung. wer_art: 'team' oder 'lehrkraft'."""
    p = _projekt(con, pid)
    if p["archiviert"]:
        raise ProjektFehler("Das Projekt ist archiviert.")
    lehrkraft = wer_art == "lehrkraft"
    aktion = d.get("aktion")
    # die Oberflaeche schickt die Woche mit, die sie zeigt: so landet nichts (z. B. ein doppeltes Abschliessen)
    # still in der naechsten Besprechung
    woche = montag(d["woche"]).isoformat() if d.get("woche") else aktuelle_woche(con, pid)
    z = _zeile(con, pid, woche)
    if z is not None and z["abgeschlossen"] and aktion in ("vorbereitung", "eintrag_neu", "meilenstein", "abschliessen"):
        raise ProjektFehler("Diese Besprechung ist schon abgeschlossen. Bitte die Seite neu laden.")
    jetzt = db.jetzt()

    if aktion == "meilenstein":   # ueber das Tracking-Sheet (eigene Transaktion), dazu ein Eintrag fuers Protokoll
        if not lehrkraft:
            raise ProjektFehler("Meilensteine aus der Besprechung setzt die Lehrkraft.")
        titel = _text(d.get("titel"), "einen Namen für den Meilenstein", 120)
        ms_woche = d.get("meilenstein_woche")
        sheet.aendern(con, pid, wer_art, wer, {"aktion": "meilenstein_neu", "titel": titel, "woche": ms_woche})
        with db.transaktion(con):
            b = _anlegen(con, pid, woche)
            con.execute("INSERT INTO eintrag (projekt_id, besprechung_id, art, text, frist, erstellt, wer_art, wer) "
                        "VALUES (?, ?, 'meilenstein', ?, ?, ?, ?, ?)", (pid, b["id"], titel, ms_woche, jetzt, wer_art, wer))
        return {}

    with db.transaktion(con):
        def ereignis(art, **daten):
            db.ereignis(con, pid, wer_art, wer, art, **daten)

        if aktion == "vorbereitung":
            text = _text(d.get("text"), "den Stand", MAX_LANG, pflicht=False)
            b = _anlegen(con, pid, woche)
            con.execute("UPDATE besprechung SET vorbereitung = ?, vorbereitet = ? WHERE id = ?", (text, jetzt, b["id"]))
            ereignis("vorbereitung", woche=woche)
        elif aktion == "notizen":   # nur Lehrkraefte, kein Ereignis: das Team sieht den Verlauf seiner Aufgaben
            if not lehrkraft:
                raise ProjektFehler("Lehrernotizen schreibt nur die Lehrkraft.")
            b = _anlegen(con, pid, woche)
            con.execute("UPDATE besprechung SET notizen = ? WHERE id = ?", (_text(d.get("text"), "Notizen", 20000, pflicht=False), b["id"]))
        elif aktion == "eintrag_neu":
            art = d.get("art")
            if art not in (LEHRKRAFT_ARTEN if lehrkraft else TEAM_ARTEN):
                raise ProjektFehler("Diese Art von Eintrag gibt es hier nicht.")
            text = _text(d.get("text"), "einen Text", MAX_TEXT)
            frist = _frist(d.get("frist"))
            if art == "auftrag" and not frist:
                raise ProjektFehler("Ein Auftrag braucht eine Frist.")
            mid = d.get("verantwortlich_id") or None
            if mid is not None and not con.execute("SELECT 1 FROM mitglied WHERE id = ? AND projekt_id = ? AND aktiv = 1",
                                                    (mid, pid)).fetchone():
                raise ProjektFehler("Dieses Teammitglied gibt es nicht.")
            b = _anlegen(con, pid, woche)
            eid = con.execute("INSERT INTO eintrag (projekt_id, besprechung_id, art, text, frist, verantwortlich_id, zone, x, y, "
                              "erstellt, wer_art, wer) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              (pid, b["id"], art, text, frist if art == "auftrag" else None, mid, d.get("zone"), d.get("x"),
                               d.get("y"), jetzt, wer_art, wer)).lastrowid
            ereignis("eintrag_neu", eintrag_id=eid, eintragsart=art, text=text, frist=frist)
            return {"eintrag_id": eid}
        elif aktion in ("erledigt", "verwerfen"):
            e = _eintrag_holen(con, pid, d.get("eintrag_id"))
            if e["verworfen"]:
                raise ProjektFehler("Dieser Eintrag ist verworfen.")
            if aktion == "erledigt":
                if not lehrkraft and e["art"] != "auftrag":
                    raise ProjektFehler("Fragen und Themen hakt die Lehrkraft in der Besprechung ab.")
                erledigt = bool(d.get("erledigt", True))
                if erledigt != bool(e["erledigt"]):
                    con.execute("UPDATE eintrag SET erledigt = ? WHERE id = ?", (jetzt if erledigt else None, e["id"]))
                    if erledigt and e["anfrage_id"] and lehrkraft:   # Rueckfrage an der Tafel geklaert
                        from . import anfragen
                        anfragen.in_besprechung_geklaert(con, e["anfrage_id"], wer)
                    ereignis("eintrag_erledigt" if erledigt else "eintrag_offen", eintrag_id=e["id"], eintragsart=e["art"], text=e["text"])
            else:
                if not lehrkraft and (e["wer_art"] != "team" or e["art"] not in TEAM_ARTEN):
                    raise ProjektFehler("Diesen Eintrag kann nur die Lehrkraft verwerfen.")
                con.execute("UPDATE eintrag SET verworfen = 1 WHERE id = ?", (e["id"],))
                ereignis("eintrag_verworfen", eintrag_id=e["id"], eintragsart=e["art"], text=e["text"])
        elif aktion == "abschliessen":
            if not lehrkraft:
                raise ProjektFehler("Abschließen kann nur die Lehrkraft.")
            b = _anlegen(con, pid, woche)
            kuerzel = _kuerzel(con, pid)
            seit = _seit(con, pid, woche)
            ergebnis = [_eintrag(e, kuerzel) for e in con.execute(
                "SELECT * FROM eintrag WHERE besprechung_id = ? AND art IN ('absprache', 'auftrag', 'meilenstein') AND verworfen = 0 "
                "ORDER BY id", (b["id"],))]
            geklaert = [_eintrag(e, kuerzel) for e in con.execute(
                "SELECT * FROM eintrag WHERE projekt_id = ? AND art IN ('frage', 'thema', 'idee') AND verworfen = 0 AND erledigt > ? "
                "ORDER BY id", (pid, seit))]
            from . import tafel   # hier, weil tafel seinerseits besprechung braucht
            protokoll = {"termin": _termin(con, pid, woche), "vorbereitung": b["vorbereitung"],
                         "zusammenfassung": zusammenfassung(con, pid, woche), "ergebnis": ergebnis, "geklaert": geklaert,
                         "tafel": tafel.momentaufnahme(con, pid, woche)}
            con.execute("UPDATE besprechung SET abgeschlossen = ?, abgeschlossen_von = ?, protokoll = ? WHERE id = ?",
                        (jetzt, wer, json.dumps(protokoll, ensure_ascii=False), b["id"]))
            ereignis("besprechung_abgeschlossen", woche=woche, ergebnisse=len(ergebnis))
        else:
            raise ProjektFehler("Unbekannte Aktion.")
    return {}

