"""Termine: Projektzeiten als Regeln, Ausfaelle und Ferien, daraus die Projekttage mit ihren Besprechungsterminen.
Buchung durch das Team (ein Termin je Woche, bis zum Buchungsschluss) oder die Lehrkraft (jederzeit), Warnungen und
die Version zum Buchungsschluss.

Eine Regel gehoert einer Lehrkraft und gilt fuer eine Klasse, also fuer alle Projekte dieser Klasse, die die Lehrkraft
betreut. Projekttag = Datum, an dem eine Regel greift, ohne Ferien, Ausfaelle und gestrichene Tage. Die Termine eines
Tages ergeben sich aus dem Besprechungsfenster und der Terminlaenge (einzelne Tage anpassbar).
Nichts wird geloescht: Regeln, Ausfaelle, Ferien und Buchungen werden nur deaktiviert.
"""
import datetime
import re

from . import db, sheet
from .projekte import ProjektFehler, montag

TAGE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
RHYTHMEN = ("jede", "gerade", "ungerade")
UHRZEIT = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
TAG = datetime.timedelta(days=1)
REGEL_FELDER = ("klasse", "wochentag", "rhythmus", "von", "bis", "fenster_von", "fenster_bis", "laenge", "schluss_tage",
                "schluss_zeit", "gueltig_von", "gueltig_bis")


# --- Hilfen ---

def _datum(wert, feld="ein Datum"):
    try:
        return datetime.date.fromisoformat(str(wert or "")[:10])
    except ValueError:
        raise ProjektFehler("Bitte %s angeben." % feld)


def _uhrzeit(wert, feld="eine Uhrzeit"):
    wert = str(wert or "").strip()
    if len(wert) == 4 and wert[1] == ":":   # 8:30 -> 08:30
        wert = "0" + wert
    if not UHRZEIT.fullmatch(wert):
        raise ProjektFehler("Bitte %s als Uhrzeit (HH:MM) angeben." % feld)
    return wert


def _min(uhrzeit):
    h, m = uhrzeit.split(":")
    return int(h) * 60 + int(m)


def _uhr(minuten):
    return "%02d:%02d" % divmod(minuten, 60)


def _ganz(wert, feld, kleinst, groesst):
    try:
        wert = int(wert)
    except (TypeError, ValueError):
        raise ProjektFehler("Bitte %s angeben." % feld)
    if not kleinst <= wert <= groesst:
        raise ProjektFehler("Bitte für %s einen Wert von %d bis %d angeben." % (feld, kleinst, groesst))
    return wert


def _text(wert, feld, laenge, pflicht=True):
    wert = (wert or "").strip()
    if pflicht and not wert:
        raise ProjektFehler("Bitte %s angeben." % feld)
    if len(wert) > laenge:
        raise ProjektFehler("Der Text ist zu lang (höchstens %d Zeichen)." % laenge)
    return wert


def _gleich(klasse_a, klasse_b):
    return klasse_a.strip().lower() == klasse_b.strip().lower()


def zeitpunkt_text(iso):
    """'2026-11-09T18:00:00' -> 'Mo 09.11., 18:00'"""
    t = datetime.datetime.fromisoformat(iso)
    return "%s %s, %s" % (TAGE[t.weekday()], t.strftime("%d.%m."), t.strftime("%H:%M"))


def tag_text(iso):
    d = datetime.date.fromisoformat(iso[:10])
    return "%s %s" % (TAGE[d.weekday()], d.strftime("%d.%m."))


def kw_text(woche):
    return "KW %d" % datetime.date.fromisoformat(woche).isocalendar()[1]


def _heute():
    return datetime.date.fromisoformat(db.jetzt()[:10])


def _projekt(con, pid):
    p = con.execute("SELECT * FROM projekt WHERE id = ?", (pid,)).fetchone()
    if p is None:
        raise ProjektFehler("Dieses Projekt gibt es nicht.")
    return p


def _projekt_ende(p):
    """Letzter Tag des Projekts (Sonntag der letzten Projektwoche)."""
    return datetime.date.fromisoformat(p["ende"]) + 6 * TAG


# --- Regeln und Projekttage ---

def _regel(z):
    d = {k: z[k] for k in ("id", "lehrkraft_id") + REGEL_FELDER}
    d["aktiv"] = bool(z["aktiv"])
    return d


def projekt_regeln(con, p):
    """Aktive Projektzeiten, die fuer ein Projekt gelten: gleiche Klasse, Regel einer betreuenden Lehrkraft."""
    return [_regel(z) for z in con.execute(
        "SELECT pz.* FROM projektzeit pz JOIN projekt_lehrkraft pl ON pl.lehrkraft_id = pz.lehrkraft_id "
        "WHERE pl.projekt_id = ? AND pz.aktiv = 1 ORDER BY pz.wochentag, pz.fenster_von", (p["id"],))
        if _gleich(z["klasse"], p["klasse"])]


def _greift(r, tag):
    if tag.weekday() != r["wochentag"] or not r["gueltig_von"] <= tag.isoformat() <= r["gueltig_bis"]:
        return False
    gerade = tag.isocalendar()[1] % 2 == 0
    return r["rhythmus"] == "jede" or gerade == (r["rhythmus"] == "gerade")


