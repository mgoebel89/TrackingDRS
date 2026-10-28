"""Kalender: Abos (ICS) und die Eintraege fuer Cockpit und Kalender-Reiter.

Abos: Jede Lehrkraft kann ihren Dienstkalender hinterlegen (Outlook: Kalender veroeffentlichen, ICS-Link). Ihn sieht nur
sie selbst, nie die Teams oder andere Lehrkraefte. Der Admin hinterlegt den Schulkalender; aus ihm kommen die Ferien
(Eintraege, deren Titel ein Stichwort wie "Ferien" enthaelt). Der Server holt beide alle 30 Minuten neu, nur lesend.
Nichts geht von TrackingDRS zurueck nach Outlook.

Abruf nur ueber https und nur zu oeffentlichen Adressen (der Container haengt im Schulnetz und im VPN).
Ohne die Pakete python3-icalendar und python3-recurring-ical-events bleibt der Rest der Anwendung lauffaehig.
"""
import datetime
import ipaddress
import socket
import urllib.parse
import urllib.request

from . import db, termine
from .projekte import ProjektFehler, montag

try:
    import icalendar
    import recurring_ical_events
except ImportError:   # lokal ohne Pakete: Abos melden einen Fehler, alles andere laeuft
    icalendar = recurring_ical_events = None

ABRUF_ALLE = datetime.timedelta(minutes=30)
MAX_GROESSE = 5 * 1024 * 1024
TAGE_ZURUECK, TAGE_VORAUS = 60, 230
STICHWOERTER = "Ferien, Feiertag, beweglicher Ferientag, unterrichtsfrei"
TAG = datetime.timedelta(days=1)


# --- Adresse pruefen und herunterladen ---

def url_pruefen(url):
    url = (url or "").strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[9:]
    teile = urllib.parse.urlsplit(url)
    if teile.scheme != "https" or not teile.hostname or len(url) > 2000:
        raise ProjektFehler("Bitte den vollständigen ICS-Link angeben (beginnt mit https:// oder webcal://).")
    return url


def _oeffentlich(url):
    """Nur Adressen im Internet: kein Zugriff auf Schulnetz, VPN oder den Container selbst."""
    host = urllib.parse.urlsplit(url).hostname
    try:
        adressen = {a[4][0] for a in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
    except OSError:
        raise ProjektFehler("Der Server %s ist nicht erreichbar." % host)
    for a in adressen:
        if not ipaddress.ip_address(a.split("%")[0]).is_global:
            raise ProjektFehler("Kalender-Abos gehen nur zu Adressen im Internet.")


class _Weiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, neu):
        neu = url_pruefen(urllib.parse.urljoin(req.full_url, neu))
        _oeffentlich(neu)
        return super().redirect_request(req, fp, code, msg, headers, neu)


def herunterladen(url):
    _oeffentlich(url)
    oeffner = urllib.request.build_opener(_Weiterleitung)
    try:
        with oeffner.open(urllib.request.Request(url, headers={"User-Agent": "TrackingDRS"}), timeout=20) as antwort:
            daten = antwort.read(MAX_GROESSE + 1)
    except ProjektFehler:
        raise
    except Exception as f:
        raise ProjektFehler("Abruf fehlgeschlagen: %s" % (getattr(f, "reason", None) or f))
    if len(daten) > MAX_GROESSE:
        raise ProjektFehler("Der Kalender ist zu groß (höchstens 5 MB).")
    return daten


# --- ICS auswerten ---

def _lokal(wert):
    if wert.tzinfo is not None:
        wert = wert.astimezone(db.ZONE)
    return wert.replace(tzinfo=None, second=0, microsecond=0)


