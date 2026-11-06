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

from . import (VERSION, anfragen, besprechung, bestellung, cockpit, db, einstellungen, export, extras, hilfe, kalender, konten, notizen, pdf,
               projekte, sheet, tafel, termine, updates, vpn)

BASIS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(BASIS, "web")
DATEN_DIR = os.environ.get("TRACKINGDRS_DATEN", "/var/lib/trackingdrs")
TLS_DIR = os.environ.get("TRACKINGDRS_TLS_DIR", os.path.join(DATEN_DIR, "tls"))
HTTPS_PORT = int(os.environ.get("TRACKINGDRS_HTTPS_PORT", "443"))
HTTP_PORT = int(os.environ.get("TRACKINGDRS_HTTP_PORT", "80"))
BIND = os.environ.get("TRACKINGDRS_BIND", "0.0.0.0")
OHNE_TLS = os.environ.get("TRACKINGDRS_OHNE_TLS") == "1"

COOKIE = "tdrs"
MAX_BODY = 12 * 1024 * 1024   # Mindmap (PDF bis 8 MB) als Base64
SEITEN = {"/anmelden": "anmelden.html", "/lehrer": "lehrer.html", "/einrichtung": "einrichtung.html", "/tafel": "tafel.html",
          "/bericht": "bericht.html"}
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
        except (konten.KontoFehler, projekte.ProjektFehler, einstellungen.EinstellungFehler, updates.UpdateFehler,
                vpn.VpnFehler) as f:
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
    k = h.konto(con, vorlaeufig_ok=True)
    h.antwort(200, {"konto": k, "team_port": HTTP_PORT if h.server.ist_tls else None,
                    "update": updates.kurz() if k["rolle"] == "admin" else None,
                    "vpn": vpn.kurz() if k["rolle"] == "admin" else None})


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
    h.antwort(200, {"logo": db.einstellung(con, "logo"), "schulkalender": kalender.abo_status(con, "schule"),
                    "stichwoerter": db.einstellung(con, "schulkalender_stichwoerter", kalender.STICHWOERTER)})


def api_schulkalender(h, con, daten):
    """Schulkalender (Ferien) setzen: neue Adresse und/oder Stichwoerter; danach sofort abrufen."""
    a = _admin(h, con)
    if daten.get("stichwoerter") is not None:
        woerter = ", ".join(w.strip() for w in str(daten["stichwoerter"]).split(",") if w.strip())[:300]
        if not woerter:
            raise Fehler(400, "Bitte mindestens ein Stichwort angeben, z. B. Ferien.")
        db.einstellung_setzen(con, "schulkalender_stichwoerter", woerter)
    if daten.get("url"):
        status = kalender.abo_setzen(con, "schule", None, daten["url"])
        print("Schulkalender gesetzt von %s" % a["kuerzel"], flush=True)
    elif kalender.abo_status(con, "schule"):
        status = kalender.abrufen(con, "schule")
    else:
        status = None
    h.antwort(200, {"schulkalender": status})


def api_schulkalender_entfernen(h, con, daten):
    _admin(h, con)
    kalender.abo_entfernen(con, "schule", None)
    h.antwort(200, {"schulkalender": None})


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
        p["warnungen"] = [w for w in termine.warnungen(con, p["id"]) if w["stufe"] != "hinweis"]
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
    p["warnungen"] = [w for w in termine.warnungen(con, pid) if w["stufe"] != "hinweis"]
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


def api_team_mitglieder(h, con, daten, token):
    projekte.mitglieder_anlegen(con, "Team", _team_projekt(con, token), daten.get("mitglieder"), "team")
    h.antwort(200, {"projekt": projekte.team_sicht(con, token)})


def api_team_mitglied(h, con, daten, token, mid):
    projekte.mitglied_aendern(con, "Team", _team_projekt(con, token), _ganzzahl(mid), daten, "team")
    h.antwort(200, {"projekt": projekte.team_sicht(con, token)})


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


LEHRKRAFT_AKTIONEN = ("meilenstein_neu", "meilenstein_aendern", "meilenstein_verwerfen")


def api_sheet_aendern(h, con, daten, pid):
    """Das Tracking-Sheet bearbeitet das Team; die Lehrkraft setzt nur Meilensteine."""
    k, pid = _projekt(h, con, pid)
    if daten.get("aktion") not in LEHRKRAFT_AKTIONEN:
        raise Fehler(403, "Das Tracking-Sheet bearbeitet nur das Team. Lehrkräfte setzen hier nur Meilensteine.")
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