def tage(con, regeln, von, bis):
    """Alle Tage von..bis (date, einschliesslich), an denen eine der Regeln greift, nach Datum und Uhrzeit sortiert.
    Entfallene Tage sind dabei (entfaellt = Grund), damit die Lehrkraft sieht, warum ein Tag fehlt."""
    if not regeln or von > bis:
        return []
    v, b = von.isoformat(), bis.isoformat()
    ferien = con.execute("SELECT von, bis, name FROM ferien WHERE aktiv = 1 AND bis >= ? AND von <= ?", (v, b)).fetchall()
    ausfaelle = con.execute("SELECT lehrkraft_id, klasse, von, bis, grund FROM ausfall WHERE aktiv = 1 AND bis >= ? AND von <= ?",
                            (v, b)).fetchall()
    ids = [r["id"] for r in regeln]
    anpassung = {(z["projektzeit_id"], z["datum"]): z for z in con.execute(
        "SELECT * FROM projekttag WHERE datum BETWEEN ? AND ? AND projektzeit_id IN (%s)" % ",".join("?" * len(ids)), [v, b] + ids)}
    liste = []
    tag = von
    while tag <= bis:
        d = tag.isoformat()
        for r in regeln:
            if not _greift(r, tag):
                continue
            a = anpassung.get((r["id"], d))
            grund = next((f["name"] for f in ferien if f["von"] <= d <= f["bis"]), None)
            if grund is None:
                grund = next((x["grund"] for x in ausfaelle if x["lehrkraft_id"] == r["lehrkraft_id"] and x["von"] <= d <= x["bis"]
                              and (not x["klasse"] or _gleich(x["klasse"], r["klasse"]))), None)
            if grund is None and a is not None and a["gestrichen"]:
                grund = a["grund"] or "gestrichen"
            fenster_von = a["fenster_von"] if a is not None and a["fenster_von"] else r["fenster_von"]
            fenster_bis = a["fenster_bis"] if a is not None and a["fenster_bis"] else r["fenster_bis"]
            laenge = a["laenge"] if a is not None and a["laenge"] else r["laenge"]
            schluss = datetime.datetime.combine(tag - r["schluss_tage"] * TAG, datetime.time.fromisoformat(r["schluss_zeit"]))
            liste.append({
                "regel_id": r["id"], "lehrkraft_id": r["lehrkraft_id"], "klasse": r["klasse"], "datum": d,
                "woche": montag(tag).isoformat(), "von": r["von"], "bis": r["bis"], "fenster_von": fenster_von,
                "fenster_bis": fenster_bis, "laenge": laenge, "schluss": schluss.isoformat(), "entfaellt": grund,
                "angepasst": a is not None and not a["gestrichen"] and bool(a["fenster_von"] or a["fenster_bis"] or a["laenge"]),
                "gestrichen": a is not None and bool(a["gestrichen"]), "grund": a["grund"] if a is not None else ""})
        tag += TAG
    liste.sort(key=lambda t: (t["datum"], t["fenster_von"]))
    return liste


def plaetze(t):
    """Anfangszeiten der Termine eines Projekttags."""
    anfang, ende = _min(t["fenster_von"]), _min(t["fenster_bis"])
    return [_uhr(m) for m in range(anfang, ende - t["laenge"] + 1, t["laenge"])]


def projekt_tage(con, p, von=None, bis=None):
    """Stattfindende Projekttage eines Projekts (ohne entfallene), begrenzt auf den Projektzeitraum."""
    start, ende = datetime.date.fromisoformat(p["start"]), _projekt_ende(p)
    von, bis = max(von or start, start), min(bis or ende, ende)
    return [t for t in tage(con, projekt_regeln(con, p), von, bis) if not t["entfaellt"]]


def wochen_info(con, p):
    """(projektwochen, ausfallwochen): Wochen (Montage) mit mindestens einem Projekttag, und Wochen, in denen alle
    Projekttage entfallen, mit Grund ({woche: 'Herbstferien'}). (None, {}) solange keine Projektzeit gilt."""
    regeln = projekt_regeln(con, p)
    if not regeln:
        return None, {}
    alle = tage(con, regeln, datetime.date.fromisoformat(p["start"]), _projekt_ende(p))
    statt = {t["woche"] for t in alle if not t["entfaellt"]}
    ausfall = {}
    for t in alle:
        if t["entfaellt"] and t["woche"] not in statt and t["entfaellt"] not in ausfall.setdefault(t["woche"], []):
            ausfall[t["woche"]].append(t["entfaellt"])
    return sorted(statt), {w: ", ".join(g) for w, g in ausfall.items()}


def projektwochen(con, p):
    """Wochen (Montage) mit mindestens einem Projekttag; None, solange fuer das Projekt keine Projektzeit gilt."""
    return wochen_info(con, p)[0]