def termine_aus_ics(daten, von, bis):
    """Eintraege zwischen von und bis (date), Serien aufgeloest. Zeiten in Berliner Ortszeit; ganztaegige Eintraege
    mit Datum, Ende einschliesslich."""
    if icalendar is None:
        raise ProjektFehler("Für Kalender-Abos fehlen die Pakete python3-icalendar und python3-recurring-ical-events "
                            "(trackingdrs-update installiert sie).")
    try:
        cal = icalendar.Calendar.from_ical(daten)
        ereignisse = recurring_ical_events.of(cal).between(von, bis)
    except Exception:
        raise ProjektFehler("Unter dieser Adresse liegt kein lesbarer Kalender (ICS).")
    liste = []
    for e in ereignisse:
        if str(e.get("STATUS", "")).upper() == "CANCELLED" or e.get("DTSTART") is None:
            continue
        start = e.get("DTSTART").dt
        ende = e.get("DTEND").dt if e.get("DTEND") is not None else None
        if ende is None and e.get("DURATION") is not None:
            ende = start + e.get("DURATION").dt
        titel = str(e.get("SUMMARY") or "(ohne Titel)").strip()[:200]
        ort = str(e.get("LOCATION") or "").strip()[:200]
        if isinstance(start, datetime.datetime):
            start = _lokal(start)
            ende = _lokal(ende) if isinstance(ende, datetime.datetime) else start
            liste.append({"beginn": start.isoformat(timespec="minutes"), "ende": max(ende, start).isoformat(timespec="minutes"),
                          "ganztags": False, "titel": titel, "ort": ort})
        else:
            letzter = (ende - TAG) if isinstance(ende, datetime.date) and ende > start else start
            liste.append({"beginn": start.isoformat(), "ende": letzter.isoformat(), "ganztags": True, "titel": titel, "ort": ort})
    liste.sort(key=lambda t: t["beginn"])
    return liste


def ferien_aus(liste, stichwoerter):
    """Ganztaegige Eintraege, deren Titel ein Stichwort enthaelt, als Ferien (von, bis, name)."""
    woerter = [w.strip().lower() for w in (stichwoerter or "").split(",") if w.strip()]
    return sorted({(t["beginn"][:10], t["ende"][:10], t["titel"][:80]) for t in liste
                   if t["ganztags"] and any(w in t["titel"].lower() for w in woerter)})


# --- Abos verwalten ---

def _abo(con, art, lehrkraft_id):
    return con.execute("SELECT * FROM kalender_abo WHERE art = ? AND COALESCE(lehrkraft_id, 0) = ?",
                       (art, lehrkraft_id or 0)).fetchone()


def abo_status(con, art, lehrkraft_id=None):
    """Was die Oberflaeche ueber ein Abo zeigt. Die Adresse selbst ist geheim (wer sie hat, liest mit): nur der Server."""
    a = _abo(con, art, lehrkraft_id)
    if a is None:
        return None
    teile = urllib.parse.urlsplit(a["url"])
    return {"adresse": "%s://%s/…" % (teile.scheme, teile.hostname), "stand": a["stand"], "versuch": a["versuch"],
            "fehler": a["fehler"], "anzahl": a["anzahl"]}


def abo_setzen(con, art, lehrkraft_id, url):
    url = url_pruefen(url)
    with db.transaktion(con):
        a = _abo(con, art, lehrkraft_id)
        if a is None:
            con.execute("INSERT INTO kalender_abo (art, lehrkraft_id, url) VALUES (?, ?, ?)", (art, lehrkraft_id, url))
        else:
            con.execute("UPDATE kalender_abo SET url = ?, versuch = NULL, stand = NULL, fehler = NULL WHERE id = ?", (url, a["id"]))
    return abrufen(con, art, lehrkraft_id)


def abo_entfernen(con, art, lehrkraft_id):
    with db.transaktion(con):
        a = _abo(con, art, lehrkraft_id)
        if a is not None:
            con.execute("DELETE FROM kalender_abo WHERE id = ?", (a["id"],))   # Termine fallen mit (Spiegel des Abrufs)
            if art == "schule":
                _ferien_uebernehmen(con, [])


