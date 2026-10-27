"""Projekte: anlegen aus einer Vorlage, Teammitglieder, Lehrkraefte (Teamteaching), Team-Link.

Ein Projekt ist die Arbeit genau eines Teams. Das Team erreicht es ueber einen geheimen Link (/t/<token>);
erneuern macht den alten Link ungueltig.
"""
import datetime
import json
import re
import secrets

from . import db


class ProjektFehler(Exception):
    """Fehler mit einer Meldung, die direkt in der Oberflaeche erscheinen darf."""


TOKEN = re.compile(r"[A-Za-z0-9_-]{20,64}")
MAX_TEXT = 200


def neuer_token():
    return secrets.token_urlsafe(24)


def montag(datum):
    """Montag der Kalenderwoche eines Datums (ISO-Text oder date)."""
    if isinstance(datum, str):
        try:
            datum = datetime.date.fromisoformat(datum[:10])
        except ValueError:
            raise ProjektFehler("Bitte ein gültiges Datum angeben.")
    return datum - datetime.timedelta(days=datum.weekday())


def schuljahr_zu(datum):
    """Schuljahr als Text, z. B. 2026/27 (Wechsel am 1. August)."""
    j = datum.year if datum.month >= 8 else datum.year - 1
    return "%d/%02d" % (j, (j + 1) % 100)


def _text(wert, feld, pflicht=True, laenge=MAX_TEXT):
    wert = (wert or "").strip()
    if pflicht and not wert:
        raise ProjektFehler("Bitte %s angeben." % feld)
    if len(wert) > laenge:
        raise ProjektFehler("%s ist zu lang (höchstens %d Zeichen)." % (feld[0].upper() + feld[1:], laenge))
    return wert


def vorlagen(con):
    return [{"schluessel": z["schluessel"], "name": z["name"], "daten": json.loads(z["daten"])}
            for z in con.execute("SELECT * FROM vorlage ORDER BY name")]


def _kuerzel(con, projekt_id, vorname, nachname, ohne=None):
    basis = (vorname[:1] + nachname[:1]).upper() or "X"
    vergeben = {z[0] for z in con.execute("SELECT kuerzel FROM mitglied WHERE projekt_id = ? AND id != ?",
                                          (projekt_id, ohne or -1))}
    kuerzel, n = basis, 2
    while kuerzel in vergeben:
        kuerzel, n = "%s%d" % (basis, n), n + 1
    return kuerzel


def _mitglied_pruefen(m):
    return _text(m.get("vorname"), "einen Vornamen", laenge=60), _text(m.get("nachname"), "einen Nachnamen", laenge=60)