# --- Cockpit, Kalender, Aktivitaeten ---

def api_cockpit(h, con, daten):
    h.antwort(200, cockpit.cockpit(con, h.konto(con), _abfrage(h, "klasse")))


def api_kalender(h, con, daten):
    k = h.konto(con)
    von, bis = termine._datum(_abfrage(h, "von"), "den Beginn"), termine._datum(_abfrage(h, "bis"), "das Ende")
    if bis < von or (bis - von).days > 200:
        raise Fehler(400, "Ungültiger Zeitraum.")
    h.antwort(200, {"eintraege": kalender.eintraege(con, k, von, bis, _abfrage(h, "klasse")),
                    "dienst": kalender.abo_status(con, "dienst", k["id"])})


def api_aktivitaeten(h, con, daten):
    k = h.konto(con)
    bereiche = [b for b in (_abfrage(h, "bereiche") or "").split(",") if b]
    h.antwort(200, cockpit.aktivitaeten(con, k, _abfrage(h, "zeitraum", "besuch"), bereiche or None, _abfrage(h, "klasse")))


def api_dienstkalender(h, con, daten):
    h.antwort(200, {"dienst": kalender.abo_status(con, "dienst", h.konto(con)["id"])})


def api_dienstkalender_setzen(h, con, daten):
    k = h.konto(con)
    h.antwort(200, {"dienst": kalender.abo_setzen(con, "dienst", k["id"], daten.get("url"))})


def api_dienstkalender_abrufen(h, con, daten):
    k = h.konto(con)
    h.antwort(200, {"dienst": kalender.abrufen(con, "dienst", k["id"])})


def api_dienstkalender_entfernen(h, con, daten):
    k = h.konto(con)
    kalender.abo_entfernen(con, "dienst", k["id"])
    h.antwort(200, {"dienst": None})


# --- Besprechung ---

def api_team_besprechung(h, con, daten, token):
    h.antwort(200, {"besprechung": besprechung.lesen(con, _team_projekt(con, token))})


def api_team_besprechung_aendern(h, con, daten, token):
    pid = _team_projekt(con, token)
    ergebnis = besprechung.aendern(con, pid, "team", "Team", daten)
    h.antwort(200, {"ergebnis": ergebnis, "besprechung": besprechung.lesen(con, pid)})


def api_besprechung(h, con, daten, pid):
    _k, pid = _projekt(h, con, pid)
    h.antwort(200, {"besprechung": besprechung.lesen(con, pid, lehrkraft=True)})


def api_besprechung_aendern(h, con, daten, pid):
    k, pid = _projekt(h, con, pid)
    if daten.get("aktion") == "abschliessen" and daten.get("bild"):   # Bild der Tafel fuer das PDF
        daten = dict(daten, bild_name=tafel.bild_speichern(_daten_dir(h), daten["bild"]))
    ergebnis = besprechung.aendern(con, pid, "lehrkraft", k["kuerzel"], daten)
    h.antwort(200, {"ergebnis": ergebnis, "besprechung": besprechung.lesen(con, pid, lehrkraft=True)})


# --- Nach der Besprechung: PDF (Tafel und Ergebnis) ---

def _pdf_antwort(h, con, pid, bid):
    inhalt = pdf.besprechung_pdf(con, _daten_dir(h), pid, bid)
    name = pdf.dateiname(con, pid, bid)
    einfach = "".join(c if c.isascii() and (c.isalnum() or c in " -_.") else "_" for c in name)
    h.antwort(200, inhalt, "application/pdf", extra=[("Content-Disposition", "attachment; filename=\"%s\"; filename*=UTF-8''%s"
                                                     % (einfach, urllib.parse.quote(name)))])


def _tafelbild(h, con, pid, bid, daten):
    if not daten.get("bild"):
        raise Fehler(400, "Kein Bild.")
    name = pdf.tafelbild_setzen(con, pid, bid, tafel.bild_speichern(_daten_dir(h), daten["bild"]))
    h.antwort(200, {"tafel_bild": name})


def api_besprechung_pdf(h, con, daten, pid, bid):
    _k, pid = _projekt(h, con, pid)
    _pdf_antwort(h, con, pid, _ganzzahl(bid))


def api_besprechung_tafelbild(h, con, daten, pid, bid):
    _k, pid = _projekt(h, con, pid)
    _tafelbild(h, con, pid, _ganzzahl(bid), daten)


