"""Einstellungen der Schule: Logo (z.B. DRS-Logo) fuer den Kopf aller Seiten.

Das Logo liegt im Datenordner, nicht im Repo (Markenrechte; das Repo soll oeffentlich werden koennen).
"""
import os
import re

from . import db

MAX_LOGO = 1024 * 1024
LOGO_TYPEN = {"png": "image/png", "jpg": "image/jpeg", "svg": "image/svg+xml"}
SVG_VERBOTEN = re.compile(rb"<script|javascript:|\son[a-z]+\s*=|<foreignObject|<iframe|<embed|<object", re.I)


class EinstellungFehler(Exception):
    """Fehler mit einer Meldung, die direkt in der Oberflaeche erscheinen darf."""


def _art(inhalt):
    if inhalt.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if inhalt.startswith(b"\xff\xd8\xff"):
        return "jpg"
    kopf = inhalt[:2048].lstrip().lower()
    if (kopf.startswith(b"<?xml") or kopf.startswith(b"<svg") or kopf.startswith(b"<!--")) and b"<svg" in inhalt[:20000].lower():
        if SVG_VERBOTEN.search(inhalt):
            raise EinstellungFehler("Dieses SVG enthält Skripte oder eingebettete Inhalte und wird nicht angenommen.")
        return "svg"
    raise EinstellungFehler("Bitte ein Logo als PNG, JPG oder SVG hochladen.")


def logo_pfad(con, daten_dir):
    """Pfad und Inhaltstyp des Logos oder (None, None)."""
    art = db.einstellung(con, "logo")
    if art not in LOGO_TYPEN:
        return None, None
    pfad = os.path.join(daten_dir, "logo." + art)
    return (pfad, LOGO_TYPEN[art]) if os.path.exists(pfad) else (None, None)


def logo_speichern(con, daten_dir, inhalt):
    if not inhalt:
        raise EinstellungFehler("Die Datei ist leer.")
    if len(inhalt) > MAX_LOGO:
        raise EinstellungFehler("Das Logo darf höchstens 1 MB groß sein.")
    art = _art(inhalt)
    neu = os.path.join(daten_dir, "logo." + art + ".neu")
    with open(neu, "wb") as f:
        f.write(inhalt)
    os.replace(neu, os.path.join(daten_dir, "logo." + art))
    for andere in LOGO_TYPEN:
        if andere != art:
            try:
                os.remove(os.path.join(daten_dir, "logo." + andere))
            except FileNotFoundError:
                pass
    db.einstellung_setzen(con, "logo", art)
    return art


def logo_entfernen(con, daten_dir):
    for art in LOGO_TYPEN:
        try:
            os.remove(os.path.join(daten_dir, "logo." + art))
        except FileNotFoundError:
            pass
    con.execute("DELETE FROM einstellung WHERE schluessel = 'logo'")