def anlegen(con, wer, titel, klasse, start, ende, lehrkraefte, mitglieder, vorlage="standard", schuljahr=None,
            beschreibung=""):
    """Legt ein Projekt mit Phasen und Vorgabe-Aufgaben aus der Vorlage an. wer: Kuerzel der Lehrkraft."""
    titel = _text(titel, "einen Projekttitel", laenge=80)
    klasse = _text(klasse, "eine Klasse", laenge=30)
    beschreibung = _text(beschreibung, "eine Beschreibung", pflicht=False, laenge=2000)
    start, ende = montag(start), montag(ende)
    if ende < start:
        raise ProjektFehler("Das Projektende liegt vor dem Start.")
    if (ende - start).days > 7 * 60:
        raise ProjektFehler("Ein Projekt kann höchstens 60 Wochen dauern.")
    schuljahr = _text(schuljahr, "ein Schuljahr", pflicht=False, laenge=9) or schuljahr_zu(start)
    zeile = con.execute("SELECT daten FROM vorlage WHERE schluessel = ?", (vorlage,)).fetchone()
    if zeile is None:
        raise ProjektFehler("Diese Vorlage gibt es nicht.")
    phasen = json.loads(zeile["daten"])["phasen"]
    ids = sorted({int(i) for i in lehrkraefte or []})
    if not ids:
        raise ProjektFehler("Mindestens eine Lehrkraft muss das Projekt betreuen.")
    if len(ids) != con.execute("SELECT COUNT(*) FROM lehrkraft WHERE id IN (%s)" % ",".join("?" * len(ids)),
                               ids).fetchone()[0]:
        raise ProjektFehler("Unbekannte Lehrkraft.")
    leute = [_mitglied_pruefen(m) for m in mitglieder or []]

    with db.transaktion(con):
        cur = con.execute("INSERT INTO projekt (titel, klasse, schuljahr, beschreibung, start, ende, link_token, erstellt) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                          (titel, klasse, schuljahr, beschreibung, start.isoformat(), ende.isoformat(), neuer_token(),
                           db.jetzt()))
        pid = cur.lastrowid
        con.executemany("INSERT INTO projekt_lehrkraft (projekt_id, lehrkraft_id) VALUES (?, ?)", [(pid, i) for i in ids])
        for pos, phase in enumerate(phasen):
            ph = con.execute("INSERT INTO phase (projekt_id, pos, name) VALUES (?, ?, ?)", (pid, pos, phase["name"])).lastrowid
            for apos, aufgabe in enumerate(phase.get("aufgaben", [])):
                con.execute("INSERT INTO aufgabe (projekt_id, phase_id, pos, titel, aus_vorlage, erstellt) "
                            "VALUES (?, ?, ?, ?, 1, ?)", (pid, ph, apos, aufgabe, db.jetzt()))
        for vorname, nachname in leute:
            con.execute("INSERT INTO mitglied (projekt_id, vorname, nachname, kuerzel) VALUES (?, ?, ?, ?)",
                        (pid, vorname, nachname, _kuerzel(con, pid, vorname, nachname)))
        db.ereignis(con, pid, "lehrkraft", wer, "projekt_angelegt", titel=titel, vorlage=vorlage)
    return pid


def darf(con, konto, projekt_id):
    """Darf diese Lehrkraft das Projekt sehen und bearbeiten? Admins duerfen alles."""
    if konto["rolle"] == "admin":
        return con.execute("SELECT 1 FROM projekt WHERE id = ?", (projekt_id,)).fetchone() is not None
    return con.execute("SELECT 1 FROM projekt_lehrkraft WHERE projekt_id = ? AND lehrkraft_id = ?",
                       (projekt_id, konto["id"])).fetchone() is not None


def _kurz(con, z):
    lk = [r[0] for r in con.execute("SELECT l.kuerzel FROM projekt_lehrkraft pl JOIN lehrkraft l ON l.id = pl.lehrkraft_id "
                                    "WHERE pl.projekt_id = ? ORDER BY l.kuerzel", (z["id"],))]
    anzahl = con.execute("SELECT COUNT(*) FROM mitglied WHERE projekt_id = ? AND aktiv = 1", (z["id"],)).fetchone()[0]
    letzte = con.execute("SELECT zeit FROM ereignis WHERE projekt_id = ? ORDER BY id DESC LIMIT 1", (z["id"],)).fetchone()
    return {"id": z["id"], "titel": z["titel"], "klasse": z["klasse"], "schuljahr": z["schuljahr"], "start": z["start"],
            "ende": z["ende"], "archiviert": bool(z["archiviert"]), "lehrkraefte": lk, "mitglieder": anzahl,
            "zuletzt": letzte[0] if letzte else None}


def liste(con, konto, archiviert=False):
    if konto["rolle"] == "admin":
        zeilen = con.execute("SELECT * FROM projekt WHERE archiviert = ? ORDER BY klasse, titel", (1 if archiviert else 0,))
    else:
        zeilen = con.execute("SELECT p.* FROM projekt p JOIN projekt_lehrkraft pl ON pl.projekt_id = p.id "
                             "WHERE pl.lehrkraft_id = ? AND p.archiviert = ? ORDER BY p.klasse, p.titel",
                             (konto["id"], 1 if archiviert else 0))
    return [_kurz(con, z) for z in zeilen.fetchall()]