def api_team_besprechung_pdf(h, con, daten, token, bid):
    _pdf_antwort(h, con, _team_projekt(con, token), _ganzzahl(bid))


def api_team_besprechung_tafelbild(h, con, daten, token, bid):
    _tafelbild(h, con, _team_projekt(con, token), _ganzzahl(bid), daten)


# --- Besprechungstafel ---

def _daten_dir(h):
    return os.path.dirname(h.server.db_pfad)


def _tafel_antwort(h, con, pid):
    tafel.melden(pid, "tafel")
    bekannt = _abfrage(h, "stand")
    z = besprechung._zeile(con, pid, besprechung.aktuelle_woche(con, pid))
    if bekannt and bekannt == tafel.stand(con, pid, z["id"] if z else None):
        return h.antwort(200, {"unveraendert": True, "anwesend": tafel.anwesend(pid)})
    h.antwort(200, {"tafel": tafel.lesen(con, pid)})


def api_tafel(h, con, daten, pid):
    _k, pid = _projekt(h, con, pid)
    _tafel_antwort(h, con, pid)


def api_tafel_aendern(h, con, daten, pid):
    k, pid = _projekt(h, con, pid)
    if daten.get("aktion") == "rahmen_ergebnis" and daten.get("bild"):   # Skizze des Rahmens als Bild am Eintrag
        daten = dict(daten, bild_name=tafel.bild_speichern(_daten_dir(h), daten["bild"]))
    ergebnis = tafel.aendern(con, pid, k["kuerzel"], daten)
    h.antwort(200, {"ergebnis": ergebnis, "tafel": tafel.lesen(con, pid)})


def api_tafel_alt(h, con, daten, pid, bid):
    _k, pid = _projekt(h, con, pid)
    h.antwort(200, {"tafel": tafel.eingefroren(con, pid, _ganzzahl(bid))})


def _bild(h, con, pid, name):
    pfad, typ = tafel.bild_pfad(con, _daten_dir(h), pid, name)
    if pfad is None:
        raise Fehler(404, "Dieses Foto gibt es nicht.")
    if typ == "application/pdf":   # PDF nie im Kontext der Seite oeffnen: herunterladen
        with open(pfad, "rb") as f:
            inhalt = f.read()
        return h.antwort(200, inhalt, typ, extra=[("Content-Disposition", 'attachment; filename="mindmap.pdf"')], cache=True)
    h.datei(pfad, typ, cache=True)


def api_bild(h, con, daten, pid, name):
    _k, pid = _projekt(h, con, pid)
    _bild(h, con, pid, name)


def api_team_tafel(h, con, daten, token):
    """Geraet des Teams meldet sich (Anwesenheit an der Tafel) und erfaehrt, ob die Tafel gerade offen ist."""
    pid = _team_projekt(con, token)
    geraet = _abfrage(h, "geraet")
    if geraet:
        tafel.melden(pid, "g-" + geraet)
    h.antwort(200, {"anwesend": tafel.anwesend(pid)})


def api_team_tafel_senden(h, con, daten, token):
    pid = _team_projekt(con, token)
    tafel.team_senden(con, pid, _daten_dir(h), daten)
    h.antwort(200, {"besprechung": besprechung.lesen(con, pid)})


def api_team_tafel_alt(h, con, daten, token, bid):
    h.antwort(200, {"tafel": tafel.eingefroren(con, _team_projekt(con, token), _ganzzahl(bid))})


def api_team_bild(h, con, daten, token, name):
    _bild(h, con, _team_projekt(con, token), name)


# --- Anfragen und Bestelllisten ---

def _team_anfragen(con, pid):
    return {"anfragen": anfragen.vorgaenge_team(con, pid), "bestellung": bestellung.team_sicht(con, pid)}


def api_team_anfragen(h, con, daten, token):
    h.antwort(200, _team_anfragen(con, _team_projekt(con, token)))


def api_team_hilfe(h, con, daten, token):
    h.antwort(200, {"hilfe": hilfe.team_stand(con, _team_projekt(con, token))})


def api_team_hilfe_aendern(h, con, daten, token):
    h.antwort(200, {"hilfe": hilfe.team_aendern(con, _team_projekt(con, token), daten)})


def api_notizen(h, con, daten):
    h.antwort(200, notizen.liste(con, h.konto(con)))


def api_notizen_zaehler(h, con, daten):
    h.antwort(200, notizen.zaehler(con, h.konto(con)))


