"""Webserver: HTTPS fuer den Lehrerbereich (Port 443). HTTP (Port 80) bedient nur die Team-Seiten, ihre Schnittstelle,
die Dateien unter /static, das Logo und das Stammzertifikat (Schuelergeraete haben das Zertifikat nicht, die Team-Links
sollen ohne Warnung aufgehen); alles andere leitet nach HTTPS um.

Ohne Zertifikat (oder mit TRACKINGDRS_OHNE_TLS=1 zum lokalen Testen) laeuft die ganze Seite ueber HTTP.
Umgebungsvariablen: TRACKINGDRS_DATEN, TRACKINGDRS_TLS_DIR, TRACKINGDRS_HTTPS_PORT, TRACKINGDRS_HTTP_PORT,
TRACKINGDRS_BIND, TRACKINGDRS_OHNE_TLS.

Alle Aenderungen laufen ueber POST mit JSON und dem Kopf X-TrackingDRS: 1 (Schutz vor fremden Formularen).
Lehrkraefte melden sich per Cookie an, Teams nur ueber ihren geheimen Link.
"""
import base64
import binascii
import json
import mimetypes
import os
import re
import socket
import ssl
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import VERSION, db, einstellungen, konten, projekte, sheet, termine

BASIS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(BASIS, "web")
DATEN_DIR = os.environ.get("TRACKINGDRS_DATEN", "/var/lib/trackingdrs")
TLS_DIR = os.environ.get("TRACKINGDRS_TLS_DIR", os.path.join(DATEN_DIR, "tls"))
HTTPS_PORT = int(os.environ.get("TRACKINGDRS_HTTPS_PORT", "443"))
HTTP_PORT = int(os.environ.get("TRACKINGDRS_HTTP_PORT", "80"))
BIND = os.environ.get("TRACKINGDRS_BIND", "0.0.0.0")
OHNE_TLS = os.environ.get("TRACKINGDRS_OHNE_TLS") == "1"

COOKIE = "tdrs"
MAX_BODY = 2 * 1024 * 1024   # Logo als Base64
SEITEN = {"/anmelden": "anmelden.html", "/lehrer": "lehrer.html", "/einrichtung": "einrichtung.html"}
STATISCH = re.compile(r"/static/([a-z0-9_-]+\.(css|js|svg|png|ico))")
TEAM_SEITE = re.compile(r"/t/[A-Za-z0-9_-]{20,64}")
# was ueber HTTP erreichbar ist, wenn HTTPS laeuft
TEAM_PFADE = re.compile(r"/t/[A-Za-z0-9_-]{20,64}|/api/t/[A-Za-z0-9_-]{20,64}(/[a-z0-9/_-]*)?"
                        r"|/static/[a-z0-9_-]+\.(css|js|svg|png|ico)|/logo|/ca\.crt")
CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")

SPERRE = konten.Sperre()


class Fehler(Exception):
    def __init__(self, status, meldung):
        super().__init__(meldung)
        self.status = status
        self.meldung = meldung


def _ganzzahl(wert):
    try:
        return int(wert)
    except (TypeError, ValueError):
        raise Fehler(400, "Ungültige Angabe.")