def _ferien_uebernehmen(con, neu):
    """Ferien aus dem Schulkalender ersetzen (quelle 'abo'); von Hand eingetragene bleiben. Laeuft in einer Transaktion."""
    alt = sorted((z["von"], z["bis"], z["name"]) for z in con.execute("SELECT * FROM ferien WHERE quelle = 'abo' AND aktiv = 1"))
    if alt == sorted(neu):
        return False
    con.execute("UPDATE ferien SET aktiv = 0 WHERE quelle = 'abo' AND aktiv = 1")
    con.executemany("INSERT INTO ferien (von, bis, name, quelle) VALUES (?, ?, ?, 'abo')", neu)
    db.ereignis(con, None, "system", "System", "ferien_abo", anzahl=len(neu))
    termine._buchungen_pruefen(con, "System", "system")
    return True


def abrufen(con, art, lehrkraft_id=None, laden=herunterladen):
    """Holt ein Abo neu. Bei einem Fehler bleiben die zuletzt geholten Termine stehen, der Fehler wird gemerkt.
    Rueckgabe: Status des Abos."""
    a = _abo(con, art, lehrkraft_id)
    if a is None:
        raise ProjektFehler("Es ist kein Kalender hinterlegt.")
    jetzt = db.jetzt()
    heute = datetime.date.fromisoformat(jetzt[:10])
    try:
        liste = termine_aus_ics(laden(a["url"]), heute - TAGE_ZURUECK * TAG, heute + TAGE_VORAUS * TAG)
    except ProjektFehler as f:
        con.execute("UPDATE kalender_abo SET versuch = ?, fehler = ? WHERE id = ?", (jetzt, str(f), a["id"]))
        return abo_status(con, art, lehrkraft_id)
    with db.transaktion(con):
        con.execute("DELETE FROM kalender_termin WHERE abo_id = ?", (a["id"],))
        con.executemany("INSERT INTO kalender_termin (abo_id, beginn, ende, ganztags, titel, ort) VALUES (?, ?, ?, ?, ?, ?)",
                        [(a["id"], t["beginn"], t["ende"], 1 if t["ganztags"] else 0, t["titel"], t["ort"]) for t in liste])
        con.execute("UPDATE kalender_abo SET versuch = ?, stand = ?, fehler = NULL, anzahl = ? WHERE id = ?",
                    (jetzt, jetzt, len(liste), a["id"]))
        if art == "schule":
            _ferien_uebernehmen(con, ferien_aus(liste, db.einstellung(con, "schulkalender_stichwoerter", STICHWOERTER)))
    return abo_status(con, art, lehrkraft_id)


def faellige_abrufen(con, laden=herunterladen):
    """Fuer den Takt des Servers: alle Abos, deren letzter Versuch mehr als 30 Minuten her ist."""
    grenze = (datetime.datetime.fromisoformat(db.jetzt()) - ABRUF_ALLE).isoformat()
    neu = 0
    for a in con.execute("SELECT * FROM kalender_abo WHERE versuch IS NULL OR versuch < ?", (grenze,)).fetchall():
        status = abrufen(con, a["art"], a["lehrkraft_id"], laden)
        neu += 0 if status["fehler"] else 1
    return neu


# --- Eintraege fuer Cockpit und Kalender ---

def meine_projekte(con, konto, klasse=None):
    """Laufende Projekte, die die Lehrkraft betreut (Admins: nur die eigenen, das Cockpit ist persoenlich)."""
    return [p for p in con.execute("SELECT p.* FROM projekt p JOIN projekt_lehrkraft pl ON pl.projekt_id = p.id "
                                   "WHERE pl.lehrkraft_id = ? AND p.archiviert = 0 ORDER BY p.klasse, p.titel", (konto["id"],))
            if not klasse or p["klasse"].strip().lower() == klasse.strip().lower()]