def api_notiz_neu(h, con, daten):
    k = h.konto(con)
    notizen.anlegen(con, k, daten)
    h.antwort(200, notizen.liste(con, k))


def api_notiz_zeitstrahl(h, con, daten, nid):
    k = h.konto(con)
    notizen.aendern(con, k, _ganzzahl(nid), daten)
    h.antwort(200, notizen.liste(con, k) if daten.get("aktion") != "gelesen" else notizen.zaehler(con, k))


def api_hilfe(h, con, daten):
    h.antwort(200, {"reihe": hilfe.reihe(con, h.konto(con))})


def api_hilfe_aendern(h, con, daten, hid):
    h.antwort(200, {"reihe": hilfe.lehrkraft_aendern(con, h.konto(con), _ganzzahl(hid), daten)})


def api_team_zaehler(h, con, daten, token):
    h.antwort(200, anfragen.team_zaehler(con, _team_projekt(con, token)))


def api_team_anfragen_aendern(h, con, daten, token):
    pid = _team_projekt(con, token)
    if daten.get("aktion") == "neu":
        bild = tafel.bild_speichern(_daten_dir(h), daten["bild"]) if daten.get("bild") else None
        anfragen.anlegen(con, pid, daten, bild)
    else:
        anfragen.team_aendern(con, pid, daten)
    h.antwort(200, _team_anfragen(con, pid))


def api_team_bestellung_lesen(h, con, daten, token):
    pid = _team_projekt(con, token)
    sicht = bestellung.team_sicht(con, pid)   # erst lesen (mit Neu-Marken), dann als gesehen merken
    bestellung.team_gesehen(con, pid)
    h.antwort(200, {"bestellung": sicht})


def api_team_bestellung(h, con, daten, token):
    pid = _team_projekt(con, token)
    ergebnis = bestellung.team_aendern(con, pid, daten)
    h.antwort(200, dict(_team_anfragen(con, pid), ergebnis=ergebnis))


def api_anfragen(h, con, daten):
    k = h.konto(con)
    h.antwort(200, {"bestellung": bestellung.uebersicht(con, k), "zaehler": anfragen.zaehler(con, k)})


def api_vorgaenge(h, con, daten):
    k = h.konto(con)
    projekt = _abfrage(h, "projekt")
    projekt = _ganzzahl(projekt) if projekt else None
    staende = _abfrage(h, "staende")
    if staende is not None:   # Eingang ab 0.10.2: Knoepfe je Stand, "nur meine", Zahlen und Betreuer
        e = anfragen.eingang(con, k, projekt, _abfrage(h, "art"), [s for s in staende.split(",") if s], _abfrage(h, "meine") == "1")
        h.antwort(200, dict(e, zaehler=anfragen.zaehler(con, k)))
        return
    h.antwort(200, {"vorgaenge": anfragen.vorgaenge_lehrkraft(con, k, _abfrage(h, "filter", "aktiv"), projekt, _abfrage(h, "art")),
                    "zaehler": anfragen.zaehler(con, k)})


def api_vorgaenge_zaehler(h, con, daten):
    h.antwort(200, anfragen.zaehler(con, h.konto(con)))


def _vorgang_projekt(con, aid):
    z = con.execute("SELECT projekt_id FROM anfrage WHERE id = ?", (_ganzzahl(aid),)).fetchone()
    if z is None:
        raise Fehler(404, "Diesen Vorgang gibt es nicht.")
    return str(z[0])


def api_vorgang_direkt(h, con, daten, aid):
    api_vorgang(h, con, daten, _vorgang_projekt(con, aid), aid)


def api_vorgang_direkt_aendern(h, con, daten, aid):
    api_vorgang_aendern(h, con, daten, _vorgang_projekt(con, aid), aid)


def api_vorgang(h, con, daten, pid, aid):
    k, pid = _projekt(h, con, pid)
    h.antwort(200, {"vorgang": anfragen.vorgang(con, pid, _ganzzahl(aid), k)})


def api_vorgang_aendern(h, con, daten, pid, aid):
    k, pid = _projekt(h, con, pid)
    aid = _ganzzahl(aid)
    if daten.get("aktion") == "nachricht":
        bild = tafel.bild_speichern(_daten_dir(h), daten["bild"]) if daten.get("bild") else None
        anfragen.nachricht(con, pid, aid, "lehrkraft", dict(daten, bild=bild), k)
    else:
        anfragen.bearbeiten(con, pid, k, dict(daten, anfrage_id=aid))
    h.antwort(200, {"vorgang": anfragen.vorgang(con, pid, aid, k)})