class Handler(BaseHTTPRequestHandler):
    server_version = "TrackingDRS"
    sys_version = ""
    timeout = 30
    protocol_version = "HTTP/1.1"
    nur_team = False   # True: HTTP-Port neben HTTPS, nur Team-Pfade

    # --- Hilfen ---

    def _kopfzeilen(self, status, typ, laenge, extra=()):
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(laenge))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")   # der Team-Link steht in der Adresse
        self.send_header("Content-Security-Policy", CSP)
        for name, wert in extra:
            self.send_header(name, wert)
        self.end_headers()

    def antwort(self, status, inhalt, typ="application/json; charset=utf-8", extra=(), cache=False):
        if not isinstance(inhalt, bytes):
            inhalt = json.dumps(inhalt, ensure_ascii=False).encode("utf-8")
        extra = list(extra) + ([] if cache else [("Cache-Control", "no-store")])
        self._kopfzeilen(status, typ, len(inhalt), extra)
        if self.command != "HEAD":
            self.wfile.write(inhalt)

    def umleiten(self, ziel):
        self._kopfzeilen(303, "text/plain; charset=utf-8", 0, [("Location", ziel), ("Cache-Control", "no-store")])

    def datei(self, pfad, typ=None, cache=False):
        try:
            with open(pfad, "rb") as f:
                inhalt = f.read()
        except OSError:
            return self.antwort(404, {"fehler": "Nicht gefunden."})
        typ = typ or (mimetypes.guess_type(pfad)[0] or "application/octet-stream")
        if typ.startswith("text/") or typ in ("application/javascript", "image/svg+xml"):
            typ += "; charset=utf-8"
        self.antwort(200, inhalt, typ, cache=cache)

    def body(self):
        """JSON-Inhalt einer POST-Anfrage. Liest immer den ganzen Inhalt (sonst bricht die Verbindung ab)."""
        laenge = _ganzzahl(self.headers.get("Content-Length") or 0)
        if laenge > MAX_BODY:
            raise Fehler(413, "Die Anfrage ist zu groß.")
        roh = self.rfile.read(laenge) if laenge else b""
        if self.headers.get("X-TrackingDRS") != "1":
            raise Fehler(403, "Anfrage abgelehnt.")
        if not roh:
            return {}
        try:
            daten = json.loads(roh.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise Fehler(400, "Ungültige Daten.")
        if not isinstance(daten, dict):
            raise Fehler(400, "Ungültige Daten.")
        return daten

    def cookie(self):
        for teil in (self.headers.get("Cookie") or "").split(";"):
            name, _, wert = teil.strip().partition("=")
            if name == COOKIE:
                return wert
        return None

    def cookie_setzen(self, wert, max_age):
        sicher = "; Secure" if getattr(self.server, "ist_tls", False) else ""
        return ("Set-Cookie", "%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d%s" % (COOKIE, wert, max_age, sicher))

    def adresse(self):
        return self.client_address[0]

    def konto(self, con, pflicht=True, vorlaeufig_ok=False):
        k = konten.sitzung_pruefen(con, self.cookie())
        if k is None:
            if pflicht:
                raise Fehler(401, "Bitte anmelden.")
            return None
        if k["pw_vorlaeufig"] and not vorlaeufig_ok:
            raise Fehler(403, "Bitte zuerst ein eigenes Passwort festlegen.")
        return k

    # --- Verteilung ---

    def do_GET(self):
        self._verteilen("GET")

    def do_HEAD(self):
        self._verteilen("GET")

    def do_POST(self):
        self._verteilen("POST")

    def zu_https(self, methode):
        """Lehrerpfade auf dem HTTP-Port: GET nach HTTPS umleiten, POST ablehnen (Passwoerter nie unverschluesselt)."""
        laenge = _ganzzahl(self.headers.get("Content-Length") or 0)
        if 0 < laenge <= MAX_BODY:
            self.rfile.read(laenge)
        if methode == "POST" or laenge > MAX_BODY:
            return self.antwort(403, {"fehler": "Bitte die Seite über https:// aufrufen."})
        host = (self.headers.get("Host") or "").split(":")[0]
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host):
            host = socket.gethostname()
        port = "" if HTTPS_PORT == 443 else ":%d" % HTTPS_PORT
        self._kopfzeilen(301, "text/plain; charset=utf-8", 0,
                         [("Location", "https://%s%s%s" % (host, port, self.path if self.path.startswith("/") else "/"))])

    def _verteilen(self, methode):
        pfad = urllib.parse.urlsplit(self.path).path
        if self.nur_team and not TEAM_PFADE.fullmatch(pfad):
            try:
                return self.zu_https(methode)
            except Fehler as f:
                return self.antwort(f.status, {"fehler": f.meldung})
        con = None
        try:
            con = db.verbinden(self.server.db_pfad)
            if methode == "GET" and not pfad.startswith("/api/"):
                return self.seite(con, pfad)
            for m, muster, funktion in ROUTEN:
                treffer = muster.fullmatch(pfad)
                if m == methode and treffer:
                    daten = self.body() if methode == "POST" else {}
                    return funktion(self, con, daten, *treffer.groups())
            if methode == "POST":
                self.body()
            raise Fehler(404, "Nicht gefunden.")
        except Fehler as f:
            self.antwort(f.status, {"fehler": f.meldung})
        except (konten.KontoFehler, projekte.ProjektFehler, einstellungen.EinstellungFehler) as f:
            self.antwort(400, {"fehler": str(f)})
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError, socket.timeout):
            pass
        except Exception as f:   # unerwartet: protokollieren, aber nichts Internes verraten
            print("FEHLER %s %s: %r" % (methode, _ohne_token(pfad), f), file=sys.stderr, flush=True)
            try:
                self.antwort(500, {"fehler": "Interner Fehler. Bitte später noch einmal versuchen."})
            except OSError:
                pass
        finally:
            if con is not None:
                con.close()

    def seite(self, con, pfad):
        if pfad == "/":
            if konten.sitzung_pruefen(con, self.cookie()):
                return self.umleiten("/lehrer")
            return self.umleiten("/einrichtung" if not konten.hat_konten(con) else "/anmelden")
        if pfad in SEITEN:
            return self.datei(os.path.join(WEB_DIR, SEITEN[pfad]), "text/html")
        if TEAM_SEITE.fullmatch(pfad):
            return self.datei(os.path.join(WEB_DIR, "team.html"), "text/html")
        treffer = STATISCH.fullmatch(pfad)
        if treffer:
            return self.datei(os.path.join(WEB_DIR, treffer.group(1)), cache=False)
        if pfad == "/ca.crt":
            return self.ca_zertifikat()
        if pfad == "/logo":
            return self.logo(con)
        raise Fehler(404, "Nicht gefunden.")

    def logo(self, con):
        pfad, typ = einstellungen.logo_pfad(con, os.path.dirname(self.server.db_pfad))
        if pfad is None:
            raise Fehler(404, "Kein Logo hinterlegt.")
        with open(pfad, "rb") as f:
            inhalt = f.read()
        # SVG nie als Dokument mit Skripten ausfuehren (sandbox), kurz zwischenspeichern
        self.antwort(200, inhalt, typ, extra=[("Content-Security-Policy", "sandbox"), ("Cache-Control", "max-age=300")],
                     cache=True)

    def ca_zertifikat(self):
        self.datei(os.path.join(TLS_DIR, "ca.crt"), "application/x-x509-ca-cert")

    def log_message(self, fmt, *args):   # keine Zugriffsprotokolle (Team-Links stehen in der Adresse)
        pass


