"""Extras: Fotos vom Aufbau (Team), Mindmap als Bild oder PDF (Lehrkraft), private Lehrernotizen, eigene
Projektvorlagen, endgueltiges Loeschen archivierter Projekte und die Komplett-Sicherung als ZIP.

Dateien liegen im Ordner bilder/ des Datenordners (Name: 24 Hexzeichen + Endung). Fotos nehmen nur JPEG/PNG an (der
Browser verkleinert vorher), die Mindmap auch PDF. Lehrernotizen sieht das Team nie. Endgueltig loeschen geht nur bei
archivierten Projekten und nimmt alles mit, auch das Ereignisprotokoll und die Dateien.
"""
import base64
import binascii
import json
import os
import secrets
import sqlite3
import tempfile
import zipfile

from . import db
from .projekte import ProjektFehler

MAX_FOTO = 1400 * 1024
MAX_MINDMAP = 8 * 1024 * 1024
TYPEN = {b"\xff\xd8\xff": ("image/jpeg", ".jpg"), b"\x89PNG\r\n\x1a\n": ("image/png", ".png"), b"%PDF-": ("application/pdf", ".pdf")}


def speichern(daten_dir, inhalt_b64, pdf=False, max_bytes=MAX_FOTO):
    """Datei aus Base64 pruefen (Inhalt, nicht Endung) und ablegen. Rueckgabe: (name, typ)."""
    try:
        roh = base64.b64decode(inhalt_b64 or "", validate=True)
    except (binascii.Error, ValueError):
        raise ProjektFehler("Die Datei konnte nicht gelesen werden.")
    if not roh:
        raise ProjektFehler("Die Datei ist leer.")
    if len(roh) > max_bytes:
        raise ProjektFehler("Die Datei ist zu groß (höchstens %d MB)." % max(1, max_bytes // (1024 * 1024)))
    for anfang, (typ, endung) in TYPEN.items():
        if roh.startswith(anfang) and (pdf or typ != "application/pdf"):
            break
    else:
        raise ProjektFehler("Bitte ein Bild (JPEG oder PNG)%s schicken." % (" oder ein PDF" if pdf else ""))
    ordner = os.path.join(daten_dir, "bilder")
    os.makedirs(ordner, exist_ok=True)
    name = secrets.token_hex(12)
    with open(os.path.join(ordner, name + endung), "wb") as f:
        f.write(roh)
    return name, typ


def _text(wert, laenge, feld="einen Text", pflicht=False):
    wert = (wert or "").strip()
    if pflicht and not wert:
        raise ProjektFehler("Bitte %s angeben." % feld)
    if len(wert) > laenge:
        raise ProjektFehler("Der Text ist zu lang (höchstens %d Zeichen)." % laenge)
    return wert


def _offen(con, pid):
    p = con.execute("SELECT * FROM projekt WHERE id = ?", (pid,)).fetchone()
    if p is None:
        raise ProjektFehler("Dieses Projekt gibt es nicht.")
    if p["archiviert"]:
        raise ProjektFehler("Das Projekt ist archiviert.")
    return p


def _datei(z, aufgaben=None):
    return {"id": z["id"], "art": z["art"], "name": z["name"], "typ": z["typ"], "titel": z["titel"], "aufgabe_id": z["aufgabe_id"],
            "aufgabe": (aufgaben or {}).get(z["aufgabe_id"]), "erstellt": z["erstellt"], "wer_art": z["wer_art"], "wer": z["wer"]}


# --- Fotos ---

def fotos(con, pid):
    aufgaben = {a["id"]: a["titel"] for a in con.execute("SELECT id, titel FROM aufgabe WHERE projekt_id = ?", (pid,))}
    return [_datei(z, aufgaben) for z in con.execute(
        "SELECT * FROM datei WHERE projekt_id = ? AND art = 'foto' AND verworfen = 0 ORDER BY erstellt DESC, id DESC", (pid,))]


def foto_neu(con, pid, daten_dir, wer_art, wer, d):
    _offen(con, pid)
    titel = _text(d.get("titel"), 200)
    aufgabe_id = d.get("aufgabe_id") or None
    if aufgabe_id is not None and not con.execute("SELECT 1 FROM aufgabe WHERE id = ? AND projekt_id = ?", (aufgabe_id, pid)).fetchone():
        raise ProjektFehler("Diese Tätigkeit gibt es nicht.")
    name, typ = speichern(daten_dir, d.get("bild"))
    with db.transaktion(con):
        fid = con.execute("INSERT INTO datei (projekt_id, art, name, typ, titel, aufgabe_id, erstellt, wer_art, wer) "
                          "VALUES (?, 'foto', ?, ?, ?, ?, ?, ?, ?)", (pid, name, typ, titel, aufgabe_id, db.jetzt(), wer_art, wer)).lastrowid
        db.ereignis(con, pid, wer_art, wer, "foto_neu", datei_id=fid, titel=titel, aufgabe_id=aufgabe_id)
    return fid


def foto_verwerfen(con, pid, wer_art, wer, fid):
    z = con.execute("SELECT * FROM datei WHERE id = ? AND projekt_id = ? AND art = 'foto' AND verworfen = 0", (fid, pid)).fetchone()
    if z is None:
        raise ProjektFehler("Dieses Foto gibt es nicht.")
    if wer_art == "team" and z["wer_art"] != "team":
        raise ProjektFehler("Dieses Foto kann nur die Lehrkraft entfernen.")
    with db.transaktion(con):
        con.execute("UPDATE datei SET verworfen = 1 WHERE id = ?", (fid,))
        db.ereignis(con, pid, wer_art, wer, "foto_verworfen", datei_id=fid, titel=z["titel"])


# --- Mindmap ---

def mindmap(con, pid):
    z = con.execute("SELECT * FROM datei WHERE projekt_id = ? AND art = 'mindmap' AND verworfen = 0 ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
    return _datei(z) if z else None


def mindmap_setzen(con, pid, daten_dir, wer, d):
    """Neue Mindmap (Bild oder PDF); die bisherige bleibt als verworfen erhalten."""
    _offen(con, pid)
    name, typ = speichern(daten_dir, d.get("inhalt"), pdf=True, max_bytes=MAX_MINDMAP)
    titel = _text(d.get("titel"), 200) or "Mindmap"
    with db.transaktion(con):
        con.execute("UPDATE datei SET verworfen = 1 WHERE projekt_id = ? AND art = 'mindmap'", (pid,))
        con.execute("INSERT INTO datei (projekt_id, art, name, typ, titel, erstellt, wer_art, wer) VALUES (?, 'mindmap', ?, ?, ?, ?, 'lehrkraft', ?)",
                    (pid, name, typ, titel, db.jetzt(), wer))
        db.ereignis(con, pid, "lehrkraft", wer, "mindmap", titel=titel)


# --- Lehrernotizen (nur Lehrkraefte; kein Ereignis, der Text steht nirgends sonst) ---

# Seit Stufe J5 stehen sie im gemeinsamen Zeitstrahl (app/notizen.py); hier nur noch die Sicht je Projekt (Bericht)
# und die einfachen Aufrufe von frueher.

def notizen(con, pid):
    from . import notizen as zeitstrahl
    return zeitstrahl.fuer_projekt(con, pid)


def notiz_neu(con, pid, wer, text):
    from . import notizen as zeitstrahl
    text = _text(text, 10000, "einen Text", pflicht=True)
    k = con.execute("SELECT id FROM lehrkraft WHERE kuerzel = ?", (wer,)).fetchone()
    with db.transaktion(con):
        return con.execute("INSERT INTO lehrernotiz (ueberschrift, text, projekt_id, lehrkraft_id, wer, erstellt) VALUES (?, ?, ?, ?, ?, ?)",
                           (zeitstrahl.ueberschrift_aus(text), text, pid, k[0] if k else None, wer, db.jetzt())).lastrowid


def notiz_aendern(con, pid, wer, nid, d):
    n = con.execute("SELECT * FROM lehrernotiz WHERE id = ? AND projekt_id = ? AND verworfen = 0", (nid, pid)).fetchone()
    if n is None:
        raise ProjektFehler("Diese Notiz gibt es nicht.")
    with db.transaktion(con):
        if d.get("verworfen"):
            con.execute("UPDATE lehrernotiz SET verworfen = 1 WHERE id = ?", (nid,))
        else:
            con.execute("UPDATE lehrernotiz SET text = ?, geaendert = ? WHERE id = ?",
                        (_text(d.get("text"), 10000, "einen Text", pflicht=True), db.jetzt(), nid))


# --- Vorlagen ---

def vorlage_speichern(con, pid, name, mit_team=False):
    """Phasen und Tätigkeiten eines Projekts als eigene Vorlage (nur Vorgaben, auf Wunsch auch die Tätigkeiten des Teams)."""
    name = _text(name, 80, "einen Namen", pflicht=True)
    phasen = []
    for ph in con.execute("SELECT * FROM phase WHERE projekt_id = ? ORDER BY pos", (pid,)).fetchall():
        sql = "SELECT titel FROM aufgabe WHERE phase_id = ? AND verworfen = 0" + ("" if mit_team else " AND aus_vorlage = 1") + " ORDER BY pos, id"
        phasen.append({"name": ph["name"], "aufgaben": [a[0] for a in con.execute(sql, (ph["id"],))]})
    if not phasen:
        raise ProjektFehler("Das Projekt hat keine Phasen.")
    with db.transaktion(con):
        n = con.execute("SELECT COUNT(*) FROM vorlage WHERE schluessel LIKE 'eigen-%'").fetchone()[0] + 1
        while con.execute("SELECT 1 FROM vorlage WHERE schluessel = ?", ("eigen-%d" % n,)).fetchone():
            n += 1
        schluessel = "eigen-%d" % n
        con.execute("INSERT INTO vorlage (schluessel, name, daten) VALUES (?, ?, ?)",
                    (schluessel, name, json.dumps({"name": name, "phasen": phasen}, ensure_ascii=False)))
    return schluessel


def vorlage_entfernen(con, schluessel):
    if not str(schluessel).startswith("eigen-"):
        raise ProjektFehler("Mitgelieferte Vorlagen lassen sich nicht entfernen.")
    with db.transaktion(con):
        con.execute("DELETE FROM vorlage WHERE schluessel = ?", (schluessel,))


# --- Endgueltig loeschen ---

def loeschen(con, pid, daten_dir, wer, bestaetigung):
    """Archiviertes Projekt mit allem loeschen (Datenschutz). Zur Sicherheit muss der Titel eingetippt werden."""
    p = con.execute("SELECT * FROM projekt WHERE id = ?", (pid,)).fetchone()
    if p is None:
        raise ProjektFehler("Dieses Projekt gibt es nicht.")
    if not p["archiviert"]:
        raise ProjektFehler("Nur archivierte Projekte lassen sich endgültig löschen.")
    if (bestaetigung or "").strip() != p["titel"]:
        raise ProjektFehler("Zur Bestätigung bitte den Projekttitel genau so eintippen: %s" % p["titel"])
    namen = [z[0] for z in con.execute(
        "SELECT bild FROM eintrag WHERE projekt_id = ? AND bild IS NOT NULL UNION SELECT bild FROM anfrage WHERE projekt_id = ? "
        "AND bild IS NOT NULL UNION SELECT name FROM datei WHERE projekt_id = ? UNION SELECT n.bild FROM nachricht n "
        "JOIN anfrage a ON a.id = n.anfrage_id WHERE a.projekt_id = ? AND n.bild IS NOT NULL", (pid, pid, pid, pid))]
    with db.transaktion(con):
        con.execute("UPDATE bestellliste SET fenster_id = NULL WHERE projekt_id = ?", (pid,))
        con.execute("DELETE FROM bestellfenster WHERE projekt_id = ?", (pid,))   # Sonderfenster haengen nicht per Kaskade
        con.execute("UPDATE eintrag SET anfrage_id = NULL WHERE projekt_id = ?", (pid,))
        con.execute("DELETE FROM projekt WHERE id = ?", (pid,))
    for name in namen:
        for endung in (".jpg", ".png", ".pdf"):
            pfad = os.path.join(daten_dir, "bilder", name + endung)
            if os.path.exists(pfad):
                os.remove(pfad)
    print("Projekt %d (%s, %s) endgueltig geloescht von %s" % (pid, p["titel"], p["schuljahr"], wer), flush=True)


# --- Sicherung ---

def sicherung(con, daten_dir):
    """ZIP mit Datenbank (konsistente Kopie per SQLite-Backup), Fotos/Dateien und Logo. Ohne TLS-Schluessel.
    Rueckgabe: Pfad einer temporaeren Datei (der Aufrufer loescht sie)."""
    fd, zip_pfad = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    db_kopie = zip_pfad + ".sqlite"
    ziel = sqlite3.connect(db_kopie)
    try:
        con.backup(ziel)
    finally:
        ziel.close()
    try:
        with zipfile.ZipFile(zip_pfad, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(db_kopie, "trackingdrs.sqlite")
            ordner = os.path.join(daten_dir, "bilder")
            if os.path.isdir(ordner):
                for name in sorted(os.listdir(ordner)):
                    z.write(os.path.join(ordner, name), "bilder/" + name, compress_type=zipfile.ZIP_STORED)
            for name in os.listdir(daten_dir):
                if name.startswith("logo."):
                    z.write(os.path.join(daten_dir, name), name)
            z.writestr("LIESMICH.txt", (
                "TrackingDRS-Sicherung vom %s\n\nWiederherstellen (im Container als root):\n"
                "  systemctl stop trackingdrs\n"
                "  ZIP nach /var/lib/trackingdrs entpacken (trackingdrs.sqlite, bilder/, logo.*)\n"
                "  chown -R trackingdrs:trackingdrs /var/lib/trackingdrs\n"
                "  systemctl start trackingdrs\n" % db.jetzt()).encode("utf-8"))
    finally:
        os.remove(db_kopie)
    return zip_pfad