def api_anfrage_bearbeiten(h, con, daten, pid):
    k, pid = _projekt(h, con, pid)
    anfragen.bearbeiten(con, pid, k, daten)
    h.antwort(200, {"vorgang": anfragen.vorgang(con, pid, _ganzzahl(daten.get("anfrage_id")), k)})


def api_team_vorgang(h, con, daten, token, aid):
    h.antwort(200, {"vorgang": anfragen.vorgang(con, _team_projekt(con, token), _ganzzahl(aid))})


def api_team_vorgang_aendern(h, con, daten, token, aid):
    pid = _team_projekt(con, token)
    aid = _ganzzahl(aid)
    if daten.get("aktion") == "nachricht":
        bild = tafel.bild_speichern(_daten_dir(h), daten["bild"]) if daten.get("bild") else None
        anfragen.nachricht(con, pid, aid, "team", dict(daten, bild=bild))
    else:
        anfragen.team_aendern(con, pid, dict(daten, anfrage_id=aid))
    h.antwort(200, {"vorgang": anfragen.vorgang(con, pid, aid)})


def api_bestellfenster(h, con, daten):
    k = h.konto(con)
    bestellung.fenster_anlegen(con, k, daten)
    h.antwort(200, {"bestellung": bestellung.uebersicht(con, k)})


def api_bestellfenster_aendern(h, con, daten, fid):
    k = h.konto(con)
    bestellung.fenster_aendern(con, k, _ganzzahl(fid), daten)
    h.antwort(200, {"bestellung": bestellung.uebersicht(con, k)})


def api_bestellliste(h, con, daten, lid):
    h.antwort(200, {"liste": bestellung.liste_lesen(con, h.konto(con), _ganzzahl(lid))})


def api_projekt_bestellung(h, con, daten, pid):
    _k, pid = _projekt(h, con, pid)
    h.antwort(200, {"bestellung": bestellung.projekt_listen(con, pid)})


def api_bestellung_pruefen(h, con, daten, pid):
    k, pid = _projekt(h, con, pid)
    bestellung.pruefen(con, pid, k["kuerzel"], daten)
    z = con.execute("SELECT liste_id FROM position WHERE id = ?", (_ganzzahl(daten.get("position_id")),)).fetchone()
    h.antwort(200, {"liste": bestellung.liste_lesen(con, k, z[0])})


def api_sammelbestellung(h, con, daten, fid):
    h.antwort(200, {"sammelbestellung": bestellung.sammelbestellung(con, h.konto(con), _ganzzahl(fid))})


def api_sammelbestellung_csv(h, con, daten, fid):
    d = bestellung.sammelbestellung(con, h.konto(con), _ganzzahl(fid))
    name = "sammelbestellung-%s.csv" % d["fenster"]["bis"][:10]
    h.antwort(200, bestellung.sammelbestellung_csv(d), "text/csv; charset=utf-8",
              extra=[("Content-Disposition", 'attachment; filename="%s"' % name)])


# --- Extras: Mindmap, Lehrernotizen, (Fotos nur noch lesen: Reiter "Fotos" ist mit J2 entfallen), Vorlagen, Export, Archiv, Sicherung ---

def _extras(con, pid, lehrkraft):
    d = {"fotos": extras.fotos(con, pid), "mindmap": extras.mindmap(con, pid)}
    if lehrkraft:
        d["notizen"] = extras.notizen(con, pid)
    return d


def api_extras(h, con, daten, pid):
    _k, pid = _projekt(h, con, pid)
    h.antwort(200, _extras(con, pid, True))


def api_mindmap(h, con, daten, pid):
    k, pid = _projekt(h, con, pid)
    extras.mindmap_setzen(con, pid, _daten_dir(h), k["kuerzel"], daten)
    h.antwort(200, _extras(con, pid, True))


def api_notiz(h, con, daten, pid):
    k, pid = _projekt(h, con, pid)
    extras.notiz_neu(con, pid, k["kuerzel"], daten.get("text"))
    h.antwort(200, _extras(con, pid, True))


def api_notiz_aendern(h, con, daten, pid, nid):
    k, pid = _projekt(h, con, pid)
    extras.notiz_aendern(con, pid, k["kuerzel"], _ganzzahl(nid), daten)
    h.antwort(200, _extras(con, pid, True))


def api_phasen(h, con, daten, pid):
    _k, pid = _projekt(h, con, pid)
    h.antwort(200, projekte.phasen_sicht(con, pid))