def _ohne_token(pfad):
    return re.sub(r"/t/[A-Za-z0-9_-]+", "/t/…", pfad)


# --- Schnittstelle ---

def api_status(h, con, daten):
    h.antwort(200, {"version": VERSION, "eingerichtet": konten.hat_konten(con)})


def api_einrichtung(h, con, daten):
    wartezeit = SPERRE.wartezeit(h.adresse())
    if wartezeit:
        raise Fehler(429, "Zu viele Fehlversuche. Bitte %d Sekunden warten." % wartezeit)
    with db.transaktion(con):
        try:
            konto = konten.einrichten(con, daten.get("code"), daten.get("kuerzel"), daten.get("name"), daten.get("passwort"))
        except konten.KontoFehler as f:
            if "Einrichtungscode" in str(f):
                SPERRE.fehlversuch(h.adresse())
            raise
    print("Einrichtung: erstes Admin-Konto %s angelegt" % konto["kuerzel"], flush=True)
    wert, _ = konten.anmelden(con, konto["kuerzel"], daten.get("passwort"))
    h.antwort(200, {"konto": konto}, extra=[h.cookie_setzen(wert, konten.SITZUNG_S)])


def api_anmelden(h, con, daten):
    wartezeit = SPERRE.wartezeit(h.adresse())
    if wartezeit:
        raise Fehler(429, "Zu viele Fehlversuche. Bitte %d Sekunden warten." % wartezeit)
    try:
        wert, konto = konten.anmelden(con, daten.get("kuerzel"), daten.get("passwort"))
    except konten.KontoFehler:
        dauer = SPERRE.fehlversuch(h.adresse())
        print("Anmeldung fehlgeschlagen: %s von %s%s" % ((daten.get("kuerzel") or "")[:12], h.adresse(),
              ", gesperrt fuer %d s" % dauer if dauer else ""), flush=True)
        raise
    SPERRE.erfolg(h.adresse())
    h.antwort(200, {"konto": konto}, extra=[h.cookie_setzen(wert, konten.SITZUNG_S)])