def entfallende_tage(con, pid, tage_voraus=21):
    """Projekttage von heute an, die wegen Ferien, Ausfall oder Streichung wegfallen (fuer die Team-Uebersicht)."""
    p = _projekt(con, pid)
    heute = _heute()
    bis = min(heute + tage_voraus * TAG, _projekt_ende(p))
    liste = []
    for t in tage(con, projekt_regeln(con, p), max(heute, datetime.date.fromisoformat(p["start"])), bis):
        if t["entfaellt"] and not any(x["datum"] == t["datum"] for x in liste):
            liste.append({"datum": t["datum"], "woche": t["woche"], "grund": t["entfaellt"]})
    return liste


def _wochen_schluss(tage_woche, buchung):
    """Buchungsschluss einer Woche: der des gebuchten Tags, sonst der spaeteste der Woche (bis dahin kann das Team buchen)."""
    if buchung is not None:
        for t in tage_woche:
            if t["regel_id"] == buchung["projektzeit_id"] and t["datum"] == buchung["datum"]:
                return t["schluss"]
    return max(t["schluss"] for t in tage_woche)


def _tag_der_buchung(con, b):
    r = con.execute("SELECT * FROM projektzeit WHERE id = ?", (b["projektzeit_id"],)).fetchone()
    if r is None:
        return None
    gefunden = tage(con, [_regel(r)], datetime.date.fromisoformat(b["datum"]), datetime.date.fromisoformat(b["datum"]))
    return gefunden[0] if gefunden and not gefunden[0]["entfaellt"] else None


def _kuerzel(con):
    return {z[0]: z[1].upper() for z in con.execute("SELECT id, kuerzel FROM lehrkraft")}


# --- Sicht fuer Team und Lehrkraft auf die Termine eines Projekts ---

def termin_sicht(con, pid, lehrkraft=False, wochen=4, aktuell=False):
    """Die naechsten Projektwochen mit ihren Tagen und Terminen. Das Team sieht fremde Buchungen nur als 'belegt'.
    aktuell: nur eine Woche, die laufende, solange sie noch einen Projekttag hat, sonst die naechste Projektwoche."""
    p = _projekt(con, pid)
    jetzt = db.jetzt()
    heute = _heute()
    von = montag(heute)
    alle = projekt_tage(con, p, von, von + (7 * wochen - 1) * TAG)
    ids = sorted({t["regel_id"] for t in alle})
    belegt = {}
    if alle:
        for z in con.execute("SELECT b.projektzeit_id, b.datum, b.uhrzeit, b.projekt_id, p.titel FROM buchung b "
                             "JOIN projekt p ON p.id = b.projekt_id WHERE b.aktiv = 1 AND b.datum BETWEEN ? AND ? "
                             "AND b.projektzeit_id IN (%s)" % ",".join("?" * len(ids)), [alle[0]["datum"], alle[-1]["datum"]] + ids):
            belegt[(z["projektzeit_id"], z["datum"], z["uhrzeit"])] = z
    eigene = {b["woche"]: b for b in con.execute("SELECT * FROM buchung WHERE projekt_id = ? AND aktiv = 1", (pid,))}
    lk = _kuerzel(con)
    ergebnis = []
    for w in sorted({t["woche"] for t in alle}):
        tage_w = [t for t in alle if t["woche"] == w]
        b = eigene.get(w)
        schluss = _wochen_schluss(tage_w, b)
        # das Team darf umbuchen, solange der gebuchte Tag seinen Buchungsschluss noch nicht erreicht hat
        fest = b is not None and not lehrkraft and jetzt >= schluss
        tage_aus = []
        for t in tage_w:
            offen = jetzt < t["schluss"]
            liste = []
            for u in plaetze(t):
                z = belegt.get((t["regel_id"], t["datum"], u))
                status = "eigen" if z and z["projekt_id"] == pid else "belegt" if z else "frei"
                vergangen = t["datum"] + "T" + u < jetzt[:16]
                platz = {"uhrzeit": u, "status": status,
                         "buchbar": status == "frei" and not vergangen and (lehrkraft or (offen and not fest))}
                if lehrkraft and z:
                    platz["team"] = z["titel"]
                liste.append(platz)
            tage_aus.append({"regel_id": t["regel_id"], "datum": t["datum"], "lehrkraft": lk.get(t["lehrkraft_id"], "?"),
                             "von": t["von"], "bis": t["bis"], "schluss": t["schluss"], "offen": offen, "plaetze": liste})
        ergebnis.append({
            "woche": w, "schluss": schluss, "fest": fest, "tage": tage_aus,
            "buchung": {"regel_id": b["projektzeit_id"], "datum": b["datum"], "uhrzeit": b["uhrzeit"],
                        "wer_art": b["wer_art"], "wer": b["wer"]} if b is not None else None})
    if aktuell:
        ergebnis = [w for w in ergebnis if any(t["datum"] >= heute.isoformat() for t in w["tage"])][:1]
    return {"wochen": ergebnis, "regeln": bool(projekt_regeln(con, p)), "jetzt": jetzt}


# --- Buchen ---