def _struktur(con, pid):
    phasen = []
    for ph in con.execute("SELECT * FROM phase WHERE projekt_id = ? ORDER BY pos", (pid,)).fetchall():
        aufgaben = [{"id": a["id"], "titel": a["titel"], "aus_vorlage": bool(a["aus_vorlage"]),
                     "verantwortlich_id": a["verantwortlich_id"], "verworfen": bool(a["verworfen"])}
                    for a in con.execute("SELECT * FROM aufgabe WHERE phase_id = ? ORDER BY pos", (ph["id"],))]
        phasen.append({"id": ph["id"], "name": ph["name"], "aufgaben": aufgaben})
    return phasen


def _mitglieder(con, pid, nur_aktive=False):
    sql = "SELECT * FROM mitglied WHERE projekt_id = ?" + (" AND aktiv = 1" if nur_aktive else "") + " ORDER BY nachname, vorname"
    return [{"id": m["id"], "vorname": m["vorname"], "nachname": m["nachname"], "kuerzel": m["kuerzel"],
             "aktiv": bool(m["aktiv"])} for m in con.execute(sql, (pid,))]


def details(con, pid, ereignisse=50):
    z = con.execute("SELECT * FROM projekt WHERE id = ?", (pid,)).fetchone()
    if z is None:
        return None
    d = _kurz(con, z)
    d.update({
        "beschreibung": z["beschreibung"],
        "link_token": z["link_token"],
        "lehrkraft_ids": [r[0] for r in con.execute("SELECT lehrkraft_id FROM projekt_lehrkraft WHERE projekt_id = ?", (pid,))],
        "mitglieder": _mitglieder(con, pid),
        "phasen": _struktur(con, pid),
        "verlauf": [{"zeit": e["zeit"], "wer_art": e["wer_art"], "wer": e["wer"], "art": e["art"],
                     "daten": json.loads(e["daten"])}
                    for e in con.execute("SELECT * FROM ereignis WHERE projekt_id = ? ORDER BY id DESC LIMIT ?",
                                         (pid, ereignisse))],
    })
    return d


def aendern(con, wer, pid, felder):
    """Titel, Klasse, Schuljahr, Beschreibung, Zeitraum und betreuende Lehrkraefte aendern."""
    alt = con.execute("SELECT * FROM projekt WHERE id = ?", (pid,)).fetchone()
    if alt is None:
        raise ProjektFehler("Dieses Projekt gibt es nicht.")
    neu = {
        "titel": _text(felder.get("titel", alt["titel"]), "einen Projekttitel", laenge=80),
        "klasse": _text(felder.get("klasse", alt["klasse"]), "eine Klasse", laenge=30),
        "schuljahr": _text(felder.get("schuljahr", alt["schuljahr"]), "ein Schuljahr", laenge=9),
        "beschreibung": _text(felder.get("beschreibung", alt["beschreibung"]), "eine Beschreibung", pflicht=False, laenge=2000),
        "start": montag(felder.get("start", alt["start"])).isoformat(),
        "ende": montag(felder.get("ende", alt["ende"])).isoformat(),
    }
    if neu["ende"] < neu["start"]:
        raise ProjektFehler("Das Projektende liegt vor dem Start.")
    geaendert = {k: v for k, v in neu.items() if v != alt[k]}
    with db.transaktion(con):
        if geaendert:
            con.execute("UPDATE projekt SET %s WHERE id = ?" % ", ".join("%s = ?" % k for k in geaendert),
                        list(geaendert.values()) + [pid])
            db.ereignis(con, pid, "lehrkraft", wer, "projekt_geaendert", **geaendert)
        if "lehrkraefte" in felder:
            ids = sorted({int(i) for i in felder["lehrkraefte"] or []})
            if not ids:
                raise ProjektFehler("Mindestens eine Lehrkraft muss das Projekt betreuen.")
            bisher = sorted(r[0] for r in con.execute("SELECT lehrkraft_id FROM projekt_lehrkraft WHERE projekt_id = ?", (pid,)))
            if ids != bisher:
                if len(ids) != con.execute("SELECT COUNT(*) FROM lehrkraft WHERE id IN (%s)" % ",".join("?" * len(ids)),
                                           ids).fetchone()[0]:
                    raise ProjektFehler("Unbekannte Lehrkraft.")
                con.execute("DELETE FROM projekt_lehrkraft WHERE projekt_id = ?", (pid,))
                con.executemany("INSERT INTO projekt_lehrkraft (projekt_id, lehrkraft_id) VALUES (?, ?)",
                                [(pid, i) for i in ids])
                kuerzel = [r[0] for r in con.execute("SELECT kuerzel FROM lehrkraft WHERE id IN (%s) ORDER BY kuerzel"
                                                     % ",".join("?" * len(ids)), ids)]
                db.ereignis(con, pid, "lehrkraft", wer, "lehrkraefte_geaendert", lehrkraefte=kuerzel)