def api_abmelden(h, con, daten):
    konten.abmelden(con, h.cookie())
    h.antwort(200, {"ok": True}, extra=[h.cookie_setzen("", 0)])


def api_ich(h, con, daten):
    # Team-Links gehen ueber HTTP (team_port), solange der Lehrerbereich ueber HTTPS laeuft
    h.antwort(200, {"konto": h.konto(con, vorlaeufig_ok=True), "team_port": HTTP_PORT if h.server.ist_tls else None})


def api_passwort(h, con, daten):
    k = h.konto(con, vorlaeufig_ok=True)
    with db.transaktion(con):
        konten.passwort_aendern(con, k["id"], daten.get("alt"), daten.get("neu"))
    wert = konten.sitzung_erzeugen(con, k["id"])   # alte Anmeldungen sind jetzt ungueltig, diese bleibt
    h.antwort(200, {"konto": konten.holen(con, k["id"])}, extra=[h.cookie_setzen(wert, konten.SITZUNG_S)])


def _admin(h, con):
    k = h.konto(con)
    if k["rolle"] != "admin":
        raise Fehler(403, "Nur für Admins.")
    return k


def api_lehrkraefte(h, con, daten):
    h.konto(con)
    h.antwort(200, {"lehrkraefte": konten.liste(con)})


def api_lehrkraft_anlegen(h, con, daten):
    a = _admin(h, con)
    with db.transaktion(con):
        neu = konten.anlegen(con, daten.get("kuerzel"), daten.get("name"), daten.get("rolle") or "lehrkraft",
                             daten.get("passwort"))
    print("Konto %s angelegt von %s" % (neu["kuerzel"], a["kuerzel"]), flush=True)
    h.antwort(200, {"lehrkraft": neu})


def api_lehrkraft_aendern(h, con, daten, lid):
    a = _admin(h, con)
    lid = _ganzzahl(lid)
    with db.transaktion(con):
        k = konten.aendern(con, lid, name=daten.get("name"), rolle=daten.get("rolle"), gesperrt=daten.get("gesperrt"))
        if daten.get("passwort"):
            konten.passwort_setzen(con, lid, daten["passwort"], vorlaeufig=True)
    print("Konto %s geaendert von %s" % (k["kuerzel"], a["kuerzel"]), flush=True)
    h.antwort(200, {"lehrkraft": konten.holen(con, lid)})


def api_einstellungen(h, con, daten):
    _admin(h, con)
    h.antwort(200, {"logo": db.einstellung(con, "logo")})


def api_logo(h, con, daten):
    a = _admin(h, con)
    try:
        inhalt = base64.b64decode(daten.get("inhalt") or "", validate=True)
    except (binascii.Error, ValueError):
        raise Fehler(400, "Die Datei konnte nicht gelesen werden.")
    art = einstellungen.logo_speichern(con, os.path.dirname(h.server.db_pfad), inhalt)
    print("Logo (%s) hochgeladen von %s" % (art, a["kuerzel"]), flush=True)
    h.antwort(200, {"logo": art})


def api_logo_entfernen(h, con, daten):
    _admin(h, con)
    einstellungen.logo_entfernen(con, os.path.dirname(h.server.db_pfad))
    h.antwort(200, {"logo": None})


def api_vorlagen(h, con, daten):
    h.konto(con)
    h.antwort(200, {"vorlagen": [{"schluessel": v["schluessel"], "name": v["name"]} for v in projekte.vorlagen(con)]})