def buchen(con, pid, wer_art, wer, regel_id, datum, uhrzeit):
    """Bucht einen Termin; eine fruehere Buchung derselben Woche wird dabei abgeloest (umbuchen)."""
    p = _projekt(con, pid)
    if p["archiviert"]:
        raise ProjektFehler("Das Projekt ist archiviert.")
    team = wer_art == "team"
    try:
        regel_id = int(regel_id)
    except (TypeError, ValueError):
        raise ProjektFehler("Ungültiger Termin.")
    datum, uhrzeit = _datum(datum), _uhrzeit(uhrzeit)
    regel = [r for r in projekt_regeln(con, p) if r["id"] == regel_id]
    if not regel:
        raise ProjektFehler("Diese Projektzeit gilt nicht für dieses Projekt.")
    gefunden = projekt_tage(con, p, datum, datum)
    t = next((x for x in gefunden if x["regel_id"] == regel_id), None)
    if t is None:
        raise ProjektFehler("An diesem Tag gibt es keine Besprechungstermine.")
    if uhrzeit not in plaetze(t):
        raise ProjektFehler("Diesen Termin gibt es nicht.")
    jetzt = db.jetzt()
    if team and jetzt >= t["schluss"]:
        raise ProjektFehler("Für diesen Tag war der Buchungsschluss %s. Bitte die Lehrkraft fragen." % zeitpunkt_text(t["schluss"]))
    if team and t["datum"] + "T" + uhrzeit < jetzt[:16]:
        raise ProjektFehler("Dieser Termin liegt in der Vergangenheit.")
    with db.transaktion(con):
        z = con.execute("SELECT projekt_id FROM buchung WHERE projektzeit_id = ? AND datum = ? AND uhrzeit = ? AND aktiv = 1",
                        (regel_id, t["datum"], uhrzeit)).fetchone()
        if z is not None:
            if z[0] == pid:
                return
            raise ProjektFehler("Dieser Termin ist schon vergeben. Bitte einen anderen wählen.")
        alt = con.execute("SELECT * FROM buchung WHERE projekt_id = ? AND woche = ? AND aktiv = 1", (pid, t["woche"])).fetchone()
        if alt is not None:
            if team:
                alt_tag = _tag_der_buchung(con, alt)
                if alt_tag is not None and jetzt >= alt_tag["schluss"]:
                    raise ProjektFehler("Euer Termin steht fest: Umbuchen ging nur bis %s." % zeitpunkt_text(alt_tag["schluss"]))
            con.execute("UPDATE buchung SET aktiv = 0 WHERE id = ?", (alt["id"],))
        con.execute("INSERT INTO buchung (projekt_id, projektzeit_id, datum, uhrzeit, woche, zeit, wer_art, wer) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (pid, regel_id, t["datum"], uhrzeit, t["woche"], jetzt, wer_art, wer))
        db.ereignis(con, pid, wer_art, wer, "termin_gebucht", datum=t["datum"], uhrzeit=uhrzeit,
                    alt_datum=alt["datum"] if alt is not None else None, alt_uhrzeit=alt["uhrzeit"] if alt is not None else None)


def stornieren(con, pid, wer_art, wer, woche):
    p = _projekt(con, pid)
    if p["archiviert"]:
        raise ProjektFehler("Das Projekt ist archiviert.")
    with db.transaktion(con):
        b = con.execute("SELECT * FROM buchung WHERE projekt_id = ? AND woche = ? AND aktiv = 1", (pid, str(woche or ""))).fetchone()
        if b is None:
            raise ProjektFehler("In dieser Woche ist kein Termin gebucht.")
        if wer_art == "team":
            t = _tag_der_buchung(con, b)
            if t is not None and db.jetzt() >= t["schluss"]:
                raise ProjektFehler("Euer Termin steht fest: Absagen ging nur bis %s." % zeitpunkt_text(t["schluss"]))
        con.execute("UPDATE buchung SET aktiv = 0 WHERE id = ?", (b["id"],))
        db.ereignis(con, pid, wer_art, wer, "termin_storniert", datum=b["datum"], uhrzeit=b["uhrzeit"])


def _buchungen_pruefen(con, wer):
    """Nach einer Aenderung an Regeln, Ausfaellen, Ferien oder Tagen: kuenftige Buchungen, deren Termin es nicht mehr
    gibt, aufheben und im Projekt vermerken. Laeuft in der Transaktion des Aufrufers."""
    heute = _heute().isoformat()
    for b in con.execute("SELECT b.*, p.klasse FROM buchung b JOIN projekt p ON p.id = b.projekt_id "
                         "WHERE b.aktiv = 1 AND b.datum >= ?", (heute,)).fetchall():
        p = _projekt(con, b["projekt_id"])
        tag = datetime.date.fromisoformat(b["datum"])
        t = next((x for x in projekt_tage(con, p, tag, tag) if x["regel_id"] == b["projektzeit_id"]), None)
        if t is not None and b["uhrzeit"] in plaetze(t):
            continue
        grund = "Termin gibt es nicht mehr"
        r = con.execute("SELECT * FROM projektzeit WHERE id = ?", (b["projektzeit_id"],)).fetchone()
        if r is not None:
            alle = tage(con, [_regel(r)], tag, tag)
            if alle and alle[0]["entfaellt"]:
                grund = alle[0]["entfaellt"]
        con.execute("UPDATE buchung SET aktiv = 0 WHERE id = ?", (b["id"],))
        db.ereignis(con, b["projekt_id"], "lehrkraft", wer, "termin_entfallen", datum=b["datum"], uhrzeit=b["uhrzeit"], grund=grund)


# --- Regeln, Tage, Ausfaelle, Ferien verwalten (Lehrkraft) ---

def _regel_pruefen(con, lehrkraft_id, d, ohne=None):
    w = {
        "klasse": _text(d.get("klasse"), "eine Klasse", 30),
        "wochentag": _ganz(d.get("wochentag"), "den Wochentag", 0, 5),
        "rhythmus": d.get("rhythmus") or "jede",
        "von": _uhrzeit(d.get("von"), "den Beginn der Projektzeit"),
        "bis": _uhrzeit(d.get("bis"), "das Ende der Projektzeit"),
        "fenster_von": _uhrzeit(d.get("fenster_von"), "den Beginn des Besprechungsfensters"),
        "fenster_bis": _uhrzeit(d.get("fenster_bis"), "das Ende des Besprechungsfensters"),
        "laenge": _ganz(d.get("laenge"), "die Länge eines Termins (Minuten)", 5, 120),
        "schluss_tage": _ganz(d.get("schluss_tage", 1), "den Buchungsschluss (Tage vorher)", 0, 7),
        "schluss_zeit": _uhrzeit(d.get("schluss_zeit") or "18:00", "die Uhrzeit des Buchungsschlusses"),
        "gueltig_von": _datum(d.get("gueltig_von"), "den ersten Tag der Regel").isoformat(),
        "gueltig_bis": _datum(d.get("gueltig_bis"), "den letzten Tag der Regel").isoformat(),
    }
    if w["rhythmus"] not in RHYTHMEN:
        raise ProjektFehler("Unbekannter Rhythmus.")
    if _min(w["bis"]) <= _min(w["von"]):
        raise ProjektFehler("Die Projektzeit endet vor ihrem Beginn.")
    if _min(w["fenster_bis"]) - _min(w["fenster_von"]) < w["laenge"]:
        raise ProjektFehler("Ins Besprechungsfenster passt kein einziger Termin.")
    if w["schluss_tage"] == 0 and w["schluss_zeit"] > w["fenster_von"]:
        raise ProjektFehler("Der Buchungsschluss liegt nach dem ersten Termin des Tages.")
    if w["gueltig_bis"] < w["gueltig_von"]:
        raise ProjektFehler("Die Regel endet vor ihrem Beginn.")
    if (datetime.date.fromisoformat(w["gueltig_bis"]) - datetime.date.fromisoformat(w["gueltig_von"])).days > 400:
        raise ProjektFehler("Eine Regel gilt höchstens ein Schuljahr.")
    for r in con.execute("SELECT * FROM projektzeit WHERE lehrkraft_id = ? AND aktiv = 1 AND wochentag = ? AND id != ?",
                         (lehrkraft_id, w["wochentag"], ohne or -1)):
        if r["gueltig_bis"] < w["gueltig_von"] or r["gueltig_von"] > w["gueltig_bis"]:
            continue
        if "jede" not in (r["rhythmus"], w["rhythmus"]) and r["rhythmus"] != w["rhythmus"]:
            continue
        if _min(r["fenster_bis"]) <= _min(w["fenster_von"]) or _min(w["fenster_bis"]) <= _min(r["fenster_von"]):
            continue
        raise ProjektFehler("Das Besprechungsfenster überschneidet sich mit deiner Projektzeit %s (%s, %s bis %s)."
                            % (r["klasse"], TAGE[r["wochentag"]], r["fenster_von"], r["fenster_bis"]))
    return w


def _eigene_regel(con, konto, rid):
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        raise ProjektFehler("Ungültige Projektzeit.")
    r = con.execute("SELECT * FROM projektzeit WHERE id = ?", (rid,)).fetchone()
    if r is None or (r["lehrkraft_id"] != konto["id"] and konto["rolle"] != "admin"):
        raise ProjektFehler("Diese Projektzeit gibt es nicht.")
    return r


def regel_anlegen(con, konto, d):
    with db.transaktion(con):
        w = _regel_pruefen(con, konto["id"], d)
        rid = con.execute("INSERT INTO projektzeit (lehrkraft_id, %s, erstellt) VALUES (?, %s, ?)"
                          % (", ".join(REGEL_FELDER), ", ".join("?" * len(REGEL_FELDER))),
                          [konto["id"]] + [w[k] for k in REGEL_FELDER] + [db.jetzt()]).lastrowid
        db.ereignis(con, None, "lehrkraft", konto["kuerzel"], "projektzeit_neu", projektzeit_id=rid, **w)
        _buchungen_pruefen(con, konto["kuerzel"])
    return rid


def regel_aendern(con, konto, rid, d):
    """Aendert eine Regel. {'aktiv': false} beendet sie (sie bleibt gespeichert, kuenftige Buchungen entfallen)."""
    r = _eigene_regel(con, konto, rid)
    with db.transaktion(con):
        if d.get("aktiv") is False:
            con.execute("UPDATE projektzeit SET aktiv = 0 WHERE id = ?", (r["id"],))
            db.ereignis(con, None, "lehrkraft", konto["kuerzel"], "projektzeit_beendet", projektzeit_id=r["id"], klasse=r["klasse"])
        else:
            w = _regel_pruefen(con, r["lehrkraft_id"], dict({k: r[k] for k in REGEL_FELDER}, **d), ohne=r["id"])
            con.execute("UPDATE projektzeit SET %s WHERE id = ?" % ", ".join("%s = ?" % k for k in REGEL_FELDER),
                        [w[k] for k in REGEL_FELDER] + [r["id"]])
            db.ereignis(con, None, "lehrkraft", konto["kuerzel"], "projektzeit_geaendert", projektzeit_id=r["id"], **w)
        _buchungen_pruefen(con, konto["kuerzel"])


def tag_anpassen(con, konto, rid, datum, d):
    """Einen einzelnen Projekttag anpassen (Fenster, Terminlaenge), streichen oder zuruecksetzen."""
    r = _eigene_regel(con, konto, rid)
    tag = _datum(datum)
    if not _greift(_regel(r), tag):
        raise ProjektFehler("An diesem Tag greift die Projektzeit nicht.")
    if d.get("zuruecksetzen"):
        werte = (0, None, None, None, "")
    elif d.get("gestrichen"):
        werte = (1, None, None, None, _text(d.get("grund"), "einen Grund", 120))
    else:
        fv = _uhrzeit(d.get("fenster_von") or r["fenster_von"], "den Beginn des Besprechungsfensters")
        fb = _uhrzeit(d.get("fenster_bis") or r["fenster_bis"], "das Ende des Besprechungsfensters")
        laenge = _ganz(d.get("laenge") or r["laenge"], "die Länge eines Termins (Minuten)", 5, 120)
        if _min(fb) - _min(fv) < laenge:
            raise ProjektFehler("Ins Besprechungsfenster passt kein einziger Termin.")
        werte = (0, fv, fb, laenge, _text(d.get("grund"), "einen Grund", 120, pflicht=False))
    with db.transaktion(con):
        con.execute("INSERT INTO projekttag (projektzeit_id, datum, gestrichen, fenster_von, fenster_bis, laenge, grund) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (projektzeit_id, datum) DO UPDATE SET gestrichen = excluded.gestrichen, "
                    "fenster_von = excluded.fenster_von, fenster_bis = excluded.fenster_bis, laenge = excluded.laenge, "
                    "grund = excluded.grund", (r["id"], tag.isoformat()) + werte)
        db.ereignis(con, None, "lehrkraft", konto["kuerzel"], "projekttag_angepasst", projektzeit_id=r["id"], datum=tag.isoformat(),
                    gestrichen=bool(werte[0]), fenster_von=werte[1], fenster_bis=werte[2], laenge=werte[3], grund=werte[4],
                    zurueckgesetzt=bool(d.get("zuruecksetzen")))
        _buchungen_pruefen(con, konto["kuerzel"])


def _zeitraum(d):
    von, bis = _datum(d.get("von"), "den ersten Tag"), _datum(d.get("bis") or d.get("von"), "den letzten Tag")
    if bis < von:
        raise ProjektFehler("Der Zeitraum endet vor seinem Beginn.")
    if (bis - von).days > 120:
        raise ProjektFehler("Der Zeitraum ist zu lang (höchstens 120 Tage).")
    return von.isoformat(), bis.isoformat()


def ausfall_anlegen(con, konto, d):
    von, bis = _zeitraum(d)
    grund = _text(d.get("grund"), "einen Grund", 120)
    klasse = _text(d.get("klasse"), "eine Klasse", 30, pflicht=False)
    with db.transaktion(con):
        aid = con.execute("INSERT INTO ausfall (lehrkraft_id, klasse, von, bis, grund, erstellt) VALUES (?, ?, ?, ?, ?, ?)",
                          (konto["id"], klasse, von, bis, grund, db.jetzt())).lastrowid
        db.ereignis(con, None, "lehrkraft", konto["kuerzel"], "ausfall_neu", ausfall_id=aid, von=von, bis=bis, klasse=klasse, grund=grund)
        _buchungen_pruefen(con, konto["kuerzel"])
    return aid


def ausfall_entfernen(con, konto, aid):
    z = con.execute("SELECT * FROM ausfall WHERE id = ?", (aid,)).fetchone()
    if z is None or (z["lehrkraft_id"] != konto["id"] and konto["rolle"] != "admin"):
        raise ProjektFehler("Diesen Ausfall gibt es nicht.")
    with db.transaktion(con):
        con.execute("UPDATE ausfall SET aktiv = 0 WHERE id = ?", (z["id"],))
        db.ereignis(con, None, "lehrkraft", konto["kuerzel"], "ausfall_entfernt", ausfall_id=z["id"], grund=z["grund"])


def ferien_anlegen(con, konto, d):
    von, bis = _zeitraum(d)
    name = _text(d.get("name"), "einen Namen (z. B. Herbstferien)", 80)
    with db.transaktion(con):
        fid = con.execute("INSERT INTO ferien (von, bis, name) VALUES (?, ?, ?)", (von, bis, name)).lastrowid
        db.ereignis(con, None, "lehrkraft", konto["kuerzel"], "ferien_neu", ferien_id=fid, von=von, bis=bis, name=name)
        _buchungen_pruefen(con, konto["kuerzel"])
    return fid


def ferien_entfernen(con, konto, fid):
    z = con.execute("SELECT * FROM ferien WHERE id = ? AND aktiv = 1", (fid,)).fetchone()
    if z is None:
        raise ProjektFehler("Diese Ferien gibt es nicht.")
    with db.transaktion(con):
        con.execute("UPDATE ferien SET aktiv = 0 WHERE id = ?", (z["id"],))
        db.ereignis(con, None, "lehrkraft", konto["kuerzel"], "ferien_entfernt", ferien_id=z["id"], name=z["name"])


# --- Uebersicht der Lehrkraft ---

def _betreute_projekte(con, konto, regel):
    return [p for p in con.execute("SELECT p.* FROM projekt p JOIN projekt_lehrkraft pl ON pl.projekt_id = p.id "
                                   "WHERE pl.lehrkraft_id = ? AND p.archiviert = 0 ORDER BY p.titel", (regel["lehrkraft_id"],))
            if _gleich(p["klasse"], regel["klasse"])]


def uebersicht(con, konto, von, wochen=4):
    """Eigene Projektzeiten, Ausfaelle, Ferien und die Projekttage der naechsten Wochen mit Belegung."""
    von = montag(_datum(von) if von else _heute())
    bis = von + (7 * wochen - 1) * TAG
    regeln = [_regel(z) for z in con.execute("SELECT * FROM projektzeit WHERE lehrkraft_id = ? ORDER BY aktiv DESC, wochentag, "
                                             "fenster_von", (konto["id"],))]
    aktive = [r for r in regeln if r["aktiv"]]
    alle = tage(con, aktive, von, bis)
    projekte_je_regel = {r["id"]: _betreute_projekte(con, konto, r) for r in aktive}
    belegt, gebucht = {}, set()
    for z in con.execute("SELECT b.*, p.titel FROM buchung b JOIN projekt p ON p.id = b.projekt_id WHERE b.aktiv = 1 "
                         "AND b.datum BETWEEN ? AND ?", (von.isoformat(), bis.isoformat())):
        belegt[(z["projektzeit_id"], z["datum"], z["uhrzeit"])] = z
        gebucht.add((z["projekt_id"], z["woche"]))
    jetzt = db.jetzt()
    tage_aus = []
    for t in alle:
        liste = []
        if not t["entfaellt"]:
            for u in plaetze(t):
                z = belegt.get((t["regel_id"], t["datum"], u))
                liste.append({"uhrzeit": u, "projekt_id": z["projekt_id"] if z else None, "team": z["titel"] if z else None,
                              "von_lehrkraft": bool(z) and z["wer_art"] == "lehrkraft",
                              "vergangen": t["datum"] + "T" + u < jetzt[:16]})
        ohne = [{"id": p["id"], "titel": p["titel"]} for p in projekte_je_regel[t["regel_id"]]
                if p["start"] <= t["woche"] <= p["ende"] and (p["id"], t["woche"]) not in gebucht]
        tage_aus.append(dict(t, plaetze=liste, ohne_termin=[] if t["entfaellt"] else ohne,
                             projekte=len(projekte_je_regel[t["regel_id"]])))
    return {
        "von": von.isoformat(), "bis": bis.isoformat(), "jetzt": jetzt,
        "regeln": [dict(r, projekte=[p["titel"] for p in _betreute_projekte(con, konto, r)]) for r in regeln],
        "tage": tage_aus,
        "ausfaelle": [{"id": z["id"], "klasse": z["klasse"], "von": z["von"], "bis": z["bis"], "grund": z["grund"]}
                      for z in con.execute("SELECT * FROM ausfall WHERE lehrkraft_id = ? AND aktiv = 1 AND bis >= ? ORDER BY von",
                                           (konto["id"], (_heute() - 30 * TAG).isoformat()))],
        "ferien": [{"id": z["id"], "von": z["von"], "bis": z["bis"], "name": z["name"], "quelle": z["quelle"]}
                   for z in con.execute("SELECT * FROM ferien WHERE aktiv = 1 AND bis >= ? ORDER BY von",
                                        ((_heute() - 30 * TAG).isoformat(),))],
        "klassen": sorted({p["klasse"] for p in con.execute(
            "SELECT p.klasse FROM projekt p JOIN projekt_lehrkraft pl ON pl.projekt_id = p.id "
            "WHERE pl.lehrkraft_id = ? AND p.archiviert = 0", (konto["id"],))}),
    }


# --- Warnungen ---

def warnungen(con, pid):
    """Was fuer ein Projekt gerade zu tun ist. stufe 'warnung' sieht auch die Lehrkraft, 'hinweis' nur das Team."""
    p = _projekt(con, pid)
    if p["archiviert"]:
        return []
    jetzt = db.jetzt()
    heute = _heute()
    diese = montag(heute).isoformat()
    liste = []
    aufgaben = con.execute("SELECT * FROM aufgabe WHERE projekt_id = ? AND verworfen = 0 ORDER BY pos, id", (pid,)).fetchall()
    zellen = {}
    for z in con.execute("SELECT z.* FROM zelle z JOIN aufgabe a ON a.id = z.aufgabe_id WHERE a.projekt_id = ?", (pid,)):
        zellen[(z["aufgabe_id"], z["woche"])] = z

    alle = projekt_tage(con, p, montag(heute), montag(heute) + 20 * TAG)   # drei ganze Wochen
    kommend = [t for t in alle if t["datum"] >= heute.isoformat()]
    wochen = {t["woche"] for t in alle if t["woche"] == diese}
    if kommend:
        wochen.add(kommend[0]["woche"])
    buchungen = {b["woche"]: b for b in con.execute("SELECT * FROM buchung WHERE projekt_id = ? AND aktiv = 1", (pid,))}
    for w in sorted(wochen):
        b = buchungen.get(w)
        schluss = _wochen_schluss([t for t in alle if t["woche"] == w], b)
        vorbei = jetzt >= schluss
        if b is None:
            if vorbei:
                liste.append({"art": "termin_fehlt", "stufe": "warnung", "woche": w,
                              "text": "Kein Besprechungstermin für %s gebucht (Buchungsschluss war %s)." % (kw_text(w), zeitpunkt_text(schluss))})
            else:
                liste.append({"art": "termin_offen", "stufe": "hinweis", "woche": w,
                              "text": "Noch kein Besprechungstermin für %s. Buchen bis %s." % (kw_text(w), zeitpunkt_text(schluss))})
        # Ampeln: fuer die Woche, in der der Buchungsschluss liegt (fruehere geht nicht, spaetere noch nicht)
        aw = montag(schluss[:10]).isoformat()
        if aw > diese:
            continue
        offen = [a for a in aufgaben if not a["erledigt"] and (a["id"], aw) in zellen and zellen[(a["id"], aw)]["plan"]
                 and not zellen[(a["id"], aw)]["ampel"]]
        if offen:
            n = "%d Aufgabe%s" % (len(offen), "" if len(offen) == 1 else "n")
            if vorbei:
                liste.append({"art": "nicht_aktualisiert", "stufe": "warnung", "woche": aw,
                              "text": "%s ohne Ampel für %s zum Buchungsschluss." % (n, kw_text(aw))})
            else:
                liste.append({"art": "ampel_offen", "stufe": "hinweis", "woche": aw,
                              "text": "%s brauch%s noch eine Ampel für %s, bis %s." % (n, "t" if len(offen) == 1 else "en",
                                                                                     kw_text(aw), zeitpunkt_text(schluss))})
    for a in aufgaben:
        if a["ende"] and not a["erledigt"] and a["ende"] < diese:
            liste.append({"art": "endtermin", "stufe": "warnung", "aufgabe_id": a["id"],
                          "text": "„%s“: Endtermin %s überschritten, nicht erledigt." % (a["titel"], kw_text(a["ende"]))})
    ohne = [a for a in aufgaben if not a["verantwortlich_id"] and (a["ende"] or any(
        k[0] == a["id"] and z["plan"] for k, z in zellen.items()))]
    if ohne:
        liste.append({"art": "verantwortlich_fehlt", "stufe": "hinweis",
                      "text": "%d geplante Aufgabe%s ohne Verantwortlichen." % (len(ohne), "" if len(ohne) == 1 else "n")})
    return liste


# --- Version zum Buchungsschluss (laeuft jede Minute im Server) ---

def faellige_versionen(con):
    """Friert fuer jedes laufende Projekt den Stand ein, sobald der Buchungsschluss einer Woche erreicht ist.
    Eine Version je Projekt und Woche. War der Server zum Buchungsschluss aus, holt er das hoechstens 2 Tage spaeter
    nach (sonst waere der eingefrorene Stand irrefuehrend). Rueckgabe: Anzahl neuer Versionen."""
    jetzt = db.jetzt()
    jetzt_dt = datetime.datetime.fromisoformat(jetzt)
    heute = _heute()
    neu = 0
    for p in con.execute("SELECT * FROM projekt WHERE archiviert = 0").fetchall():
        # ganze Wochen, damit der Buchungsschluss je Woche stimmt (er kann bis zu 7 Tage vor dem Projekttag liegen)
        alle = projekt_tage(con, p, montag(heute - 9 * TAG), montag(heute + 8 * TAG) + 6 * TAG)
        if not alle:
            continue
        buchungen = {b["woche"]: b for b in con.execute("SELECT * FROM buchung WHERE projekt_id = ? AND aktiv = 1", (p["id"],))}
        for w in sorted({t["woche"] for t in alle}):
            schluss = _wochen_schluss([t for t in alle if t["woche"] == w], buchungen.get(w))
            if not schluss <= jetzt or schluss < p["erstellt"]:
                continue
            if jetzt_dt - datetime.datetime.fromisoformat(schluss) > 2 * TAG:
                continue
            name = "Buchungsschluss %s (%s)" % (kw_text(w), zeitpunkt_text(schluss))
            if sheet.version_anlegen(con, p["id"], "buchungsschluss", name, "system", "System", woche=w):
                neu += 1
    return neu