def eintraege(con, konto, von, bis, klasse=None):
    """Alles fuer den Kalender zwischen von und bis (date): Dienst (nur eigener), Ferien, eigene Ausfaelle,
    Projekttage eigener Regeln (mit fehlenden Buchungen), Besprechungen und Meilensteine eigener Projekte."""
    v, b = von.isoformat(), bis.isoformat()
    liste = []
    a = _abo(con, "dienst", konto["id"])
    if a is not None:
        for t in con.execute("SELECT * FROM kalender_termin WHERE abo_id = ? AND beginn <= ? AND ende >= ? ORDER BY beginn",
                             (a["id"], b + "T23:59", v)):
            liste.append({"art": "dienst", "datum": t["beginn"][:10], "bis": t["ende"][:10],
                          "zeit": None if t["ganztags"] else t["beginn"][11:16],
                          "zeit_bis": None if t["ganztags"] else t["ende"][11:16], "titel": t["titel"], "ort": t["ort"]})
    for f in con.execute("SELECT * FROM ferien WHERE aktiv = 1 AND bis >= ? AND von <= ? ORDER BY von", (v, b)):
        liste.append({"art": "ferien", "datum": f["von"], "bis": f["bis"], "titel": f["name"]})
    for f in con.execute("SELECT * FROM ausfall WHERE aktiv = 1 AND lehrkraft_id = ? AND bis >= ? AND von <= ? ORDER BY von",
                         (konto["id"], v, b)):
        if not klasse or not f["klasse"] or f["klasse"].strip().lower() == klasse.strip().lower():
            liste.append({"art": "ausfall", "datum": f["von"], "bis": f["bis"], "titel": f["grund"], "klasse": f["klasse"]})

    jetzt = db.jetzt()
    wochen = ((montag(bis) - montag(von)).days // 7) + 1
    for t in termine.uebersicht(con, konto, montag(von).isoformat(), wochen)["tage"]:
        if not v <= t["datum"] <= b or t["entfaellt"] or (klasse and t["klasse"].strip().lower() != klasse.strip().lower()):
            continue
        fehlen = [p["titel"] for p in t["ohne_termin"]] if jetzt >= t["schluss"] else []
        liste.append({"art": "projekttag", "datum": t["datum"], "titel": t["klasse"], "zeit": t["fenster_von"],
                      "zeit_bis": t["fenster_bis"], "fehlen": fehlen})

    projekte = meine_projekte(con, konto, klasse)
    ids = [p["id"] for p in projekte]
    if ids:
        frage = ",".join("?" * len(ids))
        for z in con.execute("SELECT b.*, p.titel FROM buchung b JOIN projekt p ON p.id = b.projekt_id WHERE b.aktiv = 1 "
                             "AND b.datum BETWEEN ? AND ? AND b.projekt_id IN (%s) ORDER BY b.datum, b.uhrzeit" % frage, [v, b] + ids):
            liste.append({"art": "besprechung", "datum": z["datum"], "zeit": z["uhrzeit"], "titel": z["titel"],
                          "projekt_id": z["projekt_id"]})
        for p in projekte:
            tage = {}
            for t in termine.projekt_tage(con, p, montag(von), montag(bis) + 6 * TAG):
                tage.setdefault(t["woche"], t["datum"])
            for m in con.execute("SELECT * FROM meilenstein WHERE projekt_id = ? AND verworfen = 0 AND woche BETWEEN ? AND ?",
                                 (p["id"], montag(von).isoformat(), b)):
                datum = tage.get(m["woche"], m["woche"])   # am Projekttag der Woche, sonst am Montag
                if v <= datum <= b:
                    liste.append({"art": "meilenstein", "datum": datum, "titel": m["titel"], "projekt": p["titel"],
                                  "projekt_id": p["id"], "woche": m["woche"]})
    reihenfolge = {"ferien": 0, "ausfall": 1, "dienst": 2, "projekttag": 3, "besprechung": 4, "meilenstein": 5}
    liste.sort(key=lambda e: (e["datum"], reihenfolge[e["art"]], e.get("zeit") or ""))
    return liste