def _abfrage(h, name, vorgabe=None):
    return (urllib.parse.parse_qs(urllib.parse.urlsplit(h.path).query).get(name) or [vorgabe])[0]


def api_projekte(h, con, daten):
    k = h.konto(con)
    liste = projekte.liste(con, k, archiviert=_abfrage(h, "archiv") == "1")
    for p in liste:
        p["warnungen"] = [w for w in termine.warnungen(con, p["id"]) if w["stufe"] == "warnung"]
    h.antwort(200, {"projekte": liste})


def api_projekt_anlegen(h, con, daten):
    k = h.konto(con)
    lehrkraefte = daten.get("lehrkraefte") or [k["id"]]
    pid = projekte.anlegen(con, k["kuerzel"], daten.get("titel"), daten.get("klasse"), daten.get("start"),
                           daten.get("ende"), lehrkraefte, daten.get("mitglieder") or [], daten.get("vorlage") or "standard",
                           daten.get("schuljahr"), daten.get("beschreibung"))
    h.antwort(200, {"projekt": projekte.details(con, pid)})


def _projekt(h, con, pid):
    k = h.konto(con)
    pid = _ganzzahl(pid)
    if not projekte.darf(con, k, pid):
        raise Fehler(404, "Dieses Projekt gibt es nicht oder du betreust es nicht.")
    return k, pid


def api_projekt(h, con, daten, pid):
    _k, pid = _projekt(h, con, pid)
    p = projekte.details(con, pid)
    p["warnungen"] = [w for w in termine.warnungen(con, pid) if w["stufe"] == "warnung"]
    h.antwort(200, {"projekt": p})


def api_projekt_aendern(h, con, daten, pid):
    k, pid = _projekt(h, con, pid)
    projekte.aendern(con, k["kuerzel"], pid, daten)
    h.antwort(200, {"projekt": projekte.details(con, pid)})


def api_mitglied_anlegen(h, con, daten, pid):
    k, pid = _projekt(h, con, pid)
    projekte.mitglied_anlegen(con, k["kuerzel"], pid, daten.get("vorname"), daten.get("nachname"))
    h.antwort(200, {"projekt": projekte.details(con, pid)})


def api_mitglied_aendern(h, con, daten, pid, mid):
    k, pid = _projekt(h, con, pid)
    projekte.mitglied_aendern(con, k["kuerzel"], pid, _ganzzahl(mid), daten)
    h.antwort(200, {"projekt": projekte.details(con, pid)})


def api_link_erneuern(h, con, daten, pid):
    k, pid = _projekt(h, con, pid)
    projekte.link_erneuern(con, k["kuerzel"], pid)
    h.antwort(200, {"projekt": projekte.details(con, pid)})


def api_archivieren(h, con, daten, pid):
    k, pid = _projekt(h, con, pid)
    projekte.archivieren(con, k["kuerzel"], pid, bool(daten.get("archiviert")))
    h.antwort(200, {"projekt": projekte.details(con, pid)})


def api_team(h, con, daten, token):
    sicht = projekte.team_sicht(con, token)
    if sicht is None:
        raise Fehler(404, "Dieser Link ist nicht (mehr) gültig. Bitte die Lehrkraft um den aktuellen Link.")
    h.antwort(200, {"projekt": sicht})


# --- Tracking-Sheet: gleiche Aktionen fuer Team (ueber den Link) und Lehrkraft (angemeldet) ---

def _team_projekt(con, token):
    zeile = con.execute("SELECT id FROM projekt WHERE link_token = ? AND archiviert = 0", (token,)).fetchone()
    if zeile is None:
        raise Fehler(404, "Dieser Link ist nicht (mehr) gültig. Bitte die Lehrkraft um den aktuellen Link.")
    return zeile[0]


def _sheet_antwort(h, con, pid):
    bekannt = urllib.parse.parse_qs(urllib.parse.urlsplit(h.path).query).get("stand")
    if bekannt and bekannt[0] == str(sheet.stand(con, pid)):
        return h.antwort(200, {"unveraendert": True})
    h.antwort(200, {"sheet": sheet.lesen(con, pid)})