def mitglied_anlegen(con, wer, pid, vorname, nachname):
    vorname, nachname = _mitglied_pruefen({"vorname": vorname, "nachname": nachname})
    with db.transaktion(con):
        kuerzel = _kuerzel(con, pid, vorname, nachname)
        mid = con.execute("INSERT INTO mitglied (projekt_id, vorname, nachname, kuerzel) VALUES (?, ?, ?, ?)",
                          (pid, vorname, nachname, kuerzel)).lastrowid
        db.ereignis(con, pid, "lehrkraft", wer, "mitglied_angelegt", name="%s %s" % (vorname, nachname), kuerzel=kuerzel)
    return mid


def mitglied_aendern(con, wer, pid, mid, felder):
    alt = con.execute("SELECT * FROM mitglied WHERE id = ? AND projekt_id = ?", (mid, pid)).fetchone()
    if alt is None:
        raise ProjektFehler("Dieses Teammitglied gibt es nicht.")
    vorname, nachname = _mitglied_pruefen({"vorname": felder.get("vorname", alt["vorname"]),
                                           "nachname": felder.get("nachname", alt["nachname"])})
    aktiv = bool(felder.get("aktiv", bool(alt["aktiv"])))
    with db.transaktion(con):
        kuerzel = alt["kuerzel"]
        if (vorname, nachname) != (alt["vorname"], alt["nachname"]):
            kuerzel = _kuerzel(con, pid, vorname, nachname, ohne=mid)
        con.execute("UPDATE mitglied SET vorname = ?, nachname = ?, kuerzel = ?, aktiv = ? WHERE id = ?",
                    (vorname, nachname, kuerzel, 1 if aktiv else 0, mid))
        db.ereignis(con, pid, "lehrkraft", wer, "mitglied_geaendert", name="%s %s" % (vorname, nachname),
                    kuerzel=kuerzel, aktiv=aktiv)


def link_erneuern(con, wer, pid):
    with db.transaktion(con):
        token = neuer_token()
        con.execute("UPDATE projekt SET link_token = ? WHERE id = ?", (token, pid))
        db.ereignis(con, pid, "lehrkraft", wer, "link_erneuert")
    return token


def archivieren(con, wer, pid, archiviert):
    with db.transaktion(con):
        con.execute("UPDATE projekt SET archiviert = ? WHERE id = ?", (1 if archiviert else 0, pid))
        db.ereignis(con, pid, "lehrkraft", wer, "archiviert" if archiviert else "reaktiviert")


def team_sicht(con, token):
    """Was das Team ueber seinen Link sieht. None, wenn der Link unbekannt oder das Projekt archiviert ist."""
    if not TOKEN.fullmatch(token or ""):
        return None
    z = con.execute("SELECT * FROM projekt WHERE link_token = ? AND archiviert = 0", (token,)).fetchone()
    if z is None:
        return None
    lk = [{"kuerzel": r[0].upper(), "name": r[1]} for r in con.execute(
        "SELECT l.kuerzel, l.name FROM projekt_lehrkraft pl JOIN lehrkraft l ON l.id = pl.lehrkraft_id "
        "WHERE pl.projekt_id = ? ORDER BY l.name", (z["id"],))]
    return {"titel": z["titel"], "klasse": z["klasse"], "schuljahr": z["schuljahr"], "beschreibung": z["beschreibung"],
            "start": z["start"], "ende": z["ende"], "lehrkraefte": lk,
            "mitglieder": _mitglieder(con, z["id"], nur_aktive=True), "phasen": _struktur(con, z["id"])}
