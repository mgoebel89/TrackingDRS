"""Update ueber den Lehrerbereich (nur Admins).

Der Webdienst darf nichts installieren (eigener Benutzer, ProtectSystem=strict). Er legt nur eine leere Anfrage-Datei in
<daten>/update/ ab: "pruefen" oder "ausfuehren". systemd-.path-Units sehen die Datei und starten als root
trackingdrs-selbstupdate (deploy/selbstupdate.sh). Das holt den neuesten Stand von GitHub, legt vor einem Update eine
Sicherung in <daten>/sicherungen/ an und schreibt die Ergebnisse nach /var/lib/trackingdrs-update:
  stand.json     letzte Pruefung: installiert, verfuegbar, Aenderungen (taeglich und auf Knopfdruck)
  lauf.json      letztes Update: beginn, ende, ergebnis (ok | fehler)
  protokoll.txt  Ausgabe des letzten Updates
"""
import json
import os
import re

from . import VERSION, db

STAND_DIR = os.environ.get("TRACKINGDRS_UPDATE_DIR", "/var/lib/trackingdrs-update")
EINHEIT = os.environ.get("TRACKINGDRS_UPDATE_EINHEIT", "/etc/systemd/system/trackingdrs-update-ausfuehren.path")
ARTEN = ("pruefen", "ausfuehren")
SICHERUNG = re.compile(r"vor-update-[0-9_-]+\.zip")


class UpdateFehler(Exception):
    pass


def _json(name):
    try:
        with open(os.path.join(STAND_DIR, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _protokoll():
    try:
        with open(os.path.join(STAND_DIR, "protokoll.txt"), encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-200:])
    except OSError:
        return ""


def sicherungen(daten_dir):
    ordner = os.path.join(daten_dir, "sicherungen")
    try:
        namen = [n for n in os.listdir(ordner) if SICHERUNG.fullmatch(n)]
    except OSError:
        return []
    return [{"name": n, "groesse": os.path.getsize(os.path.join(ordner, n))} for n in sorted(namen, reverse=True)]


def eingerichtet():
    return os.path.exists(EINHEIT)


def kurz():
    """Fuer /api/ich (Admins): gibt es eine neuere Version?"""
    s = _json("stand.json") or {}
    if not eingerichtet() or not s.get("neu") or (s.get("installiert") or {}).get("version") != VERSION:
        return None
    return {"neu": s["neu"], "version": (s.get("verfuegbar") or {}).get("version")}


def stand(daten_dir):
    anfrage = os.path.join(daten_dir, "update")
    lauf = _json("lauf.json")
    return {
        "eingerichtet": eingerichtet(),
        "version": VERSION,
        "pruefung": _json("stand.json"),
        "lauf": lauf,
        "laeuft": bool(lauf and lauf.get("beginn") and not lauf.get("ende")),
        "wartet": {a: os.path.exists(os.path.join(anfrage, a)) for a in ARTEN},
        "protokoll": _protokoll(),
        "sicherungen": sicherungen(daten_dir),
    }


def anfordern(daten_dir, art):
    if art not in ARTEN:
        raise UpdateFehler("Unbekannte Aktion.")
    if not eingerichtet():
        raise UpdateFehler("Das Update über die Seite geht nur im Container (nach dem nächsten Update über die Konsole).")
    s = stand(daten_dir)
    if s["laeuft"] or s["wartet"]["ausfuehren"]:
        raise UpdateFehler("Es läuft schon ein Update.")
    ordner = os.path.join(daten_dir, "update")
    os.makedirs(ordner, exist_ok=True)
    with open(os.path.join(ordner, art), "w", encoding="utf-8") as f:
        f.write(db.jetzt())


def sicherung_pfad(daten_dir, name):
    if not SICHERUNG.fullmatch(name or ""):
        raise UpdateFehler("Diese Sicherung gibt es nicht.")
    pfad = os.path.join(daten_dir, "sicherungen", name)
    if not os.path.isfile(pfad):
        raise UpdateFehler("Diese Sicherung gibt es nicht.")
    return pfad


def sicherung_ablegen(con, daten_dir, behalten=5):
    """Sicherung vor einem Update (Konsole: trackingdrs sicherung). Die aeltesten ueber `behalten` werden geloescht."""
    import shutil
    from . import extras
    ordner = os.path.join(daten_dir, "sicherungen")
    os.makedirs(ordner, mode=0o750, exist_ok=True)
    ziel = os.path.join(ordner, "vor-update-%s.zip" % db.jetzt()[:19].replace("T", "_").replace(":", "-"))   # 2026-11-02_14-05-33
    shutil.move(extras.sicherung(con, daten_dir), ziel)
    os.chmod(ziel, 0o640)
    for alt in sicherungen(daten_dir)[behalten:]:
        os.remove(os.path.join(ordner, alt["name"]))
    return ziel