def _sheet_aendern(h, con, pid, wer_art, wer, daten):
    ergebnis = sheet.aendern(con, pid, wer_art, wer, daten)
    h.antwort(200, {"ergebnis": ergebnis, "sheet": sheet.lesen(con, pid)})


def api_team_sheet(h, con, daten, token):
    _sheet_antwort(h, con, _team_projekt(con, token))


def api_team_sheet_aendern(h, con, daten, token):
    _sheet_aendern(h, con, _team_projekt(con, token), "team", "Team", daten)


def api_team_version(h, con, daten, token, vid):
    h.antwort(200, {"version": sheet.version_lesen(con, _team_projekt(con, token), _ganzzahl(vid))})


def api_team_verlauf(h, con, daten, token, aid):
    h.antwort(200, {"verlauf": sheet.aufgabe_verlauf(con, _team_projekt(con, token), aid)})


def api_sheet(h, con, daten, pid):
    _k, pid = _projekt(h, con, pid)
    _sheet_antwort(h, con, pid)


def api_sheet_aendern(h, con, daten, pid):
    k, pid = _projekt(h, con, pid)
    _sheet_aendern(h, con, pid, "lehrkraft", k["kuerzel"], daten)


def api_version(h, con, daten, pid, vid):
    _k, pid = _projekt(h, con, pid)
    h.antwort(200, {"version": sheet.version_lesen(con, pid, _ganzzahl(vid))})


def api_verlauf(h, con, daten, pid, aid):
    _k, pid = _projekt(h, con, pid)
    h.antwort(200, {"verlauf": sheet.aufgabe_verlauf(con, pid, aid)})


def api_basisplan(h, con, daten, pid):
    k, pid = _projekt(h, con, pid)
    sheet.basisplan_setzen(con, pid, k["kuerzel"])
    h.antwort(200, {"sheet": sheet.lesen(con, pid)})


# --- Termine ---

def _termin_aendern(h, con, pid, wer_art, wer, daten):
    if daten.get("stornieren"):
        termine.stornieren(con, pid, wer_art, wer, daten.get("woche"))
    else:
        termine.buchen(con, pid, wer_art, wer, daten.get("regel_id"), daten.get("datum"), daten.get("uhrzeit"))
    lehrkraft = wer_art == "lehrkraft"
    h.antwort(200, {"termine": termine.termin_sicht(con, pid, lehrkraft=lehrkraft, wochen=6 if lehrkraft else 4),
                    "warnungen": termine.warnungen(con, pid)})


def api_team_termine(h, con, daten, token):
    pid = _team_projekt(con, token)
    h.antwort(200, {"termine": termine.termin_sicht(con, pid), "warnungen": termine.warnungen(con, pid)})


def api_team_termin(h, con, daten, token):
    _termin_aendern(h, con, _team_projekt(con, token), "team", "Team", daten)


def api_projekt_termine(h, con, daten, pid):
    _k, pid = _projekt(h, con, pid)
    h.antwort(200, {"termine": termine.termin_sicht(con, pid, lehrkraft=True, wochen=6),
                    "warnungen": termine.warnungen(con, pid)})


def api_projekt_termin(h, con, daten, pid):
    k, pid = _projekt(h, con, pid)
    _termin_aendern(h, con, pid, "lehrkraft", k["kuerzel"], daten)


def api_termine(h, con, daten):
    k = h.konto(con)
    wochen = min(max(_ganzzahl(_abfrage(h, "wochen", "4")), 1), 12)
    h.antwort(200, termine.uebersicht(con, k, _abfrage(h, "von"), wochen))


def api_regel_anlegen(h, con, daten):
    termine.regel_anlegen(con, h.konto(con), daten)
    h.antwort(200, {"ok": True})


def api_regel_aendern(h, con, daten, rid):
    termine.regel_aendern(con, h.konto(con), rid, daten)
    h.antwort(200, {"ok": True})


def api_tag_anpassen(h, con, daten, rid):
    termine.tag_anpassen(con, h.konto(con), rid, daten.get("datum"), daten)
    h.antwort(200, {"ok": True})