def api_phasen_aendern(h, con, daten, pid):
    k, pid = _projekt(h, con, pid)
    h.antwort(200, projekte.phasen_aendern(con, k["kuerzel"], pid, daten))


def api_vorlage_speichern(h, con, daten, pid):
    _k, pid = _projekt(h, con, pid)
    h.antwort(200, {"schluessel": extras.vorlage_speichern(con, pid, daten.get("name"), bool(daten.get("mit_team")))})


def api_vorlage_entfernen(h, con, daten, schluessel):
    _admin(h, con)
    extras.vorlage_entfernen(con, schluessel)
    h.antwort(200, {"ok": True})


def api_loeschen(h, con, daten, pid):
    k, pid = _projekt(h, con, pid)
    extras.loeschen(con, pid, _daten_dir(h), k["kuerzel"], daten.get("bestaetigung"))
    h.antwort(200, {"ok": True})


def api_archivieren_schuljahr(h, con, daten):
    k = h.konto(con)
    h.antwort(200, {"anzahl": projekte.archivieren_schuljahr(con, k, str(daten.get("schuljahr") or ""))})


def api_export_xlsx(h, con, daten, pid):
    _k, pid = _projekt(h, con, pid)
    titel = con.execute("SELECT titel FROM projekt WHERE id = ?", (pid,)).fetchone()[0]
    h.antwort(200, export.sheet_xlsx(con, pid), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
              extra=[("Content-Disposition", 'attachment; filename="%s"' % export.dateiname(titel, "xlsx"))])


def api_bericht(h, con, daten, pid):
    _k, pid = _projekt(h, con, pid)
    h.antwort(200, {"bericht": export.bericht(con, pid, _abfrage(h, "notizen") == "1")})


def api_update(h, con, daten):
    _admin(h, con)
    h.antwort(200, updates.stand(_daten_dir(h)))


def api_update_anfordern(h, con, daten):
    a = _admin(h, con)
    updates.anfordern(_daten_dir(h), daten.get("aktion"))
    print("Update: %s angefordert von %s" % (daten.get("aktion"), a["kuerzel"]), flush=True)
    h.antwort(200, updates.stand(_daten_dir(h)))


def api_vpn(h, con, daten):
    _admin(h, con)
    h.antwort(200, vpn.web_stand(_daten_dir(h)))


def api_vpn_anfordern(h, con, daten):
    # Einrichten und Ausschalten aendern, wer von aussen an den Container kommt: dafuer das eigene Passwort
    a = _admin(h, con)
    if daten.get("aktion") in ("einrichten", "aus"):
        pw = con.execute("SELECT pw FROM lehrkraft WHERE id = ?", (a["id"],)).fetchone()[0]
        if not konten.passwort_stimmt(pw, daten.get("passwort") or ""):
            raise vpn.VpnFehler("Das Passwort stimmt nicht.")
    angaben = vpn.anfordern(_daten_dir(h), daten)
    print("VPN: %s angefordert von %s%s" % (angaben["aktion"], a["kuerzel"], " (Client-Datei)" if daten.get("conf") else ""),
          flush=True)
    h.antwort(200, dict(vpn.web_stand(_daten_dir(h)), hinweise=angaben.get("hinweise", [])))


def api_update_sicherung(h, con, daten, name):
    _admin(h, con)
    with open(updates.sicherung_pfad(_daten_dir(h), name), "rb") as f:
        inhalt = f.read()
    h.antwort(200, inhalt, "application/zip", extra=[("Content-Disposition", 'attachment; filename="trackingdrs-%s"' % name)])


def api_sicherung(h, con, daten):
    a = _admin(h, con)
    pfad = extras.sicherung(con, _daten_dir(h))
    try:
        with open(pfad, "rb") as f:
            inhalt = f.read()
    finally:
        os.remove(pfad)
    print("Sicherung heruntergeladen von %s (%d KB)" % (a["kuerzel"], len(inhalt) // 1024), flush=True)
    h.antwort(200, inhalt, "application/zip",
              extra=[("Content-Disposition", 'attachment; filename="trackingdrs-sicherung-%s.zip"' % db.jetzt()[:10])])


def api_team_extras(h, con, daten, token):
    h.antwort(200, _extras(con, _team_projekt(con, token), False))



# --- Termine ---

def _termin_aendern(h, con, pid, wer_art, wer, daten):
    if daten.get("stornieren"):
        termine.stornieren(con, pid, wer_art, wer, daten.get("woche"))
    else:
        termine.buchen(con, pid, wer_art, wer, daten.get("regel_id"), daten.get("datum"), daten.get("uhrzeit"))
    if wer_art == "team":
        return h.antwort(200, _team_termine(con, pid))
    h.antwort(200, {"termine": termine.termin_sicht(con, pid, lehrkraft=True, wochen=6), "warnungen": termine.warnungen(con, pid)})


def _team_termine(con, pid):
    """Was die Team-Uebersicht braucht: Termine nur der aktuellen Woche, Warnungen, entfallende Projekttage."""
    return {"termine": termine.termin_sicht(con, pid, wochen=6, aktuell=True),
            "warnungen": [w for w in termine.warnungen(con, pid) if w["stufe"] != "intern"],
            "entfallen": termine.entfallende_tage(con, pid)}


def api_team_termine(h, con, daten, token):
    h.antwort(200, _team_termine(con, _team_projekt(con, token)))


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
    ("POST", r"/api/einstellungen/schulkalender", api_schulkalender),
    ("POST", r"/api/einstellungen/schulkalender/entfernen", api_schulkalender_entfernen),
    ("GET", r"/api/cockpit", api_cockpit),
    ("GET", r"/api/kalender", api_kalender),
    ("GET", r"/api/aktivitaeten", api_aktivitaeten),
    ("GET", r"/api/dienstkalender", api_dienstkalender),
    ("POST", r"/api/dienstkalender", api_dienstkalender_setzen),
    ("POST", r"/api/dienstkalender/abrufen", api_dienstkalender_abrufen),
    ("POST", r"/api/dienstkalender/entfernen", api_dienstkalender_entfernen),
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
    ("POST", r"/api/projekte/(\d+)/anfragen", api_anfrage_bearbeiten),
    ("GET", r"/api/projekte/(\d+)/extras", api_extras),
    ("POST", r"/api/projekte/(\d+)/mindmap", api_mindmap),
    ("POST", r"/api/projekte/(\d+)/notizen", api_notiz),
    ("POST", r"/api/projekte/(\d+)/notizen/(\d+)", api_notiz_aendern),
    ("POST", r"/api/projekte/(\d+)/vorlage", api_vorlage_speichern),
    ("POST", r"/api/projekte/(\d+)/loeschen", api_loeschen),
    ("GET", r"/api/projekte/(\d+)/export\.xlsx", api_export_xlsx),
    ("GET", r"/api/projekte/(\d+)/bericht", api_bericht),
    ("POST", r"/api/projekte/archivieren-schuljahr", api_archivieren_schuljahr),
    ("POST", r"/api/vorlagen/(eigen-\d+)/entfernen", api_vorlage_entfernen),
    ("GET", r"/api/sicherung\.zip", api_sicherung),
    ("GET", r"/api/update", api_update),
    ("POST", r"/api/update", api_update_anfordern),
    ("GET", r"/api/update/sicherung/(vor-update-[0-9_-]+\.zip)", api_update_sicherung),
    ("GET", r"/api/vpn", api_vpn),
    ("POST", r"/api/vpn", api_vpn_anfordern),
    ("GET", r"/api/projekte/(\d+)/bestellung", api_projekt_bestellung),
    ("GET", r"/api/projekte/(\d+)/phasen", api_phasen),
    ("POST", r"/api/projekte/(\d+)/phasen", api_phasen_aendern),
    ("POST", r"/api/projekte/(\d+)/bestellung", api_bestellung_pruefen),
    ("GET", r"/api/anfragen", api_anfragen),
    ("GET", r"/api/vorgaenge", api_vorgaenge),
    ("GET", r"/api/vorgaenge/zaehler", api_vorgaenge_zaehler),
    ("GET", r"/api/hilfe", api_hilfe),
    ("GET", r"/api/notizen", api_notizen),
    ("GET", r"/api/notizen/zaehler", api_notizen_zaehler),
    ("POST", r"/api/notizen", api_notiz_neu),
    ("POST", r"/api/notizen/(\d+)", api_notiz_zeitstrahl),
    ("POST", r"/api/hilfe/(\d+)", api_hilfe_aendern),
    ("GET", r"/api/vorgaenge/(\d+)", api_vorgang_direkt),
    ("POST", r"/api/vorgaenge/(\d+)", api_vorgang_direkt_aendern),
    ("GET", r"/api/projekte/(\d+)/vorgaenge/(\d+)", api_vorgang),
    ("POST", r"/api/projekte/(\d+)/vorgaenge/(\d+)", api_vorgang_aendern),
    ("POST", r"/api/bestellfenster", api_bestellfenster),
    ("POST", r"/api/bestellfenster/(\d+)", api_bestellfenster_aendern),
    ("GET", r"/api/bestellfenster/(\d+)/sammelbestellung", api_sammelbestellung),
    ("GET", r"/api/bestellfenster/(\d+)/sammelbestellung\.csv", api_sammelbestellung_csv),
    ("GET", r"/api/bestellliste/(\d+)", api_bestellliste),
    ("GET", r"/api/projekte/(\d+)/besprechung", api_besprechung),
    ("POST", r"/api/projekte/(\d+)/besprechung", api_besprechung_aendern),
    ("GET", r"/api/projekte/(\d+)/besprechung/(\d+)/pdf", api_besprechung_pdf),
    ("POST", r"/api/projekte/(\d+)/besprechung/(\d+)/tafelbild", api_besprechung_tafelbild),
    ("GET", r"/api/projekte/(\d+)/tafel", api_tafel),
    ("POST", r"/api/projekte/(\d+)/tafel", api_tafel_aendern),
    ("GET", r"/api/projekte/(\d+)/tafel/(\d+)", api_tafel_alt),
    ("GET", r"/api/projekte/(\d+)/bild/([0-9a-f]{24})", api_bild),
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
    ("GET", r"/api/t/([A-Za-z0-9_-]{20,64})/anfragen", api_team_anfragen),
    ("GET", r"/api/t/([A-Za-z0-9_-]{20,64})/zaehler", api_team_zaehler),
    ("GET", r"/api/t/([A-Za-z0-9_-]{20,64})/hilfe", api_team_hilfe),
    ("POST", r"/api/t/([A-Za-z0-9_-]{20,64})/hilfe", api_team_hilfe_aendern),
    ("POST", r"/api/t/([A-Za-z0-9_-]{20,64})/mitglieder", api_team_mitglieder),
    ("POST", r"/api/t/([A-Za-z0-9_-]{20,64})/mitglieder/(\d+)", api_team_mitglied),
    ("GET", r"/api/t/([A-Za-z0-9_-]{20,64})/extras", api_team_extras),
    ("POST", r"/api/t/([A-Za-z0-9_-]{20,64})/anfragen", api_team_anfragen_aendern),
    ("GET", r"/api/t/([A-Za-z0-9_-]{20,64})/vorgaenge/(\d+)", api_team_vorgang),
    ("POST", r"/api/t/([A-Za-z0-9_-]{20,64})/vorgaenge/(\d+)", api_team_vorgang_aendern),
    ("GET", r"/api/t/([A-Za-z0-9_-]{20,64})/bestellung", api_team_bestellung_lesen),
    ("POST", r"/api/t/([A-Za-z0-9_-]{20,64})/bestellung", api_team_bestellung),
    ("GET", r"/api/t/([A-Za-z0-9_-]{20,64})/besprechung", api_team_besprechung),
    ("POST", r"/api/t/([A-Za-z0-9_-]{20,64})/besprechung", api_team_besprechung_aendern),
    ("GET", r"/api/t/([A-Za-z0-9_-]{20,64})/besprechung/(\d+)/pdf", api_team_besprechung_pdf),
    ("POST", r"/api/t/([A-Za-z0-9_-]{20,64})/besprechung/(\d+)/tafelbild", api_team_besprechung_tafelbild),
    ("GET", r"/api/t/([A-Za-z0-9_-]{20,64})/tafel", api_team_tafel),
    ("POST", r"/api/t/([A-Za-z0-9_-]{20,64})/tafel", api_team_tafel_senden),
    ("GET", r"/api/t/([A-Za-z0-9_-]{20,64})/tafel/(\d+)", api_team_tafel_alt),
    ("GET", r"/api/t/([A-Za-z0-9_-]{20,64})/bild/([0-9a-f]{24})", api_team_bild),
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
    """Jede Minute: faellige Versionen zum Buchungsschluss anlegen und Kalender-Abos holen (alle 30 Minuten)."""
    while True:
        con = None
        try:
            con = db.verbinden(db_pfad)
            neu = termine.faellige_versionen(con)
            if neu:
                print("Versionen zum Buchungsschluss: %d neu" % neu, flush=True)
            kalender.faellige_abrufen(con)
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