def api_ausfall_anlegen(h, con, daten):
    termine.ausfall_anlegen(con, h.konto(con), daten)
    h.antwort(200, {"ok": True})


def api_ausfall_entfernen(h, con, daten, aid):
    termine.ausfall_entfernen(con, h.konto(con), _ganzzahl(aid))
    h.antwort(200, {"ok": True})


def api_ferien_anlegen(h, con, daten):
    termine.ferien_anlegen(con, h.konto(con), daten)
    h.antwort(200, {"ok": True})


def api_ferien_entfernen(h, con, daten, fid):
    termine.ferien_entfernen(con, h.konto(con), _ganzzahl(fid))
    h.antwort(200, {"ok": True})


ROUTEN = [(m, re.compile(p), f) for m, p, f in [
    ("GET", r"/api/status", api_status),
    ("POST", r"/api/einrichtung", api_einrichtung),
    ("POST", r"/api/anmelden", api_anmelden),
    ("POST", r"/api/abmelden", api_abmelden),
    ("GET", r"/api/ich", api_ich),
    ("POST", r"/api/passwort", api_passwort),
    ("GET", r"/api/lehrkraefte", api_lehrkraefte),
    ("POST", r"/api/lehrkraefte", api_lehrkraft_anlegen),
    ("POST", r"/api/lehrkraefte/(\d+)", api_lehrkraft_aendern),
    ("GET", r"/api/vorlagen", api_vorlagen),
    ("GET", r"/api/einstellungen", api_einstellungen),
    ("POST", r"/api/einstellungen/logo", api_logo),
    ("POST", r"/api/einstellungen/logo-entfernen", api_logo_entfernen),
    ("GET", r"/api/projekte", api_projekte),
    ("POST", r"/api/projekte", api_projekt_anlegen),
    ("GET", r"/api/projekte/(\d+)", api_projekt),
    ("POST", r"/api/projekte/(\d+)", api_projekt_aendern),
    ("POST", r"/api/projekte/(\d+)/mitglieder", api_mitglied_anlegen),
    ("POST", r"/api/projekte/(\d+)/mitglieder/(\d+)", api_mitglied_aendern),
    ("POST", r"/api/projekte/(\d+)/link-erneuern", api_link_erneuern),
    ("POST", r"/api/projekte/(\d+)/archivieren", api_archivieren),
    ("GET", r"/api/projekte/(\d+)/sheet", api_sheet),
    ("POST", r"/api/projekte/(\d+)/sheet", api_sheet_aendern),
    ("GET", r"/api/projekte/(\d+)/version/(\d+)", api_version),
    ("GET", r"/api/projekte/(\d+)/aufgabe/(\d+)/verlauf", api_verlauf),
    ("POST", r"/api/projekte/(\d+)/basisplan", api_basisplan),
    ("GET", r"/api/projekte/(\d+)/termine", api_projekt_termine),
    ("POST", r"/api/projekte/(\d+)/termin", api_projekt_termin),
    ("GET", r"/api/termine", api_termine),
    ("POST", r"/api/termine/regeln", api_regel_anlegen),
    ("POST", r"/api/termine/regeln/(\d+)", api_regel_aendern),
    ("POST", r"/api/termine/regeln/(\d+)/tag", api_tag_anpassen),
    ("POST", r"/api/termine/ausfaelle", api_ausfall_anlegen),
    ("POST", r"/api/termine/ausfaelle/(\d+)/entfernen", api_ausfall_entfernen),
    ("POST", r"/api/termine/ferien", api_ferien_anlegen),
    ("POST", r"/api/termine/ferien/(\d+)/entfernen", api_ferien_entfernen),
    ("GET", r"/api/t/([A-Za-z0-9_-]{20,64})", api_team),
    ("GET", r"/api/t/([A-Za-z0-9_-]{20,64})/sheet", api_team_sheet),
    ("POST", r"/api/t/([A-Za-z0-9_-]{20,64})/sheet", api_team_sheet_aendern),
    ("GET", r"/api/t/([A-Za-z0-9_-]{20,64})/version/(\d+)", api_team_version),
    ("GET", r"/api/t/([A-Za-z0-9_-]{20,64})/aufgabe/(\d+)/verlauf", api_team_verlauf),
    ("GET", r"/api/t/([A-Za-z0-9_-]{20,64})/termine", api_team_termine),
    ("POST", r"/api/t/([A-Za-z0-9_-]{20,64})/termin", api_team_termin),
]]


# --- HTTP neben HTTPS: nur die Team-Seiten ---

class TeamHandler(Handler):
    nur_team = True


class TLSServer(ThreadingHTTPServer):
    """HTTPS. Der TLS-Handschlag laeuft im Thread der Anfrage, nicht in der Annahmeschleife:
    ein Client, der die Verbindung oeffnet und dann nichts schickt, haelt so niemanden auf."""
    daemon_threads = True
    ist_tls = True

    def __init__(self, adresse, handler, kontext, db_pfad):
        super().__init__(adresse, handler)
        self.kontext = kontext
        self.db_pfad = db_pfad

    def finish_request(self, request, client_address):
        request.settimeout(Handler.timeout)
        try:
            tls = self.kontext.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):   # z.B. Browser lehnt das Zertifikat ab
            return
        try:
            self.RequestHandlerClass(tls, client_address, self)
        finally:
            # nur die Schreibrichtung schliessen und den Rest noch lesen: ein hartes Schliessen mit ungelesenen
            # Daten schickt ein RST, und der Browser verwirft dann womoeglich die schon gesendete Antwort
            try:
                tls.shutdown(socket.SHUT_WR)
                tls.settimeout(1.0)
                while tls.recv(4096):
                    pass
            except (OSError, ssl.SSLError):
                pass
            tls.close()


class HTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    ist_tls = False

    def __init__(self, adresse, handler, db_pfad=None):
        super().__init__(adresse, handler)
        self.db_pfad = db_pfad


def takt(db_pfad):
    """Jede Minute: faellige Versionen zum Buchungsschluss anlegen."""
    while True:
        con = None
        try:
            con = db.verbinden(db_pfad)
            neu = termine.faellige_versionen(con)
            if neu:
                print("Versionen zum Buchungsschluss: %d neu" % neu, flush=True)
        except Exception as f:
            print("FEHLER Takt: %r" % f, file=sys.stderr, flush=True)
        finally:
            if con is not None:
                con.close()
        time.sleep(60)


def tls_kontext():
    zert, schluessel = os.path.join(TLS_DIR, "server.crt"), os.path.join(TLS_DIR, "server.key")
    if not (os.path.exists(zert) and os.path.exists(schluessel)):
        return None
    kontext = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    kontext.minimum_version = ssl.TLSVersion.TLSv1_2
    kontext.load_cert_chain(zert, schluessel)
    return kontext


def main():
    con = db.oeffnen(DATEN_DIR)
    code = konten.einrichtungscode(con)
    con.close()
    db_pfad = os.path.join(DATEN_DIR, "trackingdrs.sqlite")
    kontext = None if OHNE_TLS else tls_kontext()
    if kontext is None:
        if not OHNE_TLS:
            print("HTTPS aus: kein Zertifikat in %s (trackingdrs-tls). Alles laeuft ueber HTTP." % TLS_DIR, flush=True)
        server = HTTPServer((BIND, HTTP_PORT), Handler, db_pfad)
        print("TrackingDRS %s auf http://%s:%d" % (VERSION, BIND, HTTP_PORT), flush=True)
    else:
        server = TLSServer((BIND, HTTPS_PORT), Handler, kontext, db_pfad)
        team = HTTPServer((BIND, HTTP_PORT), TeamHandler, db_pfad)
        threading.Thread(target=team.serve_forever, daemon=True).start()
        print("TrackingDRS %s auf https://%s:%d (http :%d nur fuer Team-Links)" % (VERSION, BIND, HTTPS_PORT, HTTP_PORT),
              flush=True)
    threading.Thread(target=takt, args=(db_pfad,), daemon=True).start()
    if code:
        print("Noch kein Konto: Einrichtung unter /einrichtung, Code mit  trackingdrs einrichtungscode", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
